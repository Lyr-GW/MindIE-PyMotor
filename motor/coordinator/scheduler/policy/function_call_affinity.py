# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Function-call affinity scheduling policy.

Augments :class:`KvCacheAffinityPolicy` with a sticky routing layer keyed by a
fingerprint of the request's ``tools`` schema. The motivation is that
agent / function-call workloads typically reuse a stable set of tool
definitions across many requests; serving such requests on the same instance
maximises KV-cache reuse even when the conductor's longest-prefix match is
unavailable.

Selection order (per call):

1. If the request carries a tools fingerprint AND the cache holds a still-valid
   record whose ``(instance, endpoint)`` is still in the candidate list, return
   it directly (sticky route).
2. Otherwise fall back to :meth:`KvCacheAffinityPolicy.select_endpoint_from_list`.
3. Otherwise fall back to :class:`LoadBalancePolicy`.
4. The successful selection (if any) is recorded in the fingerprint cache.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from motor.common.logger import get_logger
from motor.common.resources.endpoint import Endpoint
from motor.common.resources.instance import Instance, PDRole
from motor.coordinator.domain import InstanceProvider
from motor.coordinator.models.constants import OpenAIField
from motor.coordinator.models.request import RequestInfo
from motor.coordinator.scheduler.policy.base import BaseSchedulingPolicy
from motor.coordinator.scheduler.policy.kv_cache_affinity import (
    KvCacheAffinityPolicy,
)
from motor.coordinator.scheduler.policy.load_balance import LoadBalancePolicy

logger = get_logger(__name__)


# Default cache parameters; deliberately conservative to bound memory footprint.
_DEFAULT_CACHE_SIZE: int = 1024
_DEFAULT_TTL_SECONDS: float = 600.0  # 10 minutes

# KV-cache-unavailable circuit breaker: after this many consecutive empty
# responses from the conductor, we skip the conductor RPC entirely for
# ``_KV_COOLDOWN_SECONDS`` and rely on sticky+load-balance routing. After the
# cooldown we make a single probe attempt; if it still returns empty, the
# cooldown is extended.
_KV_FAILURE_THRESHOLD: int = 3
_KV_COOLDOWN_SECONDS: float = 30.0


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def extract_tools(req_data: Any) -> Optional[list]:
    """Return the ``tools`` list from a request payload, or ``None``.

    Defensive against ``None`` / non-dict inputs so callers can use it on
    arbitrary :class:`~motor.coordinator.models.request.RequestInfo.req_data`
    blobs without try/except guards.
    """
    if not isinstance(req_data, dict):
        return None
    tools = req_data.get(OpenAIField.TOOLS)
    if not tools:
        return None
    return tools


def has_function_call_signal(req_data: Any) -> bool:
    """Return ``True`` if the request looks like a function/tool-call request.

    A request qualifies when either:

    * it carries a non-empty top-level ``tools`` field, or
    * any message contains a non-empty ``tool_calls`` list.
    """
    if not isinstance(req_data, dict):
        return False
    if extract_tools(req_data) is not None:
        return True
    messages = req_data.get(OpenAIField.MESSAGES)
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        tool_calls = msg.get(OpenAIField.TOOLS_CALLS)
        if isinstance(tool_calls, list) and len(tool_calls) > 0:
            return True
    return False


def compute_tools_fingerprint(tools: Optional[Iterable[dict]]) -> Optional[str]:
    """Compute a stable SHA256 fingerprint of a tools schema.

    Tool dicts are canonicalised via ``json.dumps(..., sort_keys=True)`` so
    requests that differ only in key insertion order yield identical
    fingerprints. The order of *tools* in the list is preserved (it can affect
    chat-template rendering and therefore prefix locality).

    Returns ``None`` for an empty/None input or when the structure is not
    JSON-serialisable.
    """
    if not tools:
        return None
    try:
        normalised = [
            json.dumps(tool, sort_keys=True, ensure_ascii=False, default=str)
            for tool in tools
        ]
    except (TypeError, ValueError) as exc:
        logger.debug("compute_tools_fingerprint: non-serialisable tools: %s", exc)
        return None
    # Defensive: bytes inside dict values can sneak past ``default=str`` only
    # because str(bytes) succeeds; we want such inputs to fail-soft rather than
    # silently produce surprising fingerprints.
    if any(isinstance(_v, (bytes, bytearray)) for tool in tools for _v in _walk_values(tool)):
        return None
    payload = "\x1f".join(normalised).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _walk_values(obj: Any):
    """Yield all leaf values inside arbitrarily nested dict/list structures."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_values(v)
    else:
        yield obj


# -----------------------------------------------------------------------------
# LRU + TTL cache
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class AffinityRecord:
    """Immutable record stored per fingerprint in the affinity cache."""

    instance_id: int
    endpoint_id: int
    inserted_at: float


class ToolsAffinityCache:
    """Thread-safe LRU + TTL cache mapping ``fingerprint -> AffinityRecord``.

    Designed to be cheap on the hot path (single ``RLock`` acquisition per
    call) and bounded in memory via ``max_size``. Stale entries are evicted
    lazily on read; this avoids a background thread and keeps the data
    structure self-contained.
    """

    def __init__(
        self,
        max_size: int = _DEFAULT_CACHE_SIZE,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.RLock()
        self._data: "OrderedDict[str, AffinityRecord]" = OrderedDict()

    def get(self, fingerprint: str) -> Optional[AffinityRecord]:
        if fingerprint is None:
            return None
        with self._lock:
            record = self._data.get(fingerprint)
            if record is None:
                return None
            if (time.monotonic() - record.inserted_at) > self._ttl:
                # Expired: evict and report miss.
                self._data.pop(fingerprint, None)
                return None
            self._data.move_to_end(fingerprint)
            return record

    def put(self, fingerprint: str, instance_id: int, endpoint_id: int) -> None:
        if fingerprint is None:
            return
        with self._lock:
            self._data.pop(fingerprint, None)  # ensure move-to-end semantics
            self._data[fingerprint] = AffinityRecord(
                instance_id=instance_id,
                endpoint_id=endpoint_id,
                inserted_at=time.monotonic(),
            )
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def size(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# -----------------------------------------------------------------------------
# KV-affinity circuit breaker
# -----------------------------------------------------------------------------


class KvAffinityCircuitBreaker:
    """Tracks consecutive empty conductor responses to short-circuit RPC calls.

    The breaker has three logical states:

    * ``closed`` (default) - every selection tries
      :meth:`KvCacheAffinityPolicy.select_endpoint_from_list`.
    * ``open`` - reached when ``failure_threshold`` consecutive empties are
      observed; the breaker suppresses the conductor RPC for
      ``cooldown_seconds`` and the policy falls straight through to sticky +
      load-balance.
    * ``half-open`` - automatically entered when ``cooldown_seconds`` elapses;
      the next selection performs one probe RPC. A successful probe resets the
      breaker, a failure restarts the cooldown clock.

    A failure on the very first call also opens the breaker conservatively
    enough that the *second* call is the one that decides whether to probe; we
    do not want to ping the conductor on every request when it's clearly down.
    """

    def __init__(
        self,
        failure_threshold: int = _KV_FAILURE_THRESHOLD,
        cooldown_seconds: float = _KV_COOLDOWN_SECONDS,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._lock = threading.RLock()
        self._consecutive_failures = 0
        self._open_until: Optional[float] = None  # monotonic deadline or None

    def allow_request(self) -> bool:
        """Return True when the caller should attempt the conductor RPC."""
        with self._lock:
            if self._open_until is None:
                return True
            if time.monotonic() >= self._open_until:
                # Half-open: allow exactly one probe; the result will reset or
                # extend the cooldown via record_success / record_failure.
                self._open_until = None
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._open_until = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._open_until = time.monotonic() + self._cooldown

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._open_until is None:
                return False
            if time.monotonic() >= self._open_until:
                return False
            return True

    def reset(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._open_until = None


# -----------------------------------------------------------------------------
# Policy
# -----------------------------------------------------------------------------


# Module-level cache used by the static helper. Instance methods get a private
# cache by default, so multiple policy instances do not bleed state into each
# other unless callers opt in by using the static helper.
_GLOBAL_AFFINITY_CACHE = ToolsAffinityCache()
_GLOBAL_KV_BREAKER = KvAffinityCircuitBreaker()


class FunctionCallAffinityPolicy(BaseSchedulingPolicy):
    """Function-call aware affinity policy.

    Behaves like :class:`KvCacheAffinityPolicy` but adds a sticky-routing layer
    keyed by the tools fingerprint. Provides both an instance-bound API
    (``select_endpoint_from_list_with_cache``) and a static helper
    (``select_endpoint_from_list``) that delegates to a process-wide cache so
    it can be used from contexts that don't carry a policy instance (e.g.
    :mod:`motor.coordinator.scheduler.runtime.scheduler_client`).
    """

    def __init__(
        self,
        instance_provider: InstanceProvider,
        affinity_cache: Optional[ToolsAffinityCache] = None,
        kv_breaker: Optional[KvAffinityCircuitBreaker] = None,
    ) -> None:
        super().__init__(instance_provider=instance_provider)
        self._instance_provider = instance_provider
        self.affinity_cache: ToolsAffinityCache = affinity_cache or ToolsAffinityCache()
        self.kv_breaker: KvAffinityCircuitBreaker = (
            kv_breaker or KvAffinityCircuitBreaker()
        )
        logger.info("FunctionCallAffinityPolicy started.")

    # ------------------------------------------------------------------ static

    @staticmethod
    def select_endpoint_from_list(
        instances: list[Instance], req_info: RequestInfo
    ) -> Optional[tuple[Instance, Endpoint]]:
        """Static entry-point used by the scheduler runtime.

        Uses the module-level cache so that successive calls (potentially from
        different policy invocations on the same process) share state.
        """
        return _select(instances, req_info, _GLOBAL_AFFINITY_CACHE, _GLOBAL_KV_BREAKER)

    @staticmethod
    def reset_global_cache_for_testing() -> None:
        """Clear the process-wide cache. Intended for unit tests only."""
        _GLOBAL_AFFINITY_CACHE.clear()
        _GLOBAL_KV_BREAKER.reset()

    # ----------------------------------------------------------------- instance

    def select_endpoint_from_list_with_cache(
        self, instances: list[Instance], req_info: RequestInfo
    ) -> Optional[tuple[Instance, Endpoint]]:
        """Instance-bound variant that uses ``self.affinity_cache``."""
        return _select(instances, req_info, self.affinity_cache, self.kv_breaker)

    def _select_instance(self, _: PDRole = None) -> Optional[Instance]:
        # Like KvCacheAffinityPolicy, the per-list selection is the canonical
        # entry-point; the abstract instance-only path is unused.
        return None

    def _select_endpoint(self, _: Instance) -> Optional[Endpoint]:
        return None


# -----------------------------------------------------------------------------
# Internal selection algorithm
# -----------------------------------------------------------------------------


def _select(
    instances: list[Instance],
    req_info: RequestInfo,
    cache: ToolsAffinityCache,
    breaker: KvAffinityCircuitBreaker,
) -> Optional[tuple[Instance, Endpoint]]:
    if not instances:
        return None

    req_data = getattr(req_info, "req_data", None)
    fingerprint: Optional[str] = None
    if has_function_call_signal(req_data):
        fingerprint = compute_tools_fingerprint(extract_tools(req_data) or [])

    # 1) Sticky route - cheapest; depends only on local cache.
    if fingerprint is not None:
        sticky = _try_sticky(cache, fingerprint, instances)
        if sticky is not None:
            logger.debug(
                "function_call_affinity sticky-hit: instance=%s endpoint=%s",
                sticky[0].id,
                sticky[1].id,
            )
            return sticky

    # 2) KV-cache affinity - skipped while the breaker is open so we do not
    # hammer the conductor with a per-request RPC that we already know returns
    # empty.
    if breaker.allow_request():
        kv_pair = _safe_kv_select(instances, req_info)
        if kv_pair is not None:
            breaker.record_success()
            if fingerprint is not None:
                cache.put(fingerprint, kv_pair[0].id, kv_pair[1].id)
            return kv_pair
        breaker.record_failure()
    else:
        logger.debug(
            "function_call_affinity: KV breaker open, skipping conductor RPC"
        )

    # 3) Load-balance fallback
    lb_pair = _load_balance_select(instances)
    if lb_pair is not None and fingerprint is not None:
        cache.put(fingerprint, lb_pair[0].id, lb_pair[1].id)
    return lb_pair


def _try_sticky(
    cache: ToolsAffinityCache,
    fingerprint: str,
    instances: list[Instance],
) -> Optional[tuple[Instance, Endpoint]]:
    record = cache.get(fingerprint)
    if record is None:
        return None
    instance = next((i for i in instances if i.id == record.instance_id), None)
    if instance is None:
        return None
    for ep in instance.get_all_endpoints():
        if ep.id == record.endpoint_id:
            return (instance, ep)
    return None


def _safe_kv_select(
    instances: list[Instance], req_info: RequestInfo
) -> Optional[tuple[Instance, Endpoint]]:
    try:
        return KvCacheAffinityPolicy.select_endpoint_from_list(instances, req_info)
    except Exception as exc:
        logger.warning(
            "function_call_affinity: KV cache affinity failed: %s", exc
        )
        return None


def _load_balance_select(
    instances: list[Instance],
) -> Optional[tuple[Instance, Endpoint]]:
    instance = LoadBalancePolicy.select_instance_from_list(instances)
    if instance is None:
        return None
    endpoint = LoadBalancePolicy.select_endpoint_from_instance(instance)
    if endpoint is None:
        return None
    return (instance, endpoint)
