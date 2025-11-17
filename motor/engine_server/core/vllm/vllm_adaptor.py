#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import json
from typing import AsyncIterable, AsyncGenerator, Any
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from motor.common.utils.logger import get_logger
from motor.engine_server.constants.constants import (
    APPLICATION_JSON,
    TEXT_EVENT_STREAM,
    CONTENT_TYPE,
    CONTENT_LENGTH,
    TRANSFER_ENCODING,
    CHUNKED_ENCODING,
    CHAT_COMPLETION_PREFIX,
    COMPLETION_PREFIX,
    COMPLETIONS_PATH,
    CHAT_COMPLETIONS_PATH,
    JSON_ID_FIELD,
    DATA_PREFIX,
    DATA_DONE
)


logger = get_logger("engine_server")


def trim_id_prefix(json_data: dict[str, Any]) -> None:
    if JSON_ID_FIELD not in json_data:
        return
    original_id = json_data[JSON_ID_FIELD]
    if original_id.startswith(CHAT_COMPLETION_PREFIX):
        json_data[JSON_ID_FIELD] = original_id.replace(CHAT_COMPLETION_PREFIX, "")
    elif original_id.startswith(COMPLETION_PREFIX):
        json_data[JSON_ID_FIELD] = original_id.replace(COMPLETION_PREFIX, "")


async def create_single_chunk_iter(content: bytes) -> AsyncGenerator[bytes, None]:
    yield content


async def trim_request_for_non_stream(
        original_content: bytes,
        content_type: str,
        charset: str = "utf-8"
) -> bytes:
    if not content_type.startswith(APPLICATION_JSON):
        return original_content
    try:
        json_data = json.loads(original_content.decode(charset))
        trim_id_prefix(json_data)
        return json.dumps(json_data).encode(charset)
    except Exception as e:
        logger.error(f"Failed to trim request id for {original_content}: {e}")
    return original_content


async def trim_request_for_stream(
        original_iterable: AsyncIterable[bytes],
        charset: str = "utf-8"
) -> AsyncGenerator[bytes, None]:
    async for chunk in original_iterable:
        chunk_str = chunk.decode(charset)
        if chunk_str.startswith(DATA_DONE):
            yield chunk
            continue
        if chunk_str.startswith(DATA_PREFIX):
            json_part = chunk_str[len(DATA_PREFIX):].strip()
            try:
                if json_part:
                    json_data = json.loads(json_part)
                    trim_id_prefix(json_data)
                    modified_text = f"{DATA_PREFIX}{json.dumps(json_data, separators=(',', ':'))}"
                    if chunk_str.endswith('\n\n'):
                        modified_text += '\n\n'
                    elif chunk_str.endswith('\n'):
                        modified_text += '\n'
                    modify_chunk = modified_text.encode(charset)
                else:
                    raise ValueError(f"json_part is empty: {chunk_str}")
            except Exception as e:
                logger.error(f"Failed to trim request content {chunk}: {e}")
                modify_chunk = chunk
        else:
            logger.warning(f"chunk not startswith data: {chunk_str}")
            modify_chunk = chunk

        yield modify_chunk



class VllmMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code < 200 or response.status_code >= 300:
            return response
        if request.url.path not in [COMPLETIONS_PATH, CHAT_COMPLETIONS_PATH]:
            return response
        response_content_type = response.headers.get(CONTENT_TYPE, '')
        logger.debug(f"response_content_type: {response_content_type}")
        if APPLICATION_JSON in response_content_type:
            original_content = b"".join([chunk async for chunk in response.body_iterator])
            modify_content = await trim_request_for_non_stream(original_content, response_content_type)
            response.body_iterator = create_single_chunk_iter(modify_content)
            response.headers[CONTENT_LENGTH] = str(len(modify_content))
        elif TEXT_EVENT_STREAM in response_content_type:
            response.body_iterator = trim_request_for_stream(
                response.body_iterator,
                response.charset
            )
            response.headers[TRANSFER_ENCODING] = CHUNKED_ENCODING
        return response
