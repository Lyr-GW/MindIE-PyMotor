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

"""Shared constants and request-info helpers for PD/CDP recompute."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from motor.common.logger import get_logger
from motor.coordinator.models.constants import OpenAIField

# Coordinator-only keys: must not be forwarded to the inference engine JSON body.
_CUMULATIVE_COMPLETION_TOKENS_KEY = "_cumulative_completion_tokens"
_CLIENT_RETURN_TOKEN_IDS_KEY = "_client_return_token_ids"
_COORDINATOR_ONLY_REQ_KEYS = frozenset(
    {"_origin_max_tokens", _CUMULATIVE_COMPLETION_TOKENS_KEY, _CLIENT_RETURN_TOKEN_IDS_KEY}
)

# Set on ``request_info`` when ``stop_reason=recomputed`` but ``recompute_enabled`` is off.
RECOMPUTE_BLOCKED_BY_POLICY_KEY = "recompute_blocked_by_policy"

# Chat-only fields removed when switching recompute retry to OpenAI Completions body.
_CHAT_ONLY_KEYS_RECOMPUTE = frozenset(
    {
        OpenAIField.MESSAGES,
        "tools",
        "tool_choice",
        "functions",
        "function_call",
        "modalities",
        "parallel_tool_calls",
        "response_format",
        "reasoning_effort",
        "include_reasoning",
        "audio",
        "metadata",
    }
)

_recompute_log = get_logger(__name__)


def recompute_disabled_http_exception() -> HTTPException:
    """Raised when the engine signals recompute but ops disabled Coordinator-side retry."""
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Coordinator recompute is disabled (exception_config.recompute_enabled=false)."
        ),
    )


def extract_content_from_choice(choice: dict) -> str:
    """Extract textual content from choice delta/message/text."""
    delta = choice.get(OpenAIField.DELTA) or {}
    message = choice.get(OpenAIField.MESSAGE) or {}
    raw = (
        delta.get(OpenAIField.CONTENT)
        or message.get(OpenAIField.CONTENT)
        or choice.get(OpenAIField.TEXT)
        or ""
    )
    return raw if isinstance(raw, str) else ""


def extract_request_info(req_data: dict) -> dict:
    """Build mutable ``request_info`` for stream recompute tracking."""
    stream_flag = bool(req_data.get(OpenAIField.STREAM, False))
    chat_flag = OpenAIField.MESSAGES in req_data
    origin_max_tokens = req_data.get(
        "_origin_max_tokens", req_data.get(OpenAIField.MAX_TOKENS, 16)
    )

    return {
        "stream_flag": stream_flag,
        "chat_flag": chat_flag,
        "origin_prompt": _origin_prompt_for_recompute(req_data),
        "origin_max_tokens": origin_max_tokens,
        "generated_token": "",
        OpenAIField.COMPLETION_TOKENS: 0,
        "cached_prompt_token_ids": None,
        "cached_output_token_ids": [],
        "client_return_token_ids": bool(req_data.get(_CLIENT_RETURN_TOKEN_IDS_KEY, False)),
    }


def _origin_prompt_for_recompute(req_data: dict) -> Any:
    """Completions ``prompt`` if present; else first chat message ``content``; else empty."""
    if OpenAIField.PROMPT in req_data:
        return req_data[OpenAIField.PROMPT]
    messages = req_data.get(OpenAIField.MESSAGES) or []
    if not messages:
        return ""
    first = messages[0]
    if not isinstance(first, dict):
        return ""
    return first.get(OpenAIField.CONTENT, "")