# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Required native members inside a packaged motor wheel.

Coordinator has no Python ledger fallback. A deployable wheel must contain the
workload-shm cdylib; source-dev can still load ``target/release`` without packaging.
"""

import zipfile

# Must match native.py _LIB_BASENAME and setup.py package_data.
WORKLOAD_SHM_WHEEL_MEMBER = "motor/coordinator/workload_shm_rs/lib/libmindie_workload_shm.so"

_REQUIRED_NATIVE_MEMBERS = (WORKLOAD_SHM_WHEEL_MEMBER,)


def list_missing_required_native_libs(wheel_path: str) -> list[str]:
    """Return required native archive members that ``wheel_path`` does not contain."""
    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())
    return [member for member in _REQUIRED_NATIVE_MEMBERS if member not in names]


def assert_motor_wheel_has_workload_shm(wheel_path: str) -> None:
    """Raise ValueError when the wheel is missing the workload-shm cdylib."""
    missing = list_missing_required_native_libs(wheel_path)
    if missing:
        raise ValueError(
            "motor wheel is missing required native library: "
            + ", ".join(missing)
            + ". Build it via bash build.sh (cargo or WORKLOAD_SHM_PREBUILT)."
        )
