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

from typing import Any

from motor.common.logger import get_logger
from motor.common.resources.instance import Instance, Endpoint, PDRole
from motor.common.http.http_client import SafeHTTPSClient
from motor.config.coordinator import CoordinatorConfig


TENANT_ID = "default"
logger = get_logger(__name__)


def _is_instance_affinity_entry(value: Any) -> bool:
    """True if *value* looks like a conductor instance affinity stats object."""
    return isinstance(value, dict) and "longest_matched" in value


class ConductorApiClient():
    coordinator_config = CoordinatorConfig.from_json()

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
    ) -> None:
        """
        unregister_kv_instance.

        :returns:
        """
        prefill_kv_event_config = cls.coordinator_config.prefill_kv_event_config
        kv_endpoints = prefill_kv_event_config.endpoint.split("*:")
        if kv_endpoints.__len__() != 2:
            logger.warning(
                "skip kv-conductor register: prefill_kv_event_config.endpoint must be "
                "host:port template with '*' placeholder (e.g. tcp://*:5557), got %r",
                prefill_kv_event_config.endpoint,
            )
            return

        instance_id = f"vllm-prefill-{instance.id}"
        register_data: dict = {
            "endpoint": f"{kv_endpoints[0]}{endpoint.ip}:{str(int(kv_endpoints[1]) + endpoint.id)}", 
            "type": prefill_kv_event_config.engine_type,
            "modelname": instance.model_name,
            "block_size": prefill_kv_event_config.block_size,
            "instance_id": instance_id,
            "dp_rank": endpoint.id,
        }
        register_data["tenant_id"] = TENANT_ID

        if prefill_kv_event_config.replay_endpoint != "":
            replay_endpoints = prefill_kv_event_config.replay_endpoint.split("*:")
            if replay_endpoints.__len__() == 2:
                replay_endpoint = f"{replay_endpoints[0]}{endpoint.ip}:{str(int(replay_endpoints[1]) + endpoint.id)}"
                register_data["replay_endpoint"] = replay_endpoint

        client_args = {
            "address": f"{prefill_kv_event_config.conductor_service}:{prefill_kv_event_config.http_server_port}"
        }
        try:
            with SafeHTTPSClient(timeout=2, **client_args) as client:
                client.post("/register", register_data)
                logger.info(f"Register success! {instance_id}")

        except Exception as e:
            logger.error(
                "Exception occurred while register to controller at %s: %s",
                client_args.get('address', 'unknown'), e
            )
        logger.info(f"register_data : {register_data}")
        return

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
        register_data["tenant_id"] = TENANT_ID

        client_args = {
            "address": f"{prefill_kv_event_config.conductor_service}:{prefill_kv_event_config.http_server_port}"
        }
        try:
            with SafeHTTPSClient(timeout=2, **client_args) as client:
                client.post("/unregister", register_data)
                logger.info(f"UnRegister success! {instance_id}")

        except Exception as e:
            logger.error(
                "Exception occurred while register to controller at %s: %s",
                client_args.get('address', 'unknown'), e
            )
        logger.info(f"unregister_data : {register_data}")
        return

    @classmethod
    def _normalize_query_response(cls, response: dict[str, Any]) -> dict[str, Any]:
        """Normalize Mooncake conductor /query bodies to ``{tenant_id: {instance_id: stats}}``.

        Conductor versions differ:
        - RFC flat map: ``{"vllm-prefill-1": {"longest_matched": N, ...}}``
        - Wrapped: ``{"data": {"default": {...}}}`` or ``{"data": {"vllm-prefill-1": ...}}``
        - Legacy tenant map: ``{"default": {"vllm-prefill-1": ...}}``
        """
        if not response:
            return {}

        payload: dict[str, Any] = response
        if "data" in response and isinstance(response["data"], dict):
            payload = response["data"]

        if not payload:
            return {}

        tenant_payload = payload.get(TENANT_ID)
        if isinstance(tenant_payload, dict):
            return {TENANT_ID: tenant_payload}

        if any(_is_instance_affinity_entry(v) for v in payload.values()):
            return {TENANT_ID: payload}

        return payload

    @classmethod
    def query_conductor(
        cls, instances: list[Instance], encoded_ids: list[int]
    ) -> dict[str, Any]:
        """
        Query kv-conductor for per-instance KV prefix match lengths.

        :returns: Normalized map ``{tenant_id: {instance_id: affinity_stats}}``.
        """
        prefill_kv_event_config = cls.coordinator_config.prefill_kv_event_config
        query_data: dict = {
            "model": instances[0].model_name,
            "block_size": prefill_kv_event_config.block_size,
            "token_ids": encoded_ids,
            "tenant_id": TENANT_ID,
        }

        logger.debug(f"query_data : {query_data}")

        client_args = {
            "address": f"{prefill_kv_event_config.conductor_service}:{prefill_kv_event_config.http_server_port}"
        }
        try:
            with SafeHTTPSClient(timeout=0.2, **client_args) as client:
                raw = client.post("/query", query_data)
                normalized = cls._normalize_query_response(raw or {})
                logger.info(
                    "query success! raw=%s normalized_tenant_instances=%d",
                    raw,
                    len(normalized.get(TENANT_ID, {}) or {}),
                )
                return normalized
        except Exception as e:
            logger.error(
                "Exception occurred while query to conductor at %s: %s",
                client_args.get('address', 'unknown'), e
            )
        return {}