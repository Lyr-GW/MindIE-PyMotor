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
Workload SHM Writer -> Reader roundtrip contract (design §5 / §11.3).

Drives a real POSIX segment through the schema-4 Rust .so: Writer snapshots membership,
Reader atomic-loads tokens. Locks magic/schema 4/even seqlock/heartbeat and odd-seqlock retry.
"""

import os

import pytest

from motor.common.resources.endpoint import Endpoint, EndpointStatus, Workload
from motor.common.resources.http_msg_spec import EventType
from motor.common.resources.instance import Instance, InsStatus, PDRole, ParallelConfig
from motor.config.coordinator import CoordinatorConfig
from motor.coordinator.domain.instance_manager import InstanceManager
from motor.coordinator.scheduler.runtime.workload_shm.layout import SCHEMA_VERSION
from motor.coordinator.scheduler.runtime.workload_shm.native import (
    NativeWorkloadShmUnavailable,
    WorkloadShm,
    load_native_library,
)
from motor.coordinator.scheduler.runtime.workload_shm.reader import WorkloadSharedMemoryReader
from motor.coordinator.scheduler.runtime.workload_shm.writer import WorkloadSharedMemoryWriter


class _FakeCache:
    """Records patch_workload_from_shm calls: {(instance_id, endpoint_id): (role, active_tokens)}."""

    def __init__(self) -> None:
        self.patched: dict[tuple[int, int], tuple[PDRole, float]] = {}

    def patch_workload_from_shm(self, instance_id, endpoint_id, role, active_tokens) -> None:
        self.patched[(instance_id, endpoint_id)] = (role, active_tokens)


def _make_instance(instance_id: int, endpoint_ids: tuple[int, int], role: PDRole = PDRole.ROLE_P) -> Instance:
    inst = Instance(
        job_name=f"{role.value}-{instance_id}",
        model_name="test_model",
        id=instance_id,
        role=role,
        status=InsStatus.ACTIVE,
        parallel_config=ParallelConfig(dp_size=2),
    )
    inst.add_endpoints(
        f"pod-{instance_id}",
        {
            idx: Endpoint(
                id=endpoint_id,
                ip=f"10.0.0.{instance_id}",
                business_port=f"80{idx}",
                mgmt_port=f"90{idx}",
                status=EndpointStatus.NORMAL,
                workload=Workload(),
            )
            for idx, endpoint_id in enumerate(endpoint_ids)
        },
    )
    return inst


async def _populated_manager() -> InstanceManager:
    config = CoordinatorConfig()
    im = InstanceManager(config)
    await im.refresh_instances(EventType.ADD, [_make_instance(1, (10, 11)), _make_instance(2, (20, 21))])
    await im.update_instance_workload(1, 10, Workload(active_tokens=7))
    await im.update_instance_workload(1, 11, Workload(active_tokens=8))
    await im.update_instance_workload(2, 20, Workload(active_tokens=9))
    await im.update_instance_workload(2, 21, Workload(active_tokens=10))
    return im


def _unique(tag: str) -> str:
    return f"mw{os.getpid()}{tag}"[:24]


@pytest.fixture
def native_lib():
    try:
        return load_native_library()
    except NativeWorkloadShmUnavailable as e:
        pytest.skip(f"native workload-shm library not built: {e}")
        return None


@pytest.mark.asyncio
async def test_snapshot_roundtrips_header_and_entries(native_lib):
    """Writer snapshot -> Reader read_and_patch_cache: schema 4 + all entries patched."""
    del native_lib
    im = await _populated_manager()
    name = _unique("rt")
    writer = WorkloadSharedMemoryWriter(im, max_entries=16, shm_name=name)
    reader = WorkloadSharedMemoryReader(name)
    try:
        writer.write_snapshot()
        header = writer.native.read_header()
        assert header["schema_version"] == SCHEMA_VERSION == 4
        assert header["sequence"] % 2 == 0
        assert header["entry_count"] == 4
        assert header["instance_version"] == 1

        reader.attach()
        cache = _FakeCache()
        instance_version, stale = reader.read_and_patch_cache(cache, role=None)

        assert instance_version == 1
        assert stale is False
        assert cache.patched == {
            (1, 10): (PDRole.ROLE_P, 7.0),
            (1, 11): (PDRole.ROLE_P, 8.0),
            (2, 20): (PDRole.ROLE_P, 9.0),
            (2, 21): (PDRole.ROLE_P, 10.0),
        }
    finally:
        reader.detach()
        writer.release()


@pytest.mark.asyncio
async def test_heartbeat_is_observed_by_reader(native_lib):
    """write_heartbeat bumps the header counter; Reader does not treat a fresh writer as stale."""
    del native_lib
    im = await _populated_manager()
    name = _unique("hb")
    writer = WorkloadSharedMemoryWriter(im, max_entries=16, shm_name=name)
    reader = WorkloadSharedMemoryReader(name)
    try:
        writer.write_snapshot()
        writer.write_heartbeat()
        assert writer.native.read_header()["heartbeat"] == 1
        reader.attach()
        _, stale = reader.read_and_patch_cache(_FakeCache(), role=None)
        assert stale is False
    finally:
        reader.detach()
        writer.release()


@pytest.mark.asyncio
async def test_odd_sequence_is_rejected_by_reader(native_lib):
    """A writer-in-progress (odd seqlock) snapshot must not be accepted or patched."""
    del native_lib
    im = await _populated_manager()
    name = _unique("od")
    writer = WorkloadSharedMemoryWriter(im, max_entries=16, shm_name=name)
    reader = WorkloadSharedMemoryReader(name)
    try:
        writer.write_snapshot()
        reader.attach()
        writer.native.snapshot_begin()
        cache = _FakeCache()
        instance_version, stale = reader.read_and_patch_cache(cache, role=None)
        assert instance_version is None
        assert stale is False
        assert cache.patched == {}
        writer.native.snapshot_commit(4, bump_instance_version=False)
    finally:
        reader.detach()
        writer.release()


@pytest.mark.asyncio
async def test_schema_mismatch_is_refused(native_lib):
    """A schema-3 segment is refused by the schema-4 Reader."""
    name = _unique("sm")
    shm = WorkloadShm.create(name, 8, lib=native_lib)
    reader = WorkloadSharedMemoryReader(name)
    try:
        shm.write_snapshot([(1, 10, 0, 7.0)])
        reader.attach()
        cache = _FakeCache()
        instance_version, _stale = reader.read_and_patch_cache(cache, role=None)
        assert instance_version is None
        assert cache.patched == {}
    finally:
        reader.detach()
        shm.close(unlink=True)
