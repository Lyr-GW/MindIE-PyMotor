# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Guards the motor-wheel contract: deployable wheels must ship native members."""

import zipfile
from pathlib import Path

import pytest

from motor.coordinator.scheduler.runtime.workload_shm import native
from motor.coordinator.workload_shm_rs.wheel_gate import (
    KV_CONDUCTOR_WHEEL_MEMBER,
    WORKLOAD_SHM_WHEEL_MEMBER,
    arch_tagged_motor_wheel_name,
    assert_motor_wheel_has_kv_conductor,
    assert_motor_wheel_has_workload_shm,
    list_missing_required_native_libs,
    resolve_motor_wheel_platform_tag,
    retag_motor_wheel_filename,
)


def test_wheel_member_matches_runtime_loader_basename():
    """Packaged path must be the same basename native.py searches under lib/."""
    assert WORKLOAD_SHM_WHEEL_MEMBER.endswith("/lib/" + native._LIB_BASENAME)


def test_list_missing_required_native_libs_reports_absent_so(tmp_path: Path):
    """A wheel without the cdylib must be rejected so nightly cannot ship an empty ledger."""
    wheel = tmp_path / "motor-empty-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("motor/__init__.py", "")

    assert list_missing_required_native_libs(str(wheel)) == [WORKLOAD_SHM_WHEEL_MEMBER]
    with pytest.raises(ValueError, match="refusing to emit motor wheel"):
        assert_motor_wheel_has_workload_shm(str(wheel))


def test_list_missing_required_native_libs_accepts_packaged_so(tmp_path: Path):
    """Presence of the packaged member is enough; the gate does not inspect ELF contents."""
    wheel = tmp_path / "motor-ok-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(WORKLOAD_SHM_WHEEL_MEMBER, b"\x7fELF")

    assert list_missing_required_native_libs(str(wheel)) == []
    assert_motor_wheel_has_workload_shm(str(wheel))


def test_assert_motor_wheel_has_kv_conductor_rejects_missing_bin(tmp_path: Path):
    """When cargo produced kv-conductor, build.sh must not keep a wheel without the binary."""
    wheel = tmp_path / "motor-no-kv-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(WORKLOAD_SHM_WHEEL_MEMBER, b"\x7fELF")

    with pytest.raises(ValueError, match="refusing to emit motor wheel"):
        assert_motor_wheel_has_kv_conductor(str(wheel))


def test_assert_motor_wheel_has_kv_conductor_accepts_packaged_bin(tmp_path: Path):
    """Presence of the packaged member is enough; the gate does not inspect the ELF."""
    wheel = tmp_path / "motor-with-kv-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(WORKLOAD_SHM_WHEEL_MEMBER, b"\x7fELF")
        archive.writestr(KV_CONDUCTOR_WHEEL_MEMBER, b"\x7fELF")

    assert_motor_wheel_has_kv_conductor(str(wheel))


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        ("x86_64", "x86_64"),
        ("amd64", "x86_64"),
        ("aarch64", "aarch64"),
        ("arm64", "aarch64"),
    ],
)
def test_resolve_motor_wheel_platform_tag_normalizes_host(machine: str, expected: str):
    """x86 and ARM builds must get distinct tags so artifacts cannot collide."""
    assert resolve_motor_wheel_platform_tag(machine=machine) == expected


def test_arch_tagged_motor_wheel_name_keeps_pep517_prefix():
    """Filename stays motor-<ver>-py3-none-<arch>.whl; only the any tag is replaced."""
    assert arch_tagged_motor_wheel_name("3.1.0", platform_tag="x86_64") == "motor-3.1.0-py3-none-x86_64.whl"
    assert arch_tagged_motor_wheel_name("3.1.0", platform_tag="aarch64") == "motor-3.1.0-py3-none-aarch64.whl"


def test_retag_motor_wheel_filename_replaces_any_tag(tmp_path: Path):
    """build.sh must rename the pep517 any-wheel so x86 and ARM artifacts differ."""
    src = tmp_path / "motor-3.1.0-py3-none-any.whl"
    src.write_bytes(b"wheel")

    dest = Path(retag_motor_wheel_filename(str(src), "3.1.0", platform_tag="x86_64"))

    assert dest == tmp_path / "motor-3.1.0-py3-none-x86_64.whl"
    assert dest.is_file()
    assert not src.exists()
    assert dest.read_bytes() == b"wheel"


def test_retag_motor_wheel_filename_is_noop_when_already_tagged(tmp_path: Path):
    """Re-running the gate on an already tagged wheel must not invent a second file."""
    src = tmp_path / "motor-3.1.0-py3-none-aarch64.whl"
    src.write_bytes(b"wheel")

    dest = Path(retag_motor_wheel_filename(str(src), "3.1.0", platform_tag="aarch64"))

    assert dest == src
    assert src.is_file()
