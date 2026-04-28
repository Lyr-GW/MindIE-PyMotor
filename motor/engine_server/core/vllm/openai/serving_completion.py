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

from http import HTTPStatus
from typing import Any

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from vllm.engine.protocol import EngineClient
from vllm.entrypoints.logger import RequestLogger

from motor.engine_server.core.vllm.vllm_openai_compat import (
    get_openai_base_model_path_and_serving_models_types,
    get_openai_chat_and_completion_request_types,
    get_openai_chat_and_completion_response_types,
    get_openai_error_response_type,
    get_vllm_openai_serving_completion_class,
    kwargs_matching_signature,
)

_, OpenAIServingModels = get_openai_base_model_path_and_serving_models_types()
_, CompletionRequest = get_openai_chat_and_completion_request_types()
_, CompletionResponse = get_openai_chat_and_completion_response_types()
ErrorResponse = get_openai_error_response_type()
VllmOpenAIServingCompletion = get_vllm_openai_serving_completion_class()


class OpenAIServingCompletion:
    def __init__(
        self,
        engine_client: EngineClient,
        models: Any,
        *,
        request_logger: RequestLogger | None,
        return_tokens_as_token_ids: bool = False,
        enable_prompt_tokens_details: bool = False,
        enable_force_include_usage: bool = False,
        openai_serving_render: Any | None = None,
    ):
        comp_kw: dict[str, Any] = {
            "request_logger": request_logger,
            "return_tokens_as_token_ids": return_tokens_as_token_ids,
            "enable_prompt_tokens_details": enable_prompt_tokens_details,
            "enable_force_include_usage": enable_force_include_usage,
        }
        if openai_serving_render is not None:
            comp_kw["openai_serving_render"] = openai_serving_render
        comp_kw = kwargs_matching_signature(VllmOpenAIServingCompletion.__init__, comp_kw)
        self._vllm_serving_completion = VllmOpenAIServingCompletion(
            engine_client,
            models,
            **comp_kw,
        )

    async def handle_request(self, request: Any, raw_request: Request):
        try:
            generator = await self._vllm_serving_completion.create_completion(
                request, raw_request
            )
        except OverflowError as e:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST.value, detail=str(e)
            )from e
        except Exception as e:
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value, detail=str(e)
            )from e

        if isinstance(generator, ErrorResponse):
            return JSONResponse(
                content=generator.model_dump(), status_code=generator.error.code
            )
        elif isinstance(generator, CompletionResponse):
            return JSONResponse(
                content=generator.model_dump()
            )

        return StreamingResponse(content=generator, media_type="text/event-stream")
