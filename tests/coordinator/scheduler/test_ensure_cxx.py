# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Guards kv-conductor C++ discovery: g++ outside a full toolchain must still be found."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENSURE_CXX = _REPO_ROOT / "scripts" / "ensure_cxx.sh"
_SUBPROCESS_TIMEOUT_SEC = 10


def _isolated_env(home: Path, path: str) -> dict[str, str]:
    """PATH without the developer compiler; HOME is unused except for isolation."""
    return {
        "HOME": str(home),
        "PATH": path,
        "TERM": "dumb",
        "LC_ALL": "C",
    }


def _write_fake_gxx(bin_dir: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    gxx = bin_dir / "g++"
    gxx.write_text("#!/bin/sh\necho fake-g++ 1.0\n", encoding="utf-8")
    gxx.chmod(gxx.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return gxx


def test_ensure_cxx_script_is_present():
    """build.sh sources this file before cargo-building kv-conductor."""
    assert _ENSURE_CXX.is_file()


def test_motor_ensure_cxx_exports_gxx_when_c_plusplus_missing(tmp_path: Path):
    """cc-rs looks up 'c++'; CI may only have g++. Export CXX so zmq-sys can compile."""
    gxx = _write_fake_gxx(tmp_path / "bin")
    env = _isolated_env(tmp_path, str(gxx.parent))
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", f"source '{_ENSURE_CXX}' && motor_ensure_cxx && printf '%s\\n' \"$CXX\""],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.returncode == 0, result.stderr
    assert str(gxx) in result.stdout


def test_skip_cxx_install_does_not_attempt_package_install(tmp_path: Path):
    """Locked CI images must be able to refuse apt/dnf without touching the system."""
    env = _isolated_env(tmp_path, "/empty-path-no-compiler")
    env["SKIP_CXX_INSTALL"] = "1"
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", f"source '{_ENSURE_CXX}' && motor_ensure_cxx"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.returncode != 0
    assert "SKIP_CXX_INSTALL=1" in result.stderr
