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

"""Demand workload scoring from role and request length (scheduler + router allocation)."""

from __future__ import annotations

from motor.common.resources.endpoint import Workload
from motor.common.resources.instance import PDRole
from motor.common.utils.logger import get_logger

logger = get_logger(__name__)


def calculate_demand_workload(role: PDRole, request_length: int) -> Workload:
    """
    Compute demand workload for this allocation from role and request length.
    Shared by BaseRouter.prepare_resource and WorkloadActionHandler ALLOCATION.

    Args:
        role: PDRole enum (prefill/decode/both)
        request_length: Request length

    Returns:
        Workload: Load for ALLOCATION (used by select_and_allocate / add_req_workload)
    """
    if role == PDRole.ROLE_P:
        score = _calculate_prefill_scores(request_length)
        return Workload(active_kv_cache=score, active_tokens=score)
    if role == PDRole.ROLE_D:
        score = _calculate_decode_scores(request_length)
        return Workload(active_tokens=score)
    if role == PDRole.ROLE_U:
        score = _calculate_both_scores(request_length)
        return Workload(active_kv_cache=score, active_tokens=score)
    logger.warning("Unknown role %s for workload calculation", role)
    return Workload()


def _calculate_prefill_scores(request_length: int) -> float:
    """Prefill role workload score."""
    length_score = request_length / 4.0
    return length_score * 0.0345 + 120.0745


def _calculate_decode_scores(request_length: int) -> float:
    """Decode role workload score."""
    return float(request_length)


def _calculate_both_scores(request_length: int) -> float:
    """Hybrid role workload score."""
    return (_calculate_prefill_scores(request_length) + _calculate_decode_scores(request_length)) * 0.5
