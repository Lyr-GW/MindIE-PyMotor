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

from unittest.mock import AsyncMock, patch

import pytest

from motor.common.resources.endpoint import Endpoint, EndpointStatus, Workload
from motor.common.resources.instance import Instance, PDRole
from motor.coordinator.models.request import RequestInfo
from motor.coordinator.scheduler.runtime.scheduler_client import (
    AsyncSchedulerClient,
    SchedulerClientConfig,
)
from motor.coordinator.scheduler.runtime.zmq_protocol import (
    SchedulerRequestType,
    SchedulerResponse,
    SchedulerResponseType,
)


def _make_instance_and_endpoint() -> tuple[Instance, Endpoint]:
    inst = Instance(
        job_name="job-1",
        model_name="model",
        id=1,
        role=PDRole.ROLE_P.value,
    )
    ep = Endpoint(
        id=11,
        ip="127.0.0.1",
        business_port="8001",
        mgmt_port="9001",
        status=EndpointStatus.NORMAL,
        workload=Workload(),
    )
    inst.add_endpoints("pod-1", {11: ep})
    return inst, ep


@pytest.mark.asyncio
async def test_scheduler_select_path_uses_new_request_type():
    config = SchedulerClientConfig(
        scheduler_address="ipc:///tmp/test_scheduler",
        selection_mode="scheduler_select",
    )
    client = AsyncSchedulerClient(config)
    client._workload_reader = None

    success_resp = SchedulerResponse(
        response_type=SchedulerResponseType.SUCCESS.value,
        request_id="rid-1",
        data={
            "instance": {"id": 1, "job_name": "job-1", "model_name": "model", "role": "prefill"},
            "endpoint": {
                "id": 11,
                "ip": "127.0.0.1",
                "business_port": "8001",
                "mgmt_port": "9001",
                "status": "normal",
            },
            "allocated_workload": {"active_tokens": 1.0, "active_kv_cache": 1.0},
        },
    )
    sent_types: list[str] = []

    async def _send_request(req):
        sent_types.append(req.request_type)
        return success_resp

    client._transport.send_request = _send_request
    req_info = RequestInfo(req_id="r1", req_data={"prompt": "x"}, req_len=10, api="/v1/chat/completions")
    result = await client.select_and_allocate(PDRole.ROLE_P, req_info)

    assert result is not None
    assert sent_types == [SchedulerRequestType.SELECT_AND_ALLOCATE.value]


@pytest.mark.asyncio
async def test_scheduler_select_fallback_to_worker_select_on_unknown_request_type():
    config = SchedulerClientConfig(
        scheduler_address="ipc:///tmp/test_scheduler",
        selection_mode="scheduler_select",
    )
    client = AsyncSchedulerClient(config)
    client._workload_reader = None
    inst, ep = _make_instance_and_endpoint()

    select_err = SchedulerResponse(
        response_type=SchedulerResponseType.ERROR.value,
        request_id="rid-select",
        error="Unknown request type: select_and_allocate",
    )
    alloc_success = SchedulerResponse(
        response_type=SchedulerResponseType.SUCCESS.value,
        request_id="rid-alloc",
        data={
            "instance": {"id": 1, "job_name": "job-1", "model_name": "model", "role": "prefill"},
            "endpoint": {
                "id": 11,
                "ip": "127.0.0.1",
                "business_port": "8001",
                "mgmt_port": "9001",
                "status": "normal",
            },
        },
    )
    sent_types: list[str] = []

    async def _send_request(req):
        sent_types.append(req.request_type)
        if req.request_type == SchedulerRequestType.SELECT_AND_ALLOCATE.value:
            return select_err
        return alloc_success

    client._transport.send_request = _send_request
    with patch.object(client, "select_instance_and_endpoint", AsyncMock(return_value=(inst, ep))):
        req_info = RequestInfo(req_id="r2", req_data={"prompt": "x"}, req_len=10, api="/v1/chat/completions")
        result = await client.select_and_allocate(PDRole.ROLE_P, req_info)

    assert result is not None
    assert sent_types == [
        SchedulerRequestType.SELECT_AND_ALLOCATE.value,
        SchedulerRequestType.ALLOCATE_ONLY.value,
    ]


def test_gray_mode_bucket_distribution_selection_mode():
    config = SchedulerClientConfig(
        scheduler_address="ipc:///tmp/test_scheduler",
        selection_mode="gray",
        scheduler_select_ratio=100,
        scheduler_select_salt="s",
    )
    client = AsyncSchedulerClient(config)
    assert client._resolve_selection_mode("abc") == "scheduler_select"

    config_zero = SchedulerClientConfig(
        scheduler_address="ipc:///tmp/test_scheduler",
        selection_mode="gray",
        scheduler_select_ratio=0,
    )
    client_zero = AsyncSchedulerClient(config_zero)
    assert client_zero._resolve_selection_mode("abc") == "worker_select"
