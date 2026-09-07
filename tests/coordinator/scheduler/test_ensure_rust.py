# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Guards CI cargo discovery: rustup outside PATH must still be found; skip must not fetch."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENSURE_RUST = _REPO_ROOT / "scripts" / "ensure_rust.sh"
_SUBPROCESS_TIMEOUT_SEC = 10


def _isolated_env(home: Path) -> dict[str, str]:
    """PATH without the developer rustup; HOME is the fake cargo prefix."""
    return {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "TERM": "dumb",
        "LC_ALL": "C",
    }


def _run_ensure(home: Path, snippet: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", "-c", f"source '{_ENSURE_RUST}' && {snippet}"],
        check=False,
        capture_output=True,
        text=True,
        env=_isolated_env(home),
        timeout=_SUBPROCESS_TIMEOUT_SEC,
    )


def _write_fake_cargo(home: Path) -> Path:
    bin_dir = home / ".cargo" / "bin"
    bin_dir.mkdir(parents=True)
    cargo = bin_dir / "cargo"
    cargo.write_text("#!/bin/sh\necho fake-cargo\n", encoding="utf-8")
    cargo.chmod(cargo.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return cargo


def test_ensure_rust_script_is_present():
    """build.sh sources this file; a missing path would skip native compile on CI."""
    assert _ENSURE_RUST.is_file()


def test_motor_source_cargo_env_finds_home_cargo_when_not_on_path(tmp_path: Path):
    """Jenkins-style: rustup installed, job PATH omitted ~/.cargo/bin."""
    cargo = _write_fake_cargo(tmp_path)
    result = _run_ensure(tmp_path, "motor_source_cargo_env && command -v cargo")
    assert result.returncode == 0, result.stderr
    assert str(cargo) in result.stdout


def test_motor_source_cargo_env_fails_when_toolchain_absent(tmp_path: Path):
    """No silent success: missing cargo must be a failed lookup, not a skipped compile."""
    result = _run_ensure(tmp_path, "motor_source_cargo_env")
    assert result.returncode != 0


def test_skip_rust_install_does_not_attempt_network_install(tmp_path: Path):
    """Offline PREBUILT packing must be able to refuse rustup without curling mirrors."""
    env = _isolated_env(tmp_path)
    env["SKIP_RUST_INSTALL"] = "1"
    result = subprocess.run(  # noqa: S603
        ["bash", "-c", f"source '{_ENSURE_RUST}' && motor_install_rustup"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.returncode != 0
    assert "SKIP_RUST_INSTALL=1" in result.stderr


def test_skip_rust_build_shorthand_sets_both_per_crate_flags(tmp_path: Path):
    """No Rust changes since the last build: one knob reuses both native artifacts."""
    env = _isolated_env(tmp_path)
    env["SKIP_RUST_BUILD"] = "1"
    result = subprocess.run(  # noqa: S603
        [
            "bash",
            "-c",
            f"source '{_ENSURE_RUST}' && motor_apply_skip_rust_build_shorthand && "
            'echo "shm=$SKIP_WORKLOAD_SHM_BUILD kv=$SKIP_KV_CONDUCTOR_BUILD"',
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.returncode == 0, result.stderr
    assert "shm=1 kv=1" in result.stdout


def test_skip_rust_build_shorthand_does_not_clobber_explicit_per_crate_override(tmp_path: Path):
    """An explicit SKIP_KV_CONDUCTOR_BUILD=0 must still force a kv-conductor rebuild."""
    env = _isolated_env(tmp_path)
    env["SKIP_RUST_BUILD"] = "1"
    env["SKIP_KV_CONDUCTOR_BUILD"] = "0"
    result = subprocess.run(  # noqa: S603
        [
            "bash",
            "-c",
            f"source '{_ENSURE_RUST}' && motor_apply_skip_rust_build_shorthand && "
            'echo "shm=$SKIP_WORKLOAD_SHM_BUILD kv=$SKIP_KV_CONDUCTOR_BUILD"',
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.returncode == 0, result.stderr
    assert "shm=1 kv=0" in result.stdout


def test_skip_rust_build_shorthand_is_noop_when_unset(tmp_path: Path):
    """Default behavior (no env vars) must not silently start skipping native builds."""
    env = _isolated_env(tmp_path)
    result = subprocess.run(  # noqa: S603
        [
            "bash",
            "-c",
            f"source '{_ENSURE_RUST}' && motor_apply_skip_rust_build_shorthand && "
            'echo "shm=${SKIP_WORKLOAD_SHM_BUILD:-unset} kv=${SKIP_KV_CONDUCTOR_BUILD:-unset}"',
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.returncode == 0, result.stderr
    assert "shm=unset kv=unset" in result.stdout
