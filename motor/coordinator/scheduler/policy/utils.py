# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

import copy
import json
from typing import List, Optional
from motor.coordinator.models.constants import OpenAIField


def preprocess_input(
    messages: List[dict], 
    tools: Optional[List[dict]] = None
    ) -> tuple[List[dict], Optional[List[dict]]]:
    """
    Preprocessing Input Messages and Tools Listed in the Table Below.
    
    Args:
        messages: message list
        tools: (Optional) Tool List
        
    Returns:
        tuple: (List of processed messages, List of processed tools)
    """
    processing_messages = [
        exchange_arguments,
        exchange_tool_content
    ]
    processing_tools = [
        exchange_tools
    ]

    processed_messages = copy.deepcopy(messages)
    for message in processed_messages:
        for processing in processing_messages:
            processing(message)

    processed_tools = None
    if tools:
        processed_tools = copy.deepcopy(tools)
        for tool in processed_tools:
            for processing in processing_tools:
                processing(tool)

    return processed_messages, processed_tools


def exchange_arguments(message: dict) -> None:
    """
    Converts the tool call arguments in the message from a string to a JSON object.

    Args:
        message: Message dictionary containing tool invoking information.

    Returns:
        None: The message dictionary is modified in place.
    """
    if OpenAIField.TOOLS_CALLS not in message:
        return
    for tool in message[OpenAIField.TOOLS_CALLS]:
        if OpenAIField.FUNCTION not in tool:
            continue
        if isinstance(tool[OpenAIField.FUNCTION][OpenAIField.ARGUMENTS], str):
            tool[OpenAIField.FUNCTION][OpenAIField.ARGUMENTS] = json.loads(
                tool[OpenAIField.FUNCTION][OpenAIField.ARGUMENTS])


def exchange_tool_content(message: dict) -> None:
    """
    Message content format of the conversion tool.

    Args:
        message: Dictionary containing the message content.

    Returns:
        None: The input message dictionary is directly modified.
    """
    if OpenAIField.ROLE not in message:
        return
    if message[OpenAIField.ROLE] != "tool":
        return
    if OpenAIField.CONTENT not in message:
        return
    content = message[OpenAIField.CONTENT]
    if isinstance(content, str):
        exchange_content = {
            "type": "text",
            "text": content
        }
        message[OpenAIField.CONTENT] = f"{exchange_content}"


def exchange_tools(tool: dict) -> None:
    """
    Sort the fields of the tool function to ensure the fields are arranged according to the specified priority.

    Args:
        tool: a dictionary containing tool information

    Returns:
        None: The passed tool dictionary is modified directly
    """
    if OpenAIField.FUNCTION not in tool:
        return

    max_seq = 100
    priority = {"name": 1, "description": 2, "parameters": 3}
    tool[OpenAIField.FUNCTION] = dict(sorted(tool[OpenAIField.FUNCTION].items(), 
                                                key=lambda x: priority.get(x[0], max_seq)))
