#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

# vllm request_id prefix
# /v1/chat/completions: chatcmpl-xxx
CHAT_COMPLETION_PREFIX = "chatcmpl-"
# /v1/completions: cmpl-xxx-0
COMPLETION_PREFIX = "cmpl-"
COMPLETION_SUFFIX = "-0"

DEFAULT_REQUEST_ID = "unknown"
REQUEST_ID_KEY = "req_id"
REQUEST_DATA_KEY = "req_data"
RESOURCE_KEY = "resource"

# OpenAI request fields (OpenAI-style API schema)
OPENAI_FIELD_MESSAGES = "messages"
OPENAI_FIELD_PROMPT = "prompt"
OPENAI_FIELD_MODEL = "model"
OPENAI_FIELD_STREAM = "stream"
OPENAI_FIELD_ROLE = "role"
OPENAI_FIELD_CONTENT = "content"