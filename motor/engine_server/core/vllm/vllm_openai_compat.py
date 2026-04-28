# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
#
# MindIE is licensed under both the Mulan PSL v2 and the Apache License, Version 2.0.

"""Helpers to support multiple vLLM OpenAI serving API shapes (with/without OpenAIServingRender)."""

from __future__ import annotations

import importlib
import inspect
from typing import Any, Callable


def kwargs_matching_signature(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop keys not accepted by *fn* so one code path works across vLLM versions."""
    params = inspect.signature(fn).parameters
    return {k: v for k, v in kwargs.items() if k in params}


def vllm_openai_chat_needs_render() -> bool:
    openai_serving_chat_cls = get_vllm_openai_serving_chat_class()

    return "openai_serving_render" in inspect.signature(openai_serving_chat_cls.__init__).parameters


def get_openai_error_response_type() -> type[Any]:
    """Resolve ErrorResponse class across vLLM API layouts."""
    try:
        module = importlib.import_module("vllm.entrypoints.openai.protocol")
        return module.ErrorResponse
    except ImportError:
        module = importlib.import_module("vllm.entrypoints.openai.engine.protocol")
        return module.ErrorResponse


def get_openai_base_model_path_and_serving_models_types() -> tuple[type[Any], type[Any]]:
    """Resolve BaseModelPath and OpenAIServingModels across vLLM API layouts."""
    try:
        module = importlib.import_module("vllm.entrypoints.openai.serving_models")
        return module.BaseModelPath, module.OpenAIServingModels
    except ImportError:
        protocol_module = importlib.import_module("vllm.entrypoints.openai.models.protocol")
        serving_module = importlib.import_module("vllm.entrypoints.openai.models.serving")
        return protocol_module.BaseModelPath, serving_module.OpenAIServingModels


def get_vllm_openai_serving_chat_class() -> type[Any]:
    """Resolve vLLM OpenAIServingChat implementation class across API layouts."""
    try:
        module = importlib.import_module("vllm.entrypoints.openai.serving_chat")
        return module.OpenAIServingChat
    except ImportError:
        module = importlib.import_module("vllm.entrypoints.openai.chat_completion.serving")
        return module.OpenAIServingChat


def get_vllm_openai_serving_completion_class() -> type[Any]:
    """Resolve vLLM OpenAIServingCompletion implementation class across API layouts."""
    try:
        module = importlib.import_module("vllm.entrypoints.openai.serving_completion")
        return module.OpenAIServingCompletion
    except ImportError:
        module = importlib.import_module("vllm.entrypoints.openai.completion.serving")
        return module.OpenAIServingCompletion


def get_openai_chat_and_completion_request_types() -> tuple[type[Any], type[Any]]:
    """Resolve request protocol classes across vLLM API layouts."""
    try:
        module = importlib.import_module("vllm.entrypoints.openai.protocol")
        return module.ChatCompletionRequest, module.CompletionRequest
    except ImportError:
        chat_module = importlib.import_module(
            "vllm.entrypoints.openai.chat_completion.protocol"
        )
        completion_module = importlib.import_module(
            "vllm.entrypoints.openai.completion.protocol"
        )
        return chat_module.ChatCompletionRequest, completion_module.CompletionRequest


def get_openai_chat_and_completion_response_types() -> tuple[type[Any], type[Any]]:
    """Resolve response protocol classes across vLLM API layouts."""
    try:
        module = importlib.import_module("vllm.entrypoints.openai.protocol")
        return module.ChatCompletionResponse, module.CompletionResponse
    except ImportError:
        chat_module = importlib.import_module(
            "vllm.entrypoints.openai.chat_completion.protocol"
        )
        completion_module = importlib.import_module(
            "vllm.entrypoints.openai.completion.protocol"
        )
        return chat_module.ChatCompletionResponse, completion_module.CompletionResponse
