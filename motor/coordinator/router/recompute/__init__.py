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

"""Shared helpers for PD/CDP recompute (token-cache retry and request rewrite).

Performance note: per-chunk JSON re-serialization is CPU-bound; ``async`` does not
make it faster. Mitigations here use :mod:`msgspec` (already a dependency) for
compact JSON bytes and fewer temporary allocations on hot paths. Offloading
serialization to ``asyncio.to_thread`` is reserved for unusually large payloads
where event-loop latency matters; typical SSE chunks are cheaper inline.
"""

from __future__ import annotations

__all__ = [
    "RECOMPUTE_BLOCKED_BY_POLICY_KEY",
    "_CUMULATIVE_COMPLETION_TOKENS_KEY",
    "bump_req_id_after_recompute_prepare",
    "build_request_info_for_nonstream_recompute",
    "completions_retry_eligible_for_chat_request",
    "copy_req_data_for_engine",
    "encode_stream_chunk_bytes",
    "extract_content_from_choice",
    "extract_request_info",
    "fill_recompute_kv_from_token_cache",
    "is_recomputed_nonstream_response",
    "modify_req_id_retry_segment",
    "parse_stream_chunk_json",
    "prepare_retry_request",
    "process_stream_chunk",
    "recompute_disabled_http_exception",
    "recompute_limit_reached",
    "strip_nonstream_response_body_for_client",
    "strip_stream_chunk_bytes_for_client",
    "update_completion_tokens",
    "update_nonstream_retry_choice",
    "update_token_id_cache",
    "validate_nonstream_recompute_body",
]

from .common import (
    RECOMPUTE_BLOCKED_BY_POLICY_KEY,
    _CUMULATIVE_COMPLETION_TOKENS_KEY,
    extract_content_from_choice,
    extract_request_info,
    recompute_disabled_http_exception,
)
from .retry import (
    build_request_info_for_nonstream_recompute,
    bump_req_id_after_recompute_prepare,
    completions_retry_eligible_for_chat_request,
    copy_req_data_for_engine,
    is_recomputed_nonstream_response,
    modify_req_id_retry_segment,
    prepare_retry_request,
    recompute_limit_reached,
    update_nonstream_retry_choice,
    validate_nonstream_recompute_body,
)
from .stream import (
    encode_stream_chunk_bytes,
    fill_recompute_kv_from_token_cache,
    parse_stream_chunk_json,
    process_stream_chunk,
    strip_nonstream_response_body_for_client,
    strip_stream_chunk_bytes_for_client,
    update_completion_tokens,
    update_token_id_cache,
)
