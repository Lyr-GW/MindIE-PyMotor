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
    """8-hex-char fingerprint of the token sequence for trace correlation.

    Cheap to compute and short enough to grep in logs. Used to verify that two
    coordinator-side renderings (with vs without tools) produce different
    token sequences, which is the strongest operator-visible signal that
    tools really enter the conductor query.
    """
    if not encoded_ids:
        return "00000000"
    raw = ",".join(str(i) for i in encoded_ids).encode("utf-8")
    return hashlib.blake2b(raw, digest_size=4).hexdigest()


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
        """Mirror the subset of vLLM ChatCompletionRequest fields that change
        the rendered token sequence (see ``vllm/entrypoints/openai/chat_
        completion/protocol.py``).

        Any field that vLLM forwards to ``tokenizer.apply_chat_template`` MUST
        be forwarded here as well; otherwise the coordinator's encoded ids
        drift from what the prefill engine actually sees and conductor's
        ``longest_matched`` lies.
        """
        return {
            "chat_template": req_data.get(OpenAIField.CHAT_TEMPLATE),
            "chat_template_kwargs": req_data.get(OpenAIField.CHAT_TEMPLATE_KWARGS),
            "documents": req_data.get(OpenAIField.DOCUMENTS),
            "add_generation_prompt": req_data.get(
                OpenAIField.ADD_GENERATION_PROMPT, True
            ),
            "continue_final_message": req_data.get(
                OpenAIField.CONTINUE_FINAL_MESSAGE, False
            ),
        }

    @staticmethod
    def _emit_tools_in_cache_proof(
        manager: "TokenizerManager",
        messages: Optional[list],
        tools: Optional[list],
        chat_template_params: dict[str, Any],
        encoded_ids: list[int],
    ) -> Optional[int]:
        """Side-channel proof that ``tools`` actually inflated the encoded ids.

        Returns the *without-tools* encoded id length on success, ``None`` if
        the request carries no tools (nothing to prove) or the side-channel
        tokenize itself fails.

        We compare the request rendered ``with tools`` (the live path) and
        ``without tools`` (side-channel). If ``tools_token_delta > 0`` the
        operator has byte-level evidence that conductor's ``longest_matched``
        is computed over the tools-rendered prefix.

        This log is always emitted at INFO whenever ``tools`` is present, so
        operators do not need to flip any environment variable to see the
        proof. The cost is one extra tokenize call per function-call request
        on the affinity hot path; this trade-off is accepted because the
        proof line is the only evidence linking tokenize correctness to
        conductor's cache decision.
        """
        if not tools:
            return None
        if messages is None:
            return None
        try:
            ids_without_tools = manager.apply_chat_template(
                messages, None, **chat_template_params
            )
        except Exception as e:
            logger.warning(
                "kv_affinity tools-in-cache side-channel failed (continuing): %s", e
            )
            return None

        # Side-channel returned empty -> the no-tools tokenize fell back to
        # ``[]`` (e.g. its own ``_safe_fallback_encode`` exhausted retries).
        # Reporting ``tools_token_delta = len(encoded_ids) - 0`` would
        # misleadingly look like "tools added all tokens". Skip the proof
        # entirely and tell the operator where to look instead.
        if not ids_without_tools:
            logger.warning(
                "kv_affinity tools-in-cache side-channel returned empty token list; "
                "skipping proof line (check upstream tokenize fail-closed ERROR logs)."
            )
            return None

        delta = len(encoded_ids) - len(ids_without_tools)
        logger.info(
            "kv_affinity tools-in-cache proof: msgs=%d tools=%d "
            "ids_with_tools=%d ids_without_tools=%d tools_token_delta=%d "
            "fp_with=%s fp_without=%s",
            len(messages or []),
            len(tools or []),
            len(encoded_ids or []),
            len(ids_without_tools or []),
            delta,
            _fingerprint_ids(encoded_ids),
            _fingerprint_ids(ids_without_tools),
        )
        if delta <= 0:
            logger.warning(
                "kv_affinity tools-in-cache proof DEGENERATE: tools_token_delta=%d "
                "(<=0). Either the tokenizer chat template silently drops tools, "
                "or the model's template does not surface tools as tokens. "
                "Conductor `longest_matched` for function-call requests will not "
                "reflect the tools schema in this configuration.",
                delta,
            )
        return len(ids_without_tools)

    @staticmethod
    def _emit_hit_analysis(
        instance_id: Any,
        longest_matched: int,
        encoded_ids_len: int,
        ids_without_tools_len: Optional[int],
        block_size: int,
    ) -> None:
        """Log a Mooncake-conductor-aligned breakdown of the cache hit.

        Conductor's `/query` semantics (see
        https://kvcache-ai.github.io/Mooncake/design/conductor/indexer-api-design.html):
        - Token ids are split into complete blocks of ``block_size`` tokens.
        - Each block produces a rolling sequence hash; the prefix table is
          scanned in order, the first miss terminates the scan.
        - ``longest_matched`` is the matched-prefix length **in tokens**,
          always a multiple of ``block_size`` (trailing partial block is
          ignored).

        This log gives operators the four numbers they need to reason about
        the hit:
            ids=A blk=BS matched=M (= blk*K) hit_ratio=M/A
        Plus a verdict on whether the hit clearly covers the tools section
        (present whenever ``tools`` was on the request and the side-channel
        tokenize succeeded; absent for plain chat requests with no tools).
        """
        if not encoded_ids_len:
            return
        ratio_pct = (longest_matched * 100.0) / encoded_ids_len if encoded_ids_len else 0.0
        matched_blocks = longest_matched // block_size if block_size else 0
        verdict = ""
        if ids_without_tools_len is not None and ids_without_tools_len < encoded_ids_len:
            # Tools added new tokens; check whether the hit extends past
            # them. If longest_matched > ids_without_tools_len, the matched
            # prefix necessarily covers tokens that come from the tools
            # section.
            if longest_matched > ids_without_tools_len:
                verdict = " verdict=tools_in_hit"
            elif longest_matched == ids_without_tools_len:
                verdict = " verdict=tools_at_hit_boundary"
            else:
                verdict = " verdict=tools_not_in_hit"
        logger.info(
            "kv_affinity hit analysis: instance=%s ids=%d blk=%d "
            "longest_matched=%d matched_blocks=%d hit_ratio=%.2f%%%s",
            instance_id,
            encoded_ids_len,
            block_size,
            longest_matched,
            matched_blocks,
            ratio_pct,
            verdict,
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

        # Visibility for the validated invariant: tools, when present, MUST
        # inflate the encoded token sequence. Operators can grep this line to
        # verify function-call requests are being tokenised correctly.
        # Emitted at INFO so it shows up in default production logs without
        # any extra configuration.
        logger.info(
            "kv_affinity tokenize ok: msgs=%d tools=%d encoded_ids=%d fp=%s",
            len(messages or []),
            len(tools or []),
            len(encoded_ids or []),
            _fingerprint_ids(encoded_ids),
        )
        ids_without_tools_len = KvCacheAffinityPolicy._emit_tools_in_cache_proof(
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
        KvCacheAffinityPolicy._emit_hit_analysis(
            selected_instance.id,
            max_kv_matched,
            len(encoded_ids or []),
            ids_without_tools_len,
            block_size,
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
        """Merge the vLLM-aligned chat-template kwargs into one dict.

        Precedence (mirrors ``ChatParams.get_apply_chat_template_kwargs`` in
        vLLM): explicit request-body fields override anything carried inside
        the request-body ``chat_template_kwargs`` dict.
        """
        merged: dict[str, Any] = dict(chat_template_kwargs or {})
        # ``return_dict=False`` keeps the API contract stable across
        # transformers v4 / v5 (v5 default would otherwise be True and break
        # the ``list[int]`` return when ``tokenize=True``); same trick vLLM
        # uses in `safe_apply_chat_template`.
        merged["return_dict"] = False
        # Hard-pin these so a stray ``chat_template_kwargs`` entry can't
        # downgrade the rendering and de-sync from the inference engine.
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

        The output token sequence is the *same* one vLLM/SGLang sees during
        actual inference, so conductor's ``longest_matched`` truly reflects the
        cluster's KV-cache distribution. ``tools`` MUST be forwarded on every
        path - dropping it silently was the bug fixed in the previous
        revision.

        Extra kwargs mirror the subset of vLLM ``ChatCompletionRequest``
        fields that change the rendered prompt:

        * ``chat_template`` - request-supplied template body or named variant.
        * ``chat_template_kwargs`` - free-form dict forwarded to the template
          (e.g. Qwen3 ``enable_thinking``, RAG ``documents`` extras, custom
          flags model-specific templates expect).
        * ``documents`` - explicit list of retrieval documents.
        * ``add_generation_prompt`` - default ``True``; the request body may
          disable it for assistant continuation.
        * ``continue_final_message`` - lets the template continue the last
          assistant message instead of starting a new one.
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
        """Standard OpenAI-compatible model path.

        Calls the model tokenizer's jinja chat-template directly with
        ``tools`` and ``tokenize=True`` so the resulting token ids are
        byte-equivalent to what vLLM/SGLang prefill receives. All
        vLLM-aligned chat-template kwargs (``chat_template``, ``documents``,
        ``add_generation_prompt``, ``continue_final_message`` plus any
        request-supplied ``chat_template_kwargs``) come pre-merged in
        ``tpl_kwargs``.
        """
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
        """Non-standard model path: normalise messages/tools then encode the
        rendered prompt string. Kept for models whose chat-template cannot be
        directly invoked with ``tokenize=True`` (e.g. require argument
        coercion or reordering done by ``preprocess_input``).
        """
        messages_copy, tools_copy = preprocess_input(messages, tools)

        # In the non-standard branch we must render first (``tokenize=False``)
        # and re-encode the string, so override only the ``tokenize`` flag and
        # ``return_dict`` while keeping every other vLLM-aligned kwarg
        # (``chat_template``, ``documents``, ``add_generation_prompt`` ...).
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
        """Last-resort tokenize that NEVER drops ``tools``.

        Tries the tools-aware standard call once more; if that also fails,
        returns ``[]`` so :meth:`KvCacheAffinityPolicy.select_endpoint_from_list`
        can surface a None and let the upper scheduler fall back to LB.
        Returning a partially-correct token list (e.g. messages without tools)
        would silently mislead conductor's longest_matched and is far worse
        than failing closed.
        """
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
