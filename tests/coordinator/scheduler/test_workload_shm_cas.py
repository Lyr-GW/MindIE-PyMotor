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
P2 schema-4 per-slot CAS contract (design §5.4 / §6 / R1 / A2–A4 / C3).

Drives the Rust schema-4 CAS engine through the ctypes ``native`` binding. The headline test spawns
multiple **separate processes** that each CAS-add with a re-read-on-Changed retry loop against one
shared POSIX segment; the final value must equal the exact sum of all deltas (no lost updates) --
the core R1 proof that the ledger supports multi-process atomic read/write. Skipped only if the
native library is not built.
"""

import multiprocessing
import os

import pytest

from motor.coordinator.scheduler.runtime.workload_shm.layout import ROLE_PREFILL
from motor.coordinator.scheduler.runtime.workload_shm.native import (
    STATUS_BLOCKED,
    STATUS_CHANGED,
    STATUS_OK,
    STATUS_SLOT_INVALID,
    NativeWorkloadShmUnavailable,
    WorkloadShm,
    load_native_library,
)


@pytest.fixture
def lib():
    try:
        return load_native_library()
    except NativeWorkloadShmUnavailable as e:
        pytest.skip(f"native workload-shm library not built: {e}")


def _unique(tag: str) -> str:
    return f"mindie_wl_cas_test_{tag}_{os.getpid()}"


def _single_entry_segment(lib, tag: str) -> WorkloadShm:
    shm = WorkloadShm.create_v4(_unique(tag), 8, lib=lib)
    # slot 0: instance 1, endpoint 10, generation 0, flags 0, tokens 0.0
    shm.write_snapshot_v4([(1, 10, ROLE_PREFILL, 0, 0, 0.0)])
    return shm


def test_cas_add_ok_then_changed(lib):
    """expected match -> OK and value increments; stale expected -> CHANGED with fresh value, no add."""
    shm = _single_entry_segment(lib, "ok")
    try:
        status, actual = shm.cas_add(1, 10, 0, expected=0.0, delta=3.0)
        assert status == STATUS_OK
        assert actual == 3.0
        status, actual = shm.cas_add(1, 10, 0, expected=0.0, delta=100.0)
        assert status == STATUS_CHANGED
        assert actual == 3.0  # unchanged, returns current
    finally:
        shm.close(unlink=True)


def test_cas_sub_floor0(lib):
    """Release path floors at 0 and never goes negative."""
    shm = _single_entry_segment(lib, "floor0")
    try:
        assert shm.cas_add(1, 10, 0, 0.0, 5.0)[0] == STATUS_OK
        status, actual = shm.cas_sub_floor0(1, 10, 0, 9.0)
        assert status == STATUS_OK
        assert actual == 0.0
    finally:
        shm.close(unlink=True)


def test_blocked_flag_is_final_gate(lib):
    """set_blocked makes cas_add refuse (BLOCKED); clearing it re-enables allocation (C3)."""
    shm = _single_entry_segment(lib, "blocked")
    try:
        assert shm.set_blocked(1, True) == 1
        status, actual = shm.cas_add(1, 10, 0, 0.0, 1.0)
        assert status == STATUS_BLOCKED
        assert actual == 0.0
        shm.set_blocked(1, False)
        assert shm.cas_add(1, 10, 0, 0.0, 1.0)[0] == STATUS_OK
    finally:
        shm.close(unlink=True)


def test_generation_mismatch_is_slot_invalid(lib):
    """A stale generation (slot reused) yields SLOT_INVALID, guarding against ABA."""
    shm = _single_entry_segment(lib, "gen")
    try:
        status, _ = shm.cas_add(1, 10, 1, 0.0, 1.0)  # slot gen is 0, caller remembers 1
        assert status == STATUS_SLOT_INVALID
    finally:
        shm.close(unlink=True)


def test_cas_add_until_ok_retries_on_changed(lib):
    """The CAS-expected retry helper converges even when the starting expected is stale."""
    shm = _single_entry_segment(lib, "retry")
    try:
        shm.cas_add(1, 10, 0, 0.0, 7.0)  # move value to 7 so initial expected=0.0 is stale
        final = shm.cas_add_until_ok(1, 10, 0, 5.0)
        assert final == 12.0
    finally:
        shm.close(unlink=True)


def _cas_worker(name: str, instance_id: int, endpoint_id: int, generation: int, count: int) -> None:
    """Child process: attach the shared segment and CAS-add `count` times with retry-on-Changed."""
    from motor.coordinator.scheduler.runtime.workload_shm.native import (
        WorkloadShm as _WorkloadShm,
        load_native_library as _load,
    )

    shm = _WorkloadShm.attach(name, lib=_load())
    try:
        for _ in range(count):
            shm.cas_add_until_ok(instance_id, endpoint_id, generation, 1.0)
    finally:
        shm.close(unlink=False)


def test_multiprocess_cas_conserves_total(lib):
    """R1 core (A2): N spawned processes each add 1.0 M times; final == N*M exactly (no lost updates)."""
    ctx = multiprocessing.get_context("spawn")
    name = _unique("conserve")
    shm = WorkloadShm.create_v4(name, 8, lib=lib)
    n_procs = 4
    per_proc = 500
    try:
        shm.write_snapshot_v4([(1, 10, ROLE_PREFILL, 0, 0, 0.0)])
        procs = [ctx.Process(target=_cas_worker, args=(name, 1, 10, 0, per_proc)) for _ in range(n_procs)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)
            assert p.exitcode == 0, f"worker exited with {p.exitcode}"
        total = shm.load_entry(0)["active_tokens"]
        assert total == float(n_procs * per_proc)
    finally:
        shm.close(unlink=True)
