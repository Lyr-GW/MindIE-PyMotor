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
P1 native shared-memory writer contract (design §12.2 / A1 / R-6).

Drives the Rust ``libmindie_workload_shm`` writer (via the ctypes ``native`` binding) and reads the
segment back with the production Python ``WorkloadSharedMemoryReader`` -- proving the ``.so`` writes
schema-3 bytes the existing reader accepts (the "insertion band"). The suite is skipped only if the
library is not built; the missing-library error path is asserted explicitly.
"""

import os

import pytest

from motor.common.resources.instance import PDRole
from motor.coordinator.scheduler.runtime.workload_shm import native
from motor.coordinator.scheduler.runtime.workload_shm.native import (
    NativeWorkloadShmUnavailable,
    WorkloadShm,
    load_native_library,
    pdrole_to_shm_role,
)
from motor.coordinator.scheduler.runtime.workload_shm.reader import WorkloadSharedMemoryReader


class _FakeCache:
    def __init__(self) -> None:
        self.patched: dict[tuple[int, int], tuple[PDRole, float]] = {}

    def patch_workload_from_shm(self, instance_id, endpoint_id, role, active_tokens) -> None:
        self.patched[(instance_id, endpoint_id)] = (role, active_tokens)


@pytest.fixture
def lib():
    try:
        return load_native_library()
    except NativeWorkloadShmUnavailable as e:
        pytest.skip(f"native workload-shm library not built: {e}")


def _unique(tag: str) -> str:
    return f"mindie_wl_native_test_{tag}_{os.getpid()}"


def _read_with_python(name: str, role: PDRole | None = None) -> tuple[tuple[int | None, bool], _FakeCache]:
    """Attach the production Python reader, read once, and detach without unlinking (Rust owns it)."""
    reader = WorkloadSharedMemoryReader(name)
    reader.attach()
    try:
        # The native side owns unlink; drop the resource_tracker's claim to avoid a spurious unlink.
        from multiprocessing import resource_tracker

        resource_tracker.unregister(reader._shm._name, "shared_memory")  # noqa: SLF001
    except Exception:
        pass
    cache = _FakeCache()
    try:
        result = reader.read_and_patch_cache(cache, role=role)
    finally:
        reader.detach()
    return result, cache


def test_native_reports_schema_and_abi(lib):
    """The library advertises schema 3 (matching the Python layout) and a stable ABI version."""
    assert lib.mindie_wl_schema_version() == 3
    assert lib.mindie_wl_abi_version() >= 1


def test_native_writer_roundtrips_to_python_reader(lib):
    """Rust snapshot -> production Python reader: header + all entries patched byte-compatibly."""
    name = _unique("rt")
    shm = WorkloadShm.create(name, 16, lib=lib)
    try:
        shm.write_snapshot(
            [
                (1, 10, pdrole_to_shm_role(PDRole.ROLE_P), 7.0),
                (1, 11, pdrole_to_shm_role(PDRole.ROLE_P), 8.0),
                (2, 20, pdrole_to_shm_role(PDRole.ROLE_P), 9.0),
            ],
            bump_instance_version=True,
        )
        shm.heartbeat()

        header = shm.read_header()
        assert header["schema_version"] == 3
        assert header["sequence"] % 2 == 0
        assert header["entry_count"] == 3
        assert header["instance_version"] == 1
        assert header["heartbeat"] == 1

        (instance_version, stale), cache = _read_with_python(name)
        assert instance_version == 1
        assert stale is False
        assert cache.patched == {
            (1, 10): (PDRole.ROLE_P, 7.0),
            (1, 11): (PDRole.ROLE_P, 8.0),
            (2, 20): (PDRole.ROLE_P, 9.0),
        }
    finally:
        shm.close(unlink=True)


def test_native_odd_sequence_is_rejected_then_accepted(lib):
    """A begun-but-not-committed snapshot (odd seqlock) is refused; commit makes it readable."""
    name = _unique("odd")
    shm = WorkloadShm.create(name, 8, lib=lib)
    try:
        shm.snapshot_begin()
        shm.write_entry(0, 1, 10, pdrole_to_shm_role(PDRole.ROLE_P), 5.0)
        assert shm.read_header()["sequence"] % 2 == 1  # writer in progress

        (instance_version, stale), cache = _read_with_python(name)
        assert instance_version is None
        assert cache.patched == {}

        shm.snapshot_commit(1, bump_instance_version=True)
        assert shm.read_header()["sequence"] % 2 == 0

        (instance_version2, _), cache2 = _read_with_python(name)
        assert instance_version2 == 1
        assert cache2.patched == {(1, 10): (PDRole.ROLE_P, 5.0)}
    finally:
        shm.close(unlink=True)


def test_native_create_recovers_from_orphan(lib):
    """Creating over an existing (orphaned) segment unlinks and recreates it, like the Python writer."""
    name = _unique("orphan")
    first = WorkloadShm.create(name, 4, lib=lib)
    first.write_snapshot([(1, 10, pdrole_to_shm_role(PDRole.ROLE_P), 1.0)])
    # Simulate a crashed writer: close WITHOUT unlinking, leaving the segment behind.
    first.close(unlink=False)

    second = WorkloadShm.create(name, 4, lib=lib)
    try:
        second.write_snapshot([(2, 20, pdrole_to_shm_role(PDRole.ROLE_P), 2.0)])
        (_, _), cache = _read_with_python(name)
        assert cache.patched == {(2, 20): (PDRole.ROLE_P, 2.0)}
    finally:
        second.close(unlink=True)


def test_missing_library_raises_clear_error():
    """A missing .so must raise NativeWorkloadShmUnavailable (no silent fallback to a wrong ledger)."""
    with pytest.raises(NativeWorkloadShmUnavailable) as exc:
        load_native_library(path="/nonexistent/does-not-exist/libmindie_workload_shm.so")
    assert native._LIB_BASENAME in str(exc.value)
