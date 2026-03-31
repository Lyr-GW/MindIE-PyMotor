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

"""Adapt vLLM OpenAI Completion responses to Chat Completion shape for client contract."""

from __future__ import annotations

from typing import Any

from motor.coordinator.models.constants import OpenAIField


def _lift_prompt_token_ids_from_choice(
    choice: dict[str, Any], response: dict[str, Any]
) -> None:
    """Move ``prompt_token_ids`` from a completion choice to the top-level response if absent."""
    pti = choice.pop(OpenAIField.PROMPT_TOKEN_IDS, None)
    if pti is not None and response.get(OpenAIField.PROMPT_TOKEN_IDS) is None:
        response[OpenAIField.PROMPT_TOKEN_IDS] = pti


def _chat_completion_id(req_id: str) -> str:
    base = req_id.replace("cmpl-", "").replace("chatcmpl-", "")
    return f"chatcmpl-{base}"


def is_completion_like_stream_chunk(chunk_json: dict[str, Any]) -> bool:
    """True if chunk looks like a text_completion stream object (not chat chunk)."""
    if chunk_json.get("object") == "text_completion":
        return True
    choices = chunk_json.get(OpenAIField.CHOICES) or []
    if not choices:
        return False
    c0 = choices[0]
    if c0.get(OpenAIField.DELTA):
        return False
    return OpenAIField.TEXT in c0


def adapt_completion_stream_chunk_to_chat(
    chunk_json: dict[str, Any],
    *,
    req_id: str,
    stream_state: dict[str, Any],
) -> None:
    """Mutate ``chunk_json`` in place: Completion stream chunk → ``chat.completion.chunk``."""
    chunk_json["object"] = "chat.completion.chunk"
    chunk_json["id"] = _chat_completion_id(req_id)

    choices = chunk_json.get(OpenAIField.CHOICES) or []
    if not choices:
        return
    c0 = choices[0]
    idx = c0.get("index", 0)
    text = c0.pop(OpenAIField.TEXT, None) or ""
    finish_reason = c0.pop("finish_reason", None)
    stop_reason = c0.pop("stop_reason", None)
    # Completion logprobs shape differs from Chat; omit unless mapped (see SPEC).
    c0.pop("logprobs", None)

    _lift_prompt_token_ids_from_choice(c0, chunk_json)

    delta: dict[str, Any] = {}
    if not stream_state.get("stream_role_sent"):
        delta["role"] = "assistant"
        stream_state["stream_role_sent"] = True
    if text:
        delta["content"] = text

    c0.clear()
    c0["index"] = idx
    c0[OpenAIField.DELTA] = delta
    if finish_reason is not None:
        c0["finish_reason"] = finish_reason
    if stop_reason is not None:
        c0["stop_reason"] = stop_reason


def adapt_completion_nonstream_to_chat(body: dict[str, Any], *, req_id: str) -> None:
    """Mutate ``body`` in place: ``text_completion`` → ``chat.completion``."""
    body["object"] = "chat.completion"
    body["id"] = _chat_completion_id(req_id)

    choices = body.get(OpenAIField.CHOICES) or []
    if not choices:
        return
    c0 = choices[0]
    text = c0.pop(OpenAIField.TEXT, None) or ""
    finish_reason = c0.pop("finish_reason", None)
    stop_reason = c0.pop("stop_reason", None)
    token_ids = c0.pop(OpenAIField.TOKEN_IDS, None)
    c0.pop("logprobs", None)
    c0.pop("prompt_logprobs", None)

    _lift_prompt_token_ids_from_choice(c0, body)

    c0.clear()
    c0["index"] = 0
    c0[OpenAIField.MESSAGE] = {
        OpenAIField.ROLE: "assistant",
        OpenAIField.CONTENT: text,
    }
    if finish_reason is not None:
        c0["finish_reason"] = finish_reason
    if stop_reason is not None:
        c0["stop_reason"] = stop_reason
    if token_ids is not None:
        c0[OpenAIField.TOKEN_IDS] = token_ids
