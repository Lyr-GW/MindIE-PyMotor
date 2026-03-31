# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
#
# MindIE is licensed under both the Mulan PSL v2 and the Apache License, Version 2.0.
# You may choose to use this software under the terms of either license.
#
# ---------------------------------------------------------------------------
# Mulan PSL v2:
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
#
# Apache License, Version 2.0:
# You may obtain a copy of the License at:
#         http://www.apache.org/licenses/LICENSE-2.0
# ---------------------------------------------------------------------------
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the respective licenses for more details.

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from vllm.entrypoints.chat_utils import load_chat_template
from vllm.entrypoints.logger import RequestLogger
from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
from vllm.entrypoints.openai.completion.protocol import CompletionRequest
from vllm.entrypoints.openai.models.protocol import BaseModelPath
from vllm.entrypoints.openai.models.serving import OpenAIServingModels
from vllm.entrypoints.utils import process_lora_modules

from motor.common.utils.logger import get_logger
from motor.engine_server.core.infer_endpoint import InferEndpoint, CONFIG_KEY
from motor.engine_server.core.vllm.vllm_engine import VLLMEngine
from motor.engine_server.core.vllm.openai.serving_chat import OpenAIServingChat
from motor.engine_server.core.vllm.openai.serving_completion import OpenAIServingCompletion
from motor.engine_server.core.vllm.vllm_openai_compat import (
    kwargs_matching_signature,
    vllm_openai_chat_needs_render,
)

logger = get_logger(__name__)


@asynccontextmanager
async def _vllm_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Set app.state in lifespan (runs in the process that serves requests)."""
    config = app.extra.get(CONFIG_KEY)
    if not config:
        raise ValueError(
            "VLLM lifespan: app.extra[CONFIG_KEY] not set (init_request_handlers not called)."
        )
    args = config.get_args()
    engine = VLLMEngine(config)
    engine_client = engine.launch()
    if engine_client is None:
        raise ValueError("VLLM lifespan: engine_client not found.")
    logger.info("InferEndpoint lifespan: Initializing engine_client...")

    try:
        await engine_client.reset_mm_cache()
        logger.info("InferEndpoint lifespan: Engine_client initialized successfully")

        async def vllm_health_checker() -> bool:
            try:
                await engine_client.check_health()
                return True
            except Exception:
                logger.error("VLLM health check failed")
                return False

        app.state.health_checker = vllm_health_checker
        app.state.engine_client = engine_client

        supported_tasks = await engine_client.get_supported_tasks()
        resolved_chat_template = load_chat_template(args.chat_template)
        vllm_config = engine_client.vllm_config

        default_mm_loras = (
            vllm_config.lora_config.default_mm_loras
            if vllm_config.lora_config is not None
            else {}
        )
        lora_modules = process_lora_modules(args.lora_modules, default_mm_loras)

        if args.served_model_name is not None:
            served_model_names = args.served_model_name
        else:
            served_model_names = [args.model]

        if args.enable_log_requests:
            request_logger = RequestLogger(max_log_len=args.max_log_len)
        else:
            request_logger = None

        base_model_paths = [BaseModelPath(name=name, model_path=args.model) for name in served_model_names]

        openai_serving_models = OpenAIServingModels(
            engine_client=engine_client,
            base_model_paths=base_model_paths,
            lora_modules=lora_modules,
        )
        app.state.openai_serving_models = openai_serving_models

        openai_serving_render = None
        if vllm_openai_chat_needs_render():
            try:
                from vllm.entrypoints.serve.render.serving import OpenAIServingRender
            except ImportError as e:
                raise RuntimeError(
                    "Installed vLLM expects OpenAIServingRender (chat serving API); "
                    "use a complete matching vLLM build or an older vLLM without the render layer."
                ) from e
            render_kw = {
                "model_config": engine_client.model_config,
                "renderer": engine_client.renderer,
                "io_processor": engine_client.io_processor,
                "model_registry": openai_serving_models.registry,
                "request_logger": request_logger,
                "chat_template": resolved_chat_template,
                "chat_template_content_format": args.chat_template_content_format,
                "trust_request_chat_template": getattr(args, "trust_request_chat_template", False),
                "enable_auto_tools": getattr(args, "enable_auto_tool_choice", False),
                "exclude_tools_when_tool_choice_none": getattr(
                    args, "exclude_tools_when_tool_choice_none", False
                ),
                "tool_parser": getattr(args, "tool_call_parser", None),
                "default_chat_template_kwargs": getattr(args, "default_chat_template_kwargs", None),
                "log_error_stack": getattr(args, "log_error_stack", False),
            }
            render_kw = kwargs_matching_signature(OpenAIServingRender.__init__, render_kw)
            openai_serving_render = OpenAIServingRender(**render_kw)

        try:
            app.state.openai_serving_chat = OpenAIServingChat(
                engine_client=engine_client,
                models=openai_serving_models,
                response_role=args.response_role,
                request_logger=request_logger,
                chat_template=resolved_chat_template,
                chat_template_content_format=args.chat_template_content_format,
                openai_serving_render=openai_serving_render,
            ) if "generate" in supported_tasks else None

            app.state.openai_serving_completion = OpenAIServingCompletion(
                engine_client=engine_client,
                models=openai_serving_models,
                request_logger=request_logger,
                return_tokens_as_token_ids=getattr(args, "return_tokens_as_token_ids", False),
                enable_prompt_tokens_details=getattr(args, "enable_prompt_tokens_details", False),
                enable_force_include_usage=getattr(args, "enable_force_include_usage", False),
                openai_serving_render=openai_serving_render,
            ) if "generate" in supported_tasks else None

            logger.info("InferEndpoint lifespan: Serving components created successfully")
        except Exception as e:
            logger.error(f"InferEndpoint lifespan: Failed to create serving components: {e}")
            raise

        yield
        engine.shutdown()
        logger.info("InferEndpoint lifespan: Engine_client cleanup completed")
    except Exception as e:
        logger.error(f"InferEndpoint lifespan: Failed to initialize or manage engine_client: {e}")
        raise


class VLLMEndpoint(InferEndpoint):

    def get_lifespan(self):
        return _vllm_lifespan

    def init_request_handlers(self) -> None:
        self.chat_completion_request = ChatCompletionRequest
        self.completion_request = CompletionRequest
