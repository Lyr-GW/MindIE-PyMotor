#!/usr/bin/env python3
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