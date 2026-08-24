# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""
select_and_allocate without ZMQ: local scoring + schema-4 CAS (design §3.3 / §6 / R4).

Does not mock send_request. A stale expected must reload and re-run the same Python scorer.
"""

import os

import pytest

from motor.common.resources.endpoint import Endpoint, EndpointStatus, Workload
from motor.common.resources.http_msg_spec import EventType
from motor.common.resources.instance import Instance, InsStatus, PDRole, ParallelConfig
from motor.config.coordinator import CoordinatorConfig
from motor.coordinator.domain.instance_manager import InstanceManager
from motor.coordinator.models.request import RequestInfo
from motor.coordinator.scheduler.runtime.scheduler_client import (
    AsyncSchedulerClient,
    SchedulerClientConfig,
    _SchedulerInstanceCache,
)
from motor.coordinator.scheduler.runtime.workload_shm.native import (
    NativeWorkloadShmUnavailable,
    load_native_library,
)
from motor.coordinator.scheduler.runtime.workload_shm.reader import WorkloadSharedMemoryReader
from motor.coordinator.scheduler.runtime.workload_shm.writer import WorkloadSharedMemoryWriter


def _unique(tag: str) -> str:
    return f"mw{os.getpid()}{tag}"[:24]


def _make_instance(instance_id: int, endpoint_id: int, tokens: float) -> Instance:
    inst = Instance(
        job_name=f"p-{instance_id}",
        model_name="test_model",
        id=instance_id,
        role=PDRole.ROLE_P,
        status=InsStatus.ACTIVE,
        parallel_config=ParallelConfig(dp_size=1),
    )
    inst.add_endpoints(
        f"pod-{instance_id}",
        {
            0: Endpoint(
                id=endpoint_id,
                ip=f"10.0.0.{instance_id}",
                business_port="8080",
                mgmt_port="9080",
                status=EndpointStatus.NORMAL,
                workload=Workload(active_tokens=tokens),
            )
        },
    )
    return inst


@pytest.fixture
def native_lib():
    try:
        return load_native_library()
    except NativeWorkloadShmUnavailable as e:
        pytest.skip(f"native workload-shm library not built: {e}")
        return None


async def _client_with_shm(im: InstanceManager, name: str) -> tuple[AsyncSchedulerClient, WorkloadSharedMemoryWriter]:
    writer = WorkloadSharedMemoryWriter(im, max_entries=8, shm_name=name)
    writer.write_snapshot()
    client = AsyncSchedulerClient(
        SchedulerClientConfig(scheduler_type="load_balance", endpoint_instance_score_weight=0.0)
    )
    cache = _SchedulerInstanceCache()
    instances = list(im.get_available_instances(PDRole.ROLE_P).values())
    await cache.replace_all(PDRole.ROLE_P, instances)
    client._cache = cache
    reader = WorkloadSharedMemoryReader(name)
    reader.attach()
    client._workload_reader = reader
    return client, writer


@pytest.mark.asyncio
async def test_select_and_allocate_cas_commits_lowest_load(native_lib):
    """Read SHM, score with LoadBalance, CAS-add, return (Instance, Endpoint, Workload)."""
    del native_lib
    config = CoordinatorConfig()
    im = InstanceManager(config)
    await im.refresh_instances(
        EventType.ADD,
        [_make_instance(1, 10, 1.0), _make_instance(2, 20, 50.0)],
    )
    name = _unique("al")
    client, writer = await _client_with_shm(im, name)
    try:
        req = RequestInfo(req_id="req-cas", req_data={}, req_len=8, api="v1/completions", token_ids=[1, 2, 3, 4])
        result = await client.select_and_allocate(PDRole.ROLE_P, req)
        assert result is not None
        instance, endpoint, committed = result
        assert instance.id == 1
        assert endpoint.id == 10
        assert committed.active_tokens == pytest.approx(4.0)
        meta = client._workload_reader.entry_meta(1, 10)
        assert meta is not None
        assert meta["active_tokens"] == pytest.approx(5.0)
    finally:
        client._workload_reader.detach()
        writer.release()


@pytest.mark.asyncio
async def test_select_and_allocate_changed_reloads_and_rescores(native_lib):
    """Stale expected (CHANGED) must re-score on the fresh vector, not blindly add on the old winner."""
    del native_lib
    config = CoordinatorConfig()
    im = InstanceManager(config)
    await im.refresh_instances(
        EventType.ADD,
        [_make_instance(1, 10, 1.0), _make_instance(2, 20, 8.0)],
    )
    name = _unique("ch")
    client, writer = await _client_with_shm(im, name)
    native = client._workload_reader.native
    orig = native.cas_add
    calls = {"n": 0}

    def wrapped(iid, eid, gen, expected, delta):
        calls["n"] += 1
        if calls["n"] == 1:
            orig(iid, eid, gen, expected, 80.0)
        return orig(iid, eid, gen, expected, delta)

    native.cas_add = wrapped
    try:
        req = RequestInfo(req_id="req-changed", req_data={}, req_len=4, api="v1/completions", token_ids=[1, 2, 3, 4])
        result = await client.select_and_allocate(PDRole.ROLE_P, req)
        assert result is not None
        instance, endpoint, _committed = result
        assert instance.id == 2
        assert endpoint.id == 20
        assert calls["n"] >= 2
    finally:
        native.cas_add = orig
        client._workload_reader.detach()
        writer.release()


@pytest.mark.asyncio
async def test_select_and_allocate_without_shm_returns_none(native_lib):
    """Missing native attach fails closed (A7): no silent Python ledger."""
    del native_lib
    client = AsyncSchedulerClient(SchedulerClientConfig(scheduler_type="load_balance"))
    req = RequestInfo(req_id="req-none", req_data={}, req_len=4, api="v1/completions", token_ids=[1])
    assert await client.select_and_allocate(PDRole.ROLE_P, req) is None
