# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
#
# MindIE is licensed under both the Mulan PSL v2 and the Apache License, Version 2.0.

"""Helpers to support multiple vLLM OpenAI serving API shapes (with/without OpenAIServingRender)."""

from __future__ import annotations

import inspect
from typing import Any, Callable


def kwargs_matching_signature(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop keys not accepted by *fn* so one code path works across vLLM versions."""
    params = inspect.signature(fn).parameters
    return {k: v for k, v in kwargs.items() if k in params}


def vllm_openai_chat_needs_render() -> bool:
    from vllm.entrypoints.openai.chat_completion.serving import OpenAIServingChat

    return "openai_serving_render" in inspect.signature(OpenAIServingChat.__init__).parameters
