# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""In-process external-policy runner with fail-open anomaly isolation and cooldown."""

import asyncio
import json
import math
import time
from collections import Counter
from collections.abc import Mapping, Sequence

from motor.common.logger import get_logger
from motor.config.coordinator import PolicyPluginConfig
from motor.coordinator.scheduler.policy.api import (
    CandidateId,
    EndpointSelectionPolicy,
    RankedCandidate,
    SelectionInput,
)
from motor.coordinator.scheduler.policy.plugin_worker import load_policy

logger = get_logger(__name__)

_FALLBACK_REASONS = (
    "busy",
    "unavailable",
    "cooldown",
    "declined",
    "invalid_input",
    "timeout",
    "plugin_error",
    "no_eligible_candidates",
    "membership_changed",
    "cas_retry_limit",
    "snapshot_error",
)

_EXTREME_ANOMALY_TYPES = (SystemExit, MemoryError, RecursionError)


class PolicyRunner:
    """Per-role in-process external policy executor, sharing the worker hot path."""

    def __init__(self, config: PolicyPluginConfig, role: str | None = None) -> None:
        self.config = config
        self.role = role or (config.role[0] if config.role else "unknown")
        self._policy: EndpointSelectionPolicy | None = None
        self._restart_task: asyncio.Task[None] | None = None
        self._starting = False
        self._retry_after = 0.0
        self._closed = False
        self._counts: Counter[str] = Counter()
        self._fallback_reasons: Counter[str] = Counter()
        self._seconds = 0.0

    @staticmethod
    def _validate(raw: Sequence[RankedCandidate], selection: SelectionInput) -> tuple[RankedCandidate, ...]:
        if isinstance(raw, (str, bytes, bytearray, Mapping)) or not isinstance(raw, Sequence):
            raise ValueError("Plugin ranking must be a sequence of RankedCandidate")
        if not raw or len(raw) > len(selection.candidates):
            raise ValueError("Empty or invalid policy ranking")
        allowed = {item.id for item in selection.candidates} - selection.excluded
        seen: set[CandidateId] = set()
        ranked: list[RankedCandidate] = []
        for item in raw:
            if not isinstance(item, RankedCandidate) or not isinstance(item.id, CandidateId):
                raise ValueError("Invalid policy ranking item")
            candidate = item.id
            score = item.score
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (candidate.instance_id, candidate.endpoint_id)
            ):
                raise ValueError("Policy candidate IDs must be integers")
            if candidate not in allowed or candidate in seen:
                raise ValueError("Unknown, excluded or duplicate candidate")
            if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score):
                raise ValueError("Policy score must be finite")
            seen.add(candidate)
            ranked.append(item)
        return tuple(ranked)

    async def start(self) -> None:
        """Preload in a worker thread outside the request path. Errors leave built-in active."""
        if self._closed or self._starting or self._policy is not None or time.monotonic() < self._retry_after:
            return
        self._starting = True
        try:
            policy = await asyncio.wait_for(
                asyncio.to_thread(load_policy, self.config.name, self.config.options),
                timeout=self.config.startup_timeout_ms / 1000,
            )
        except (Exception, SystemExit) as exc:
            if not self._closed:
                self._counts["load_errors"] += 1
                self._record_load_failure(exc)
            return
        finally:
            self._starting = False

        if self._closed:
            return
        self._policy = policy
        self._counts["loads"] += 1
        logger.info(
            "Scheduling plugin loaded name=%s role=%s api_version=2 mode=in_process",
            self.config.name,
            self.role,
        )

    def is_available(self) -> bool:
        """Fast pre-check before constructing SelectionInput; schedules recovery when due."""
        if self._closed:
            self.record_fallback("unavailable")
            return False
        if self._policy is None:
            cooling_down = time.monotonic() < self._retry_after
            if not cooling_down and not self._starting and self._restart_task is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    self._restart_task = loop.create_task(self._restart())
            self.record_fallback("cooldown" if cooling_down else "unavailable")
            return False
        return True

    def rank_sync(self, selection: SelectionInput) -> tuple[RankedCandidate, ...] | None:
        """Synchronously rank candidates in-process; enter cooldown on error or slow call."""
        if not self.is_available():
            return None
        policy = self._policy
        if policy is None:
            self.record_fallback("unavailable")
            return None

        started = time.perf_counter()
        self._counts["calls"] += 1
        try:
            raw = policy.rank(selection)
        except (Exception, SystemExit) as exc:
            elapsed = time.perf_counter() - started
            self._seconds += elapsed
            if self._closed:
                self.record_fallback("unavailable")
                return None
            self._counts["errors"] += 1
            self.record_fallback("plugin_error")
            self._fail(exc, req_id=selection.request.request_id, elapsed_ms=elapsed * 1000.0)
            return None

        elapsed = time.perf_counter() - started
        self._seconds += elapsed
        if self._closed:
            self.record_fallback("unavailable")
            return None
        if elapsed > self.config.timeout_ms / 1000:
            self._counts["timeouts"] += 1
            self.record_fallback("timeout")
            self._fail_timeout(elapsed * 1000.0, req_id=selection.request.request_id)
            return None
        if raw is None:
            self.record_fallback("declined")
            return None
        try:
            return self._validate(raw, selection)
        except ValueError as exc:
            self._counts["errors"] += 1
            self.record_fallback("plugin_error")
            self._fail(exc, req_id=selection.request.request_id, elapsed_ms=elapsed * 1000.0)
            return None

    async def rank(self, selection: SelectionInput) -> tuple[RankedCandidate, ...] | None:
        """Async compatibility wrapper delegating directly to synchronous in-process ranking."""
        return self.rank_sync(selection)

    async def close(self) -> None:
        """Cancel background recovery and drop the policy instance during shutdown."""
        self._closed = True
        if self._restart_task is not None:
            self._restart_task.cancel()
            await asyncio.gather(self._restart_task, return_exceptions=True)
            self._restart_task = None
        self._policy = None

    def metrics_text(self) -> str:
        """Worker-local Prometheus counters; scrape every worker's metaserver."""
        label = "{policy=%s,role=%s}" % (
            json.dumps(self.config.name, ensure_ascii=False),
            json.dumps(self.role, ensure_ascii=False),
        )
        lines = []
        for event in ("loads", "load_errors", "calls", "errors", "timeouts", "fallbacks"):
            name = "motor_policy_%s_total" % event
            lines.extend(("# TYPE %s counter" % name, "%s%s %s" % (name, label, self._counts[event])))
        name = "motor_policy_fallbacks_by_reason_total"
        lines.append("# TYPE %s counter" % name)
        extra_reasons = sorted(r for r in self._fallback_reasons if r not in _FALLBACK_REASONS)
        for reason in (*_FALLBACK_REASONS, *extra_reasons):
            lines.append(
                "%s%s,reason=%s} %s"
                % (name, label[:-1], json.dumps(reason, ensure_ascii=False), self._fallback_reasons[reason])
            )
        lines.append("# TYPE motor_policy_selection_seconds summary")
        lines.append("motor_policy_selection_seconds_sum%s %s" % (label, self._seconds))
        lines.append("motor_policy_selection_seconds_count%s %s" % (label, self._counts["calls"]))
        return "\n".join(lines) + "\n"

    def record_fallback(self, reason: str) -> None:
        """Count both runner and core fallback decisions under a bounded reason label."""
        if reason not in _FALLBACK_REASONS:
            logger.warning(
                "Unknown scheduling plugin fallback reason name=%s role=%s reason=%s",
                self.config.name,
                self.role,
                reason,
            )
        self._counts["fallbacks"] += 1
        self._fallback_reasons[reason] += 1
        logger.debug("Scheduling plugin fallback name=%s role=%s reason=%s", self.config.name, self.role, reason)

    def _record_load_failure(self, exc: BaseException) -> None:
        timed_out = isinstance(exc, asyncio.TimeoutError)
        log_fn = logger.error if isinstance(exc, _EXTREME_ANOMALY_TYPES) else logger.warning
        if timed_out:
            log_fn(
                "Scheduling plugin startup timed out name=%s role=%s startup_timeout_ms=%d "
                "cooldown_seconds=%s; entering cooldown and falling back to configured built-in strategy",
                self.config.name,
                self.role,
                self.config.startup_timeout_ms,
                self.config.cooldown_seconds,
            )
        else:
            log_fn(
                "Scheduling plugin load failed name=%s role=%s reason=%s error=%s "
                "cooldown_seconds=%s; entering cooldown and falling back to configured built-in strategy",
                self.config.name,
                self.role,
                type(exc).__name__,
                str(exc)[:512],
                self.config.cooldown_seconds,
            )
        self._enter_cooldown()

    def _fail(self, exc: BaseException, *, req_id: str | None = None, elapsed_ms: float | None = None) -> None:
        log_fn = logger.error if isinstance(exc, _EXTREME_ANOMALY_TYPES) else logger.warning
        log_fn(
            "Scheduling plugin failed name=%s role=%s req_id=%s reason=%s error=%s "
            "elapsed_ms=%s cooldown_seconds=%s; entering cooldown and falling back to configured built-in strategy",
            self.config.name,
            self.role,
            req_id or "-",
            type(exc).__name__,
            str(exc)[:512],
            "%.2f" % elapsed_ms if elapsed_ms is not None else "-",
            self.config.cooldown_seconds,
        )
        self._enter_cooldown()

    def _fail_timeout(self, elapsed_ms: float, *, req_id: str | None = None) -> None:
        logger.warning(
            "Scheduling plugin exceeded timeout budget name=%s role=%s req_id=%s elapsed_ms=%.2f "
            "timeout_ms=%d cooldown_seconds=%s; in-process call blocked event loop, "
            "entering cooldown and falling back to configured built-in strategy",
            self.config.name,
            self.role,
            req_id or "-",
            elapsed_ms,
            self.config.timeout_ms,
            self.config.cooldown_seconds,
        )
        self._enter_cooldown()

    def _enter_cooldown(self) -> None:
        self._policy = None
        self._retry_after = time.monotonic() + self.config.cooldown_seconds

    async def _restart(self) -> None:
        try:
            await self.start()
        finally:
            self._restart_task = None
