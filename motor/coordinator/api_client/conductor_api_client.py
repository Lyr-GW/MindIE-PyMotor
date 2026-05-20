#!/usr/bin/env python3
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

import threading
from typing import Any

from motor.common.logger import get_logger
from motor.common.resources.instance import Instance, Endpoint, PDRole
from motor.common.http.http_client import SafeHTTPSClient
from motor.common.utils.log_throttle import IntervalLogThrottle, StateLogThrottle
from motor.config.coordinator import CoordinatorConfig


TENANT_ID = "default"
logger = get_logger(__name__)


# Module-level throttles. Keep them at module level so every call site shares
# the same state machine; resetting per-instance state would let log spam back
# in through any caller that creates a fresh client.
_QUERY_RESULT_THROTTLE = StateLogThrottle(heartbeat_seconds=60.0)
_QUERY_ERROR_THROTTLE = IntervalLogThrottle(interval_seconds=30.0)
_REGISTER_ERROR_THROTTLE = IntervalLogThrottle(interval_seconds=30.0)


class ConductorApiClient():
    coordinator_config = CoordinatorConfig.from_json()

    # ------------------------------------------------------------------
    # Registration bookkeeping
    # ------------------------------------------------------------------
    # We track which (instance_id, endpoint_id) pairs have been *successfully*
    # registered with kv-conductor since this process started, and which are
    # still pending due to transport / 5xx failures. ``resync_registrations``
    # retries the pending set; instance_manager wires it into a periodic task
    # so a slow conductor start no longer leaves the scheduler with an empty
    # tenant forever.
    _registration_lock: threading.RLock = threading.RLock()
    _registered_keys: set[tuple[int, int]] = set()
    _pending_registrations: dict[tuple[int, int], tuple[Instance, Endpoint]] = {}

    @staticmethod
    def register_kv_instance(
        instances: list[Instance]
    ) -> None:
        """
        register_kv_instance.

        :returns:
        """
        logger.info("register_kv_instance started.")

        for instance in instances:
            if instance.role != PDRole.ROLE_P:
                continue
            for endpoint in instance.endpoints.values():
                for ep in endpoint.values():
                    ConductorApiClient().register_post(instance, ep)

    @staticmethod
    def unregister_kv_instance(
        instances: list[Instance]
    ) -> None:
        """
        unregister_kv_instance.

        :returns:
        """
        logger.info("unregister_kv_instance started.")

        for instance in instances:
            if instance.role != PDRole.ROLE_P:
                continue
            for endpoint in instance.endpoints.values():
                for ep in endpoint.values():
                    ConductorApiClient().unregister_post(instance, ep)

    @classmethod
    def register_post(
        cls, instance: Instance, endpoint: Endpoint
    ) -> bool:
        """Register a single (instance, endpoint) pair with kv-conductor.

        Returns ``True`` when the POST succeeded; ``False`` otherwise (kv
        endpoint config malformed, transport error, etc.). Failed pairs are
        recorded in ``_pending_registrations`` so :meth:`resync_registrations`
        can retry them later without the caller having to track state.
        """
        prefill_kv_event_config = cls.coordinator_config.prefill_kv_event_config
        kv_endpoints = prefill_kv_event_config.endpoint.split("*:")
        if kv_endpoints.__len__() != 2:
            logger.debug(f"kv_endpoints size not 2  :  {prefill_kv_event_config.endpoint}")
            return False

        instance_id = f"vllm-prefill-{instance.id}"
        register_data: dict = {
            "endpoint": f"{kv_endpoints[0]}{endpoint.ip}:{str(int(kv_endpoints[1]) + endpoint.id)}",
            "type": prefill_kv_event_config.engine_type,
            "modelname": instance.model_name,
            "block_size": prefill_kv_event_config.block_size,
            "instance_id": instance_id,
            "dp_rank": endpoint.id,
        }
        if TENANT_ID != "default":
            register_data["tenant_id"] = TENANT_ID


        if prefill_kv_event_config.replay_endpoint != "":
            replay_endpoints = prefill_kv_event_config.replay_endpoint.split("*:")
            if replay_endpoints.__len__() == 2:
                replay_endpoint = f"{replay_endpoints[0]}{endpoint.ip}:{str(int(replay_endpoints[1]) + endpoint.id)}"
                register_data["replay_endpoint"] = replay_endpoint

        client_args = {
            "address": f"{prefill_kv_event_config.conductor_service}:{prefill_kv_event_config.http_server_port}"
        }
        key = (instance.id, endpoint.id)
        try:
            with SafeHTTPSClient(timeout=2, **client_args) as client:
                client.post("/register", register_data)
                logger.info(f"Register success! {instance_id}")
            cls._mark_registered(key)
            logger.debug(f"register_data : {register_data}")
            return True
        except Exception as e:
            cls._mark_pending(key, instance, endpoint)
            should_log, suppressed = _REGISTER_ERROR_THROTTLE.should_log(
                f"register:{client_args.get('address', 'unknown')}"
            )
            if should_log:
                suffix = (
                    f" (suppressed {suppressed} similar errors)" if suppressed else ""
                )
                logger.error(
                    "Exception occurred while register to controller at %s: %s%s",
                    client_args.get('address', 'unknown'), e, suffix,
                )
            else:
                logger.debug(
                    "Register retry pending for %s @ %s: %s",
                    instance_id, client_args.get('address', 'unknown'), e,
                )
            return False

    @classmethod
    def unregister_post(
        cls, instance: Instance, endpoint: Endpoint
    ) -> None:
        """
        unregister_kv_instance.

        :returns:
        """
        prefill_kv_event_config = cls.coordinator_config.prefill_kv_event_config
        instance_id = f"vllm-prefill-{instance.id}"
        register_data: dict = {
            "type": prefill_kv_event_config.engine_type,
            "modelname": instance.model_name,
            "block_size": prefill_kv_event_config.block_size,
            "instance_id": instance_id,
            "dp_rank": endpoint.id,
        }
        if TENANT_ID != "default":
            register_data["tenant_id"] = TENANT_ID

        client_args = {
            "address": f"{prefill_kv_event_config.conductor_service}:{prefill_kv_event_config.http_server_port}"
        }
        key = (instance.id, endpoint.id)
        try:
            with SafeHTTPSClient(timeout=2, **client_args) as client:
                client.post("/unregister", register_data)
                logger.info(f"UnRegister success! {instance_id}")
        except Exception as e:
            logger.error(
                "Exception occurred while register to controller at %s: %s",
                client_args.get('address', 'unknown'), e
            )
        finally:
            cls._forget_registration(key)
        logger.debug(f"unregister_data : {register_data}")
        return

    @classmethod
    def query_conductor(
        cls, instances: list[Instance], encoded_ids: list[int]
    ) -> dict[str, Any]:
        """Query kv-conductor for prefix-match statistics.

        Logging here is on the request hot path; we keep WARN-level signal
        ("tenant has no data right now") but only on state transitions to
        avoid drowning operators in repeats. The full response body is logged
        at DEBUG.
        """
        prefill_kv_event_config = cls.coordinator_config.prefill_kv_event_config
        query_data: dict = {
            "model": instances[0].model_name,
            "block_size": prefill_kv_event_config.block_size,
            "token_ids": encoded_ids,
        }
        if TENANT_ID != "default":
            query_data["tenant_id"] = TENANT_ID

        logger.debug(f"query_data : {query_data}")

        client_args = {
            "address": f"{prefill_kv_event_config.conductor_service}:{prefill_kv_event_config.http_server_port}"
        }
        try:
            with SafeHTTPSClient(timeout=0.2, **client_args) as client:
                response = client.post("/query", query_data)
                cls._log_query_result(response, client_args.get('address', 'unknown'))
                return response
        except Exception as e:
            should_log, suppressed = _QUERY_ERROR_THROTTLE.should_log(
                f"query:{client_args.get('address', 'unknown')}"
            )
            if should_log:
                suffix = (
                    f" (suppressed {suppressed} similar errors)" if suppressed else ""
                )
                logger.error(
                    "Exception occurred while register to controller at %s: %s%s",
                    client_args.get('address', 'unknown'), e, suffix,
                )
            else:
                logger.debug(
                    "query_conductor failure at %s: %s",
                    client_args.get('address', 'unknown'), e,
                )
        return {}

    # ------------------------------------------------------------------
    # Resync API
    # ------------------------------------------------------------------

    @classmethod
    def resync_registrations(cls) -> int:
        """Re-attempt registration for any (instance, endpoint) that previously
        failed to register. Returns the number of pairs that succeeded on this
        attempt.

        Safe to call from any thread; the registration lock serialises the
        snapshot+drain of pending work. Pairs that still fail stay pending and
        will be retried on the next call.
        """
        with cls._registration_lock:
            pending = list(cls._pending_registrations.items())
        if not pending:
            return 0

        recovered = 0
        for key, (instance, endpoint) in pending:
            if cls.register_post(instance, endpoint):
                recovered += 1
            else:
                logger.debug("resync still failing for %s", key)
        if recovered:
            logger.info(
                "resync_registrations: recovered %d/%d pending registration(s)",
                recovered, len(pending),
            )
        return recovered

    @classmethod
    def pending_registration_count(cls) -> int:
        """Test/diagnostic helper - number of registrations still failing."""
        with cls._registration_lock:
            return len(cls._pending_registrations)

    @classmethod
    def registered_count(cls) -> int:
        """Test/diagnostic helper - number of successful registrations."""
        with cls._registration_lock:
            return len(cls._registered_keys)

    @classmethod
    def reset_registration_state_for_testing(cls) -> None:
        with cls._registration_lock:
            cls._registered_keys.clear()
            cls._pending_registrations.clear()
        _QUERY_RESULT_THROTTLE.reset()
        _QUERY_ERROR_THROTTLE.reset()
        _REGISTER_ERROR_THROTTLE.reset()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _mark_registered(cls, key: tuple[int, int]) -> None:
        with cls._registration_lock:
            cls._registered_keys.add(key)
            cls._pending_registrations.pop(key, None)

    @classmethod
    def _mark_pending(
        cls, key: tuple[int, int], instance: Instance, endpoint: Endpoint
    ) -> None:
        with cls._registration_lock:
            cls._pending_registrations[key] = (instance, endpoint)
            cls._registered_keys.discard(key)

    @classmethod
    def _forget_registration(cls, key: tuple[int, int]) -> None:
        with cls._registration_lock:
            cls._registered_keys.discard(key)
            cls._pending_registrations.pop(key, None)

    @classmethod
    def _log_query_result(cls, response: Any, address: str) -> None:
        """State-aware logging for /query responses.

        State key is the boolean ``has_useful_data`` plus the address; we
        transition-log so a stuck "empty response" condition fires once per
        heartbeat instead of once per request.
        """
        has_useful_data = isinstance(response, dict) and bool(
            response.get(TENANT_ID)
        )
        state = (address, has_useful_data)
        should_log, suppressed = _QUERY_RESULT_THROTTLE.should_log(state)
        if not should_log:
            logger.debug("query_conductor result at %s: %s", address, response)
            return
        suffix = (
            f" (suppressed {suppressed} similar messages)" if suppressed else ""
        )
        if has_useful_data:
            logger.info(
                "query_conductor at %s returned data for tenant=%s%s",
                address, TENANT_ID, suffix,
            )
        else:
            logger.warning(
                "query_conductor at %s returned no engine data for tenant=%s; "
                "scheduler will fall back to load_balance until registrations "
                "land%s",
                address, TENANT_ID, suffix,
            )
