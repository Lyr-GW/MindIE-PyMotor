# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

import hashlib
import os
import threading
from typing import Any, Optional

from motor.common.resources.instance import Instance, PDRole
from motor.common.resources.endpoint import Endpoint
from motor.coordinator.domain import InstanceProvider
from motor.coordinator.scheduler.policy.base import BaseSchedulingPolicy
from motor.config.coordinator import CoordinatorConfig
from motor.common.logger import get_logger
from motor.coordinator.models.constants import OpenAIField
from motor.coordinator.models.request import RequestInfo
from motor.coordinator.api_client.conductor_api_client import ConductorApiClient, TENANT_ID
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.coordinator.scheduler.policy.utils import preprocess_input


logger = get_logger(__name__)


def _fingerprint_ids(encoded_ids: list[int]) -> str:
    """8-hex-char fingerprint of the token sequence for log grep / trace correlation."""
    if not encoded_ids:
        return "00000000"
    raw = ",".join(str(i) for i in encoded_ids).encode("utf-8")
    return hashlib.blake2b(raw, digest_size=4).hexdigest()


def _classify_verdict(longest_matched: int, ids_without_tools_len: Optional[int]) -> str:
    """Return a `verdict=...` suffix telling whether the hit covers the tools section."""
    if ids_without_tools_len is None:
        return ""
    if longest_matched > ids_without_tools_len:
        return " verdict=tools_in_hit"
    if longest_matched == ids_without_tools_len:
        return " verdict=tools_at_hit_boundary"
    return " verdict=tools_not_in_hit"


class KvCacheAffinityPolicy(BaseSchedulingPolicy):
    """
    KvCache Affinity Scheduler Policy implementation.
    Selects instances and endpoints in a kvcache-affinity fashion.
    """

    def __init__(self, instance_provider: InstanceProvider):
        super().__init__(instance_provider=instance_provider)
        self._instance_provider = instance_provider

        logger.info("KvCacheAffinityPolicy started.")

    @staticmethod
    def _extract_chat_template_params(req_data: dict) -> dict[str, Any]:
        """Pull the vLLM-aligned chat-template fields from the request body so
        coordinator-side tokenize matches what the prefill engine renders."""
        return {
            "chat_template": req_data.get(OpenAIField.CHAT_TEMPLATE),
            "chat_template_kwargs": req_data.get(OpenAIField.CHAT_TEMPLATE_KWARGS),
            "documents": req_data.get(OpenAIField.DOCUMENTS),
            "add_generation_prompt": req_data.get(OpenAIField.ADD_GENERATION_PROMPT, True),
            "continue_final_message": req_data.get(OpenAIField.CONTINUE_FINAL_MESSAGE, False),
        }

    @staticmethod
    def _compute_ids_without_tools(
        manager: "TokenizerManager",
        messages: Optional[list],
        tools: Optional[list],
        chat_template_params: dict[str, Any],
        encoded_ids: list[int],
    ) -> Optional[int]:
        """Side-channel re-tokenize with ``tools=None`` to size the tools delta.

        Returns the without-tools id length, or ``None`` when the proof cannot be
        produced (no tools, no messages, side-channel error, or empty fallback).
        Emits the proof line at DEBUG and a WARNING when delta <= 0 (template
        silently drops tools).
        """
        if not tools or messages is None:
            return None
        try:
            ids_without_tools = manager.apply_chat_template(
                messages, None, **chat_template_params
            )
        except Exception as e:
            logger.warning("kv_affinity tools-in-cache side-channel failed: %s", e)
            return None
        if not ids_without_tools:
            logger.warning(
                "kv_affinity tools-in-cache side-channel returned empty token list; "
                "skipping proof line."
            )
            return None

        delta = len(encoded_ids) - len(ids_without_tools)
        logger.debug(
            "kv_affinity tools-in-cache proof: msgs=%d tools=%d ids_with_tools=%d "
            "ids_without_tools=%d tools_token_delta=%d fp_with=%s fp_without=%s",
            len(messages), len(tools), len(encoded_ids), len(ids_without_tools),
            delta, _fingerprint_ids(encoded_ids), _fingerprint_ids(ids_without_tools),
        )
        if delta <= 0:
            logger.warning(
                "kv_affinity tools-in-cache proof DEGENERATE: tools_token_delta=%d "
                "(tokenizer chat template appears to drop tools).",
                delta,
            )
        return len(ids_without_tools)

    @staticmethod
    def _emit_select_debug(
        instance_id: Any,
        longest_matched: int,
        encoded_ids: list[int],
        ids_without_tools_len: Optional[int],
        block_size: int,
        msgs_len: int,
        tools_len: int,
    ) -> None:
        """One DEBUG line summarising tokenize fingerprint, conductor hit and tools verdict."""
        encoded_len = len(encoded_ids)
        if not encoded_len:
            return
        ratio_pct = (longest_matched * 100.0) / encoded_len
        matched_blocks = longest_matched // block_size if block_size else 0
        verdict = _classify_verdict(longest_matched, ids_without_tools_len) \
            if ids_without_tools_len is not None and ids_without_tools_len < encoded_len else ""
        logger.debug(
            "kv_affinity hit analysis: instance=%s msgs=%d tools=%d encoded_ids=%d "
            "fp=%s blk=%d longest_matched=%d matched_blocks=%d hit_ratio=%.2f%%%s",
            instance_id, msgs_len, tools_len, encoded_len, _fingerprint_ids(encoded_ids),
            block_size, longest_matched, matched_blocks, ratio_pct, verdict,
        )

    @staticmethod
    def select_endpoint_from_list(
        instances: list[Instance],
        req_info: RequestInfo
    ) -> tuple[Instance, Endpoint] | None:
        """
        Select an endpoint with the least workload from the given instance.
        """
        encoded_ids: list[int] = []
        req_data = req_info.req_data
        messages = req_data.get(OpenAIField.MESSAGES, None)
        tools = req_data.get(OpenAIField.TOOLS, None)
        chat_template_params = KvCacheAffinityPolicy._extract_chat_template_params(req_data)

        manager = TokenizerManager()
        if messages is not None:
            encoded_ids = manager.apply_chat_template(
                messages, tools, **chat_template_params
            )
        else:
            prompt = req_data.get(OpenAIField.PROMPT, None)
            if prompt is not None:
                encoded_ids = manager.encode(prompt)

        ids_without_tools_len = KvCacheAffinityPolicy._compute_ids_without_tools(
            manager, messages, tools, chat_template_params, encoded_ids
        )

        rsp = ConductorApiClient.query_conductor(instances, encoded_ids)
        tenant = rsp.get(TENANT_ID, None)
        if tenant is None:
            logger.warning(f"tenant is none")
            return None

        block_size = ConductorApiClient.coordinator_config.prefill_kv_event_config.block_size

        max_kv_matched = 0
        max_kv_dp = 0
        selected_instance = None
        selected_endpoint = None
        selected_data_dp = {}
        for instance in instances:
            instance_data = tenant.get(f"vllm-prefill-{instance.id}", None)
            if instance_data is None:
                continue

            data_matched = instance_data.get("longest_matched", 0)
            if data_matched < max_kv_matched:
                continue

            max_kv_matched = data_matched
            selected_instance = instance
            selected_data_dp = instance_data.get("DP", {})

        if selected_instance is None:
            logger.warning(f"selected_instance is None")
            return None

        if not selected_data_dp:
            logger.warning(f"selected_data_dp is None")
            return None

        for endpoint in selected_instance.endpoints.values():
            for ep in endpoint.values():
                kv_dp = selected_data_dp.get(f"{ep.id}", 0)
                if kv_dp < max_kv_dp:
                    continue

                max_kv_dp = kv_dp
                selected_endpoint = ep

        if selected_endpoint is None:
            logger.warning(f"selected_endpoint is None")
            return None
        logger.info(f"select_endpoint: {selected_instance.id}-{selected_endpoint.id}  max_kv_matched:{max_kv_matched}")
        KvCacheAffinityPolicy._emit_select_debug(
            selected_instance.id,
            max_kv_matched,
            encoded_ids,
            ids_without_tools_len,
            block_size,
            len(messages or []),
            len(tools or []),
        )
        return (selected_instance, selected_endpoint)

    def _select_instance(self, _: PDRole = None) -> Instance | None:
        """
        Select an instance with the least workload.
        """
        return None

    def _select_endpoint(self, _: Instance) -> Endpoint | None:
        """
        Select an endpoint with the least workload from the given instance.
        """
        return None


class TokenizerManager(ThreadSafeSingleton):
    """
    Tracer Manager class, Singleton class
    """

    def __init__(self, config: CoordinatorConfig | None = None):
        """TracerManager init"""
        # If the instance manager is already initialized, return.
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.config_lock = threading.RLock()

        if config is None:
            config = CoordinatorConfig()

        self.endpoint = config.tracer_config.endpoint

        self.tokenizer = None

        if config.prefill_kv_event_config.conductor_service == "":
            logger.info("conductor_service is empty. disable TokenizerManager!")
            return

        model_path = config.prefill_kv_event_config.model_path
        if model_path:
            os.environ['TORCH_DEVICE_BACKEND_AUTOLOAD'] = '0'
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

        logger.info(f"TokenizerManager init.(model_path:{model_path})")

        self.openai_standard = os.environ.get("OPENAI_STANDARD", "STANDARD")

    @staticmethod
    def _build_template_kwargs(
        *,
        chat_template: Optional[str],
        chat_template_kwargs: Optional[dict],
        documents: Optional[list],
        add_generation_prompt: bool,
        continue_final_message: bool,
    ) -> dict[str, Any]:
        """Merge vLLM-aligned chat-template kwargs; explicit fields override
        same-named entries inside ``chat_template_kwargs`` (vLLM precedence)."""
        merged: dict[str, Any] = dict(chat_template_kwargs or {})
        # Pin return_dict=False for transformers v5 compat (v5 defaults to True).
        merged["return_dict"] = False
        merged["add_generation_prompt"] = bool(add_generation_prompt)
        if continue_final_message:
            merged["continue_final_message"] = True
        if chat_template is not None:
            merged["chat_template"] = chat_template
        if documents is not None:
            merged["documents"] = documents
        return merged

    def apply_chat_template(
        self,
        messages: list,
        tools: list | None = None,
        *,
        chat_template: Optional[str] = None,
        chat_template_kwargs: Optional[dict] = None,
        documents: Optional[list] = None,
        add_generation_prompt: bool = True,
        continue_final_message: bool = False,
    ) -> list[int]:
        """Render messages (and optional tools) into token ids for KV-cache affinity.

        Output must be byte-equivalent to what vLLM/SGLang prefill sees so
        conductor's ``longest_matched`` reflects real KV-cache distribution.
        ``tools`` MUST be forwarded on every path. The extra keyword-only kwargs
        mirror the vLLM ``ChatCompletionRequest`` fields that change rendering.
        """
        if self.tokenizer is None:
            return []

        tpl_kwargs = self._build_template_kwargs(
            chat_template=chat_template,
            chat_template_kwargs=chat_template_kwargs,
            documents=documents,
            add_generation_prompt=add_generation_prompt,
            continue_final_message=continue_final_message,
        )

        try:
            if self.openai_standard != "STANDARD":
                return self._apply_chat_template_with_preprocess(
                    messages, tools, tpl_kwargs
                )
            return self._apply_chat_template_standard(messages, tools, tpl_kwargs)
        except Exception as e:
            logger.warning(
                "kv_affinity primary tokenize path failed: %s; "
                "trying tools-aware fallback (msgs=%d, tools=%d)",
                e,
                len(messages or []),
                len(tools or []),
            )
            return self._safe_fallback_encode(messages, tools, tpl_kwargs)

    def encode(self, prompt: str) -> list[int]:
        """
        When the inference API /v1/completions is called, 
        this method is used for encoding.
        """
        if self.tokenizer is None:
            return []
        result = self.tokenizer.encode(prompt)
        return result

    def _apply_chat_template_standard(
        self,
        messages: list,
        tools: list | None,
        tpl_kwargs: dict[str, Any],
    ) -> list[int]:
        """Standard path: invoke tokenizer's jinja chat-template directly with
        ``tokenize=True`` so ids are byte-equivalent to prefill engine input."""
        return self.tokenizer.apply_chat_template(
            conversation=messages,
            tools=tools,
            tokenize=True,
            **tpl_kwargs,
        )

    def _apply_chat_template_with_preprocess(
        self,
        messages: list,
        tools: list | None,
        tpl_kwargs: dict[str, Any],
    ) -> list[int]:
        """Non-standard path: normalise messages/tools via preprocess_input,
        render to string with ``tokenize=False`` then encode."""
        messages_copy, tools_copy = preprocess_input(messages, tools)

        render_kwargs = dict(tpl_kwargs)
        render_kwargs["return_dict"] = False
        prompt = self.tokenizer.apply_chat_template(
            conversation=messages_copy,
            tools=tools_copy,
            tokenize=False,
            **render_kwargs,
        )
        return self.tokenizer.encode(prompt)

    def _safe_fallback_encode(
        self,
        messages: list,
        tools: list | None,
        tpl_kwargs: dict[str, Any],
    ) -> list[int]:
        """Last-resort tools-aware retry; on second failure return ``[]`` so the
        scheduler falls back to LoadBalance instead of silently dropping tools."""
        try:
            return self._apply_chat_template_standard(messages, tools, tpl_kwargs)
        except Exception as e:
            logger.error(
                "kv_affinity tokenize failed on both primary and fallback paths; "
                "returning [] so scheduler falls back to LoadBalance. "
                "msgs=%d tools=%d err=%s",
                len(messages or []),
                len(tools or []),
                e,
            )
            return []
