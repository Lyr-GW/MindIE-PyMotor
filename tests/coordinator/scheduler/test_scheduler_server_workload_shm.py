# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.

"""Tests for schema-4 workload SHM create orphan recovery (POSIX)."""

import os
import sys
import uuid

import pytest

from motor.coordinator.scheduler.runtime.workload_shm.layout import FLAG_VALID
from motor.coordinator.scheduler.runtime.workload_shm.native import (
    NativeWorkloadShmUnavailable,
    WorkloadShm,
    load_native_library,
)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shared_memory orphan semantics differ on Windows")
def test_create_v4_recovers_from_orphan_segment():
    """Stale mindie_workload_* from unclean exit is unlinked and recreated by create_v4."""
    try:
        lib = load_native_library()
    except NativeWorkloadShmUnavailable as e:
        pytest.skip(f"native workload-shm library not built: {e}")

    name = f"mw{os.getpid()}{uuid.uuid4().hex[:6]}"[:24]
    first = WorkloadShm.create_v4(name, 8, lib=lib)
    first.write_snapshot_v4([(1, 10, 0, 0, FLAG_VALID, 1.0)])
    first.close(unlink=False)

    second = WorkloadShm.create_v4(name, 8, lib=lib)
    try:
        second.write_snapshot_v4([(2, 20, 0, 0, FLAG_VALID, 2.0)])
        entry = second.load_entry(0)
        assert entry["instance_id"] == 2
        assert entry["active_tokens"] == 2.0
    finally:
        second.close(unlink=True)
