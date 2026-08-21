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

Unlike ``test_workload_shm_writer.py`` / ``test_workload_shm_reader.py`` (which assert on private
buffers / patched ``unpack_header``), this drives a real POSIX ``shared_memory`` segment end to end:
the Writer packs it, the Reader reads it back through ``read_and_patch_cache``. It locks the on-wire
contract (magic, schema 3, 24B entry stride at offset 64, heartbeat at offset 32, and odd-sequence
seqlock retry) so a future Rust ``.so`` writer/reader can be validated against the exact same test.
"""

import struct
from multiprocessing import shared_memory

import pytest

from motor.common.resources.endpoint import Endpoint, EndpointStatus, Workload
from motor.common.resources.http_msg_spec import EventType
from motor.common.resources.instance import Instance, InsStatus, PDRole, ParallelConfig
from motor.config.coordinator import CoordinatorConfig
from motor.coordinator.domain.instance_manager import InstanceManager
from motor.coordinator.scheduler.runtime.workload_shm.layout import (
    HEADER_SIZE,
    HEARTBEAT_OFFSET,
    MAGIC,
    SCHEMA_VERSION,
    WorkloadShmHeader,
    pack_header,
    total_size,
    unpack_header,
)
from motor.coordinator.scheduler.runtime.workload_shm.reader import WorkloadSharedMemoryReader
from motor.coordinator.scheduler.runtime.workload_shm.writer import WorkloadSharedMemoryWriter

_MAX_ENTRIES = 16


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


def _new_segment() -> shared_memory.SharedMemory:
    return shared_memory.SharedMemory(create=True, size=total_size(_MAX_ENTRIES))


@pytest.mark.asyncio
async def test_snapshot_roundtrips_header_and_entries():
    """Writer snapshot -> Reader read_and_patch_cache: header contract + all 24B entries patched."""
    im = await _populated_manager()
    shm = _new_segment()
    writer = WorkloadSharedMemoryWriter(shm, im, max_entries=_MAX_ENTRIES)
    reader = WorkloadSharedMemoryReader(shm.name)
    try:
        writer.write_snapshot()

        header = unpack_header(memoryview(shm.buf))
        assert header.magic == MAGIC
        assert header.schema_version == SCHEMA_VERSION == 3
        assert header.sequence % 2 == 0  # stable snapshot
        assert header.entry_count == 4
        assert header.instance_version == 1

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
        shm.close()
        shm.unlink()


@pytest.mark.asyncio
async def test_heartbeat_lives_at_offset_32():
    """write_heartbeat bumps the u64 at byte offset 32 and the Reader observes the change."""
    im = await _populated_manager()
    shm = _new_segment()
    writer = WorkloadSharedMemoryWriter(shm, im, max_entries=_MAX_ENTRIES)
    reader = WorkloadSharedMemoryReader(shm.name)
    try:
        writer.write_snapshot()
        writer.write_heartbeat()

        raw = struct.unpack("<Q", bytes(memoryview(shm.buf)[HEARTBEAT_OFFSET : HEARTBEAT_OFFSET + 8]))[0]
        assert raw == 1
        assert unpack_header(memoryview(shm.buf)).heartbeat_sequence == 1

        reader.attach()
        _, stale = reader.read_and_patch_cache(_FakeCache(), role=None)
        assert stale is False
    finally:
        reader.detach()
        writer.release()
        shm.close()
        shm.unlink()


@pytest.mark.asyncio
async def test_odd_sequence_is_rejected_by_reader():
    """A writer-in-progress (odd seqlock) snapshot must not be accepted or patched."""
    im = await _populated_manager()
    shm = _new_segment()
    writer = WorkloadSharedMemoryWriter(shm, im, max_entries=_MAX_ENTRIES)
    reader = WorkloadSharedMemoryReader(shm.name)
    try:
        writer.write_snapshot()
        reader.attach()

        # Force the on-wire sequence odd (writer mid-update) without a matching even close.
        stable = unpack_header(memoryview(shm.buf))
        memoryview(shm.buf)[:HEADER_SIZE] = pack_header(
            WorkloadShmHeader(
                magic=stable.magic,
                schema_version=stable.schema_version,
                sequence=stable.sequence + 1,  # odd
                entry_count=stable.entry_count,
                max_entries=stable.max_entries,
                instance_version=stable.instance_version,
                heartbeat_sequence=stable.heartbeat_sequence,
                prefill_sequence=stable.prefill_sequence,
                decode_sequence=stable.decode_sequence,
                hybrid_sequence=stable.hybrid_sequence,
            )
        )

        cache = _FakeCache()
        instance_version, stale = reader.read_and_patch_cache(cache, role=None)
        assert instance_version is None
        assert stale is False
        assert cache.patched == {}
    finally:
        reader.detach()
        writer.release()
        shm.close()
        shm.unlink()


@pytest.mark.asyncio
async def test_schema_mismatch_is_refused():
    """A mismatched schema_version is refused (wrong entry stride would feed garbage loads)."""
    im = await _populated_manager()
    shm = _new_segment()
    writer = WorkloadSharedMemoryWriter(shm, im, max_entries=_MAX_ENTRIES)
    reader = WorkloadSharedMemoryReader(shm.name)
    try:
        writer.write_snapshot()
        reader.attach()

        stable = unpack_header(memoryview(shm.buf))
        memoryview(shm.buf)[:HEADER_SIZE] = pack_header(
            WorkloadShmHeader(
                magic=stable.magic,
                schema_version=SCHEMA_VERSION + 1,  # future/unknown schema
                sequence=stable.sequence,
                entry_count=stable.entry_count,
                max_entries=stable.max_entries,
                instance_version=stable.instance_version,
                heartbeat_sequence=stable.heartbeat_sequence,
                prefill_sequence=stable.prefill_sequence,
                decode_sequence=stable.decode_sequence,
                hybrid_sequence=stable.hybrid_sequence,
            )
        )

        cache = _FakeCache()
        instance_version, stale = reader.read_and_patch_cache(cache, role=None)
        assert instance_version is None
        assert cache.patched == {}
    finally:
        reader.detach()
        writer.release()
        shm.close()
        shm.unlink()
