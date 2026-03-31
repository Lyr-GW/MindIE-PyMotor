# -*- coding: utf-8 -*-
"""Tests for scheduler workload SharedMemory creation (POSIX orphan recovery)."""

import os
import sys
import uuid
from multiprocessing import shared_memory

import pytest

from motor.coordinator.scheduler.runtime.scheduler_server import _create_workload_shared_memory


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shared_memory orphan semantics differ on Windows")
def test_create_workload_shm_recovers_from_orphan_segment():
    """Stale mindie_workload_* from unclean exit causes FileExistsError; helper unlinks and recreates."""
    name = f"mindie_workload_test_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    size = 4096
    orphan = shared_memory.SharedMemory(name=name, create=True, size=size)
    orphan.close()
    # Segment may still exist until unlink; create=True must fail
    with pytest.raises(FileExistsError):
        shared_memory.SharedMemory(name=name, create=True, size=size)

    recovered = _create_workload_shared_memory(shared_memory, name, size)
    try:
        assert recovered.size >= size
    finally:
        recovered.close()
        try:
            recovered.unlink()
        except FileNotFoundError:
            pass
