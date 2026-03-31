# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.

from motor.coordinator.router.adapters.completion_to_chat import (
    adapt_completion_nonstream_to_chat,
    adapt_completion_stream_chunk_to_chat,
    is_completion_like_stream_chunk,
)


def test_is_completion_like_stream_chunk():
    assert is_completion_like_stream_chunk(
        {"object": "text_completion", "choices": [{"text": "a"}]}
    )
    assert is_completion_like_stream_chunk({"choices": [{"text": "a"}]})
    assert not is_completion_like_stream_chunk(
        {"choices": [{"delta": {"content": "a"}}]}
    )


def test_adapt_completion_stream_chunk_to_chat():
    chunk = {
        "object": "text_completion",
        "id": "cmpl-old",
        "choices": [
            {"index": 0, "text": "Hi", "finish_reason": None, "prompt_token_ids": [1, 2]}
        ],
    }
    st: dict = {}
    adapt_completion_stream_chunk_to_chat(chunk, req_id="req1", stream_state=st)
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["id"].startswith("chatcmpl-")
    assert chunk["prompt_token_ids"] == [1, 2]
    assert chunk["choices"][0]["delta"]["role"] == "assistant"
    assert chunk["choices"][0]["delta"]["content"] == "Hi"
    assert st["stream_role_sent"] is True


def test_adapt_completion_nonstream_to_chat():
    body = {
        "object": "text_completion",
        "id": "cmpl-x",
        "choices": [
            {
                "index": 0,
                "text": "Hello",
                "finish_reason": "stop",
                "prompt_token_ids": [9, 8],
            }
        ],
    }
    adapt_completion_nonstream_to_chat(body, req_id="rid")
    assert body["object"] == "chat.completion"
    assert body["id"].startswith("chatcmpl-")
    assert body["prompt_token_ids"] == [9, 8]
    assert body["choices"][0]["message"]["content"] == "Hello"
