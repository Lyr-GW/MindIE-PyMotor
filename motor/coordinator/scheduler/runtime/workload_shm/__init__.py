# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""
Workload shared memory: layout, reader (Worker), owner (Mgmt).
"""

__all__ = [
    "WorkloadSharedMemoryReader",
    "WorkloadSharedMemoryOwner",
    "total_size",
]

from motor.coordinator.scheduler.runtime.workload_shm.layout import total_size
from motor.coordinator.scheduler.runtime.workload_shm.reader import WorkloadSharedMemoryReader
from motor.coordinator.scheduler.runtime.workload_shm.writer import WorkloadSharedMemoryOwner
