# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""
ctypes binding for the Rust ``libmindie_workload_shm`` shared-memory writer (design §8.4 / §8.6).

P1 exposes the schema-3 single-writer surface (create / attach / snapshot / heartbeat / close) so
the segment written here is byte-compatible with the existing Python
``WorkloadSharedMemoryReader``. If the ``.so`` is missing the loader raises
``NativeWorkloadShmUnavailable`` with a clear message -- callers must fail loudly rather than
silently fall back to a wrong ledger (design §8.5 / R-6 / A7).
"""

import ctypes
import os

from motor.common.logger import get_logger
from motor.common.resources.instance import PDRole
from motor.coordinator.scheduler.runtime.workload_shm.layout import (
    DEFAULT_WORKLOAD_SHM_MAX_ENTRIES,
    ROLE_DECODE,
    ROLE_ENCODE,
    ROLE_HYBRID,
    ROLE_PREFILL,
)

logger = get_logger(__name__)

_LIB_BASENAME = "libmindie_workload_shm.so"
_ENV_OVERRIDE = "WORKLOAD_SHM_LIB"

# C ABI status codes (must match src/error.rs).
_STATUS = {
    0: "Ok",
    1: "Changed",
    2: "Blocked",
    3: "SlotInvalid",
    4: "SchemaMismatch",
    5: "NotAttached",
    6: "NoSpace",
    7: "Syscall",
    8: "BadArg",
}
_STATUS_OK = 0

_PDROLE_TO_SHM = {
    PDRole.ROLE_E: ROLE_ENCODE,
    PDRole.ROLE_P: ROLE_PREFILL,
    PDRole.ROLE_D: ROLE_DECODE,
    PDRole.ROLE_U: ROLE_HYBRID,
}


class NativeWorkloadShmUnavailable(RuntimeError):
    """Raised when the native workload-shm library cannot be loaded."""


class NativeWorkloadShmError(RuntimeError):
    """Raised when a native workload-shm call returns a non-Ok status."""


def pdrole_to_shm_role(role: PDRole) -> int:
    """Map PDRole to the shm layout role byte (hybrid for unknowns, matching the Python writer)."""
    return _PDROLE_TO_SHM.get(role, ROLE_HYBRID)


def _candidate_paths() -> list[str]:
    """Search order: explicit env override, packaged wheel lib dir, then source build output."""
    paths: list[str] = []
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        paths.append(override)
    crate_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "workload_shm_rs"))
    paths.append(os.path.join(crate_dir, "lib", _LIB_BASENAME))  # packaged (setup.py package_data)
    paths.append(os.path.join(crate_dir, "target", "release", _LIB_BASENAME))  # source dev
    return paths


def _bind(lib: ctypes.CDLL) -> ctypes.CDLL:
    """Declare argtypes/restype for the C ABI so ctypes marshals arguments correctly."""
    lib.mindie_wl_abi_version.restype = ctypes.c_uint32
    lib.mindie_wl_abi_version.argtypes = []
    lib.mindie_wl_schema_version.restype = ctypes.c_uint32
    lib.mindie_wl_schema_version.argtypes = []
    lib.mindie_wl_create.restype = ctypes.c_int32
    lib.mindie_wl_create.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64)]
    lib.mindie_wl_attach.restype = ctypes.c_int32
    lib.mindie_wl_attach.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint64)]
    lib.mindie_wl_close.restype = ctypes.c_int32
    lib.mindie_wl_close.argtypes = [ctypes.c_uint64, ctypes.c_int32]
    lib.mindie_wl_snapshot_begin.restype = ctypes.c_int32
    lib.mindie_wl_snapshot_begin.argtypes = [ctypes.c_uint64]
    lib.mindie_wl_snapshot_write_entry.restype = ctypes.c_int32
    lib.mindie_wl_snapshot_write_entry.argtypes = [
        ctypes.c_uint64,
        ctypes.c_uint32,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_uint8,
        ctypes.c_double,
    ]
    lib.mindie_wl_snapshot_commit.restype = ctypes.c_int32
    lib.mindie_wl_snapshot_commit.argtypes = [ctypes.c_uint64, ctypes.c_uint32, ctypes.c_int32]
    lib.mindie_wl_heartbeat.restype = ctypes.c_int32
    lib.mindie_wl_heartbeat.argtypes = [ctypes.c_uint64]
    lib.mindie_wl_read_header.restype = ctypes.c_int32
    lib.mindie_wl_read_header.argtypes = [
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_int64),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
    ]
    return lib


_lib_cache: ctypes.CDLL | None = None


def load_native_library(path: str | None = None) -> ctypes.CDLL:
    """
    Load (and cache) the native workload-shm library.

    Raises NativeWorkloadShmUnavailable with the searched paths when it cannot be found/loaded, so
    the caller degrades loudly instead of writing a wrong ledger.
    """
    global _lib_cache
    if path is None and _lib_cache is not None:
        return _lib_cache
    candidates = [path] if path else _candidate_paths()
    errors: list[str] = []
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            errors.append(f"{candidate}: not found")
            continue
        try:
            lib = _bind(ctypes.CDLL(candidate))
        except OSError as e:
            errors.append(f"{candidate}: {e}")
            continue
        if path is None:
            _lib_cache = lib
        return lib
    raise NativeWorkloadShmUnavailable(
        "Could not load "
        + _LIB_BASENAME
        + " (build it via build.sh / `cargo build --release` in "
        + "motor/coordinator/workload_shm_rs, or set "
        + _ENV_OVERRIDE
        + "). Tried: "
        + "; ".join(errors)
    )


class WorkloadShm:
    """Thin OO wrapper over the C ABI. One instance owns one handle."""

    def __init__(self, lib: ctypes.CDLL, handle: int, *, created: bool):
        self._lib = lib
        self._handle = handle
        self._created = created

    @property
    def handle(self) -> int:
        """Opaque native handle."""
        return self._handle

    @classmethod
    def create(
        cls,
        name: str,
        max_entries: int = DEFAULT_WORKLOAD_SHM_MAX_ENTRIES,
        *,
        lib: ctypes.CDLL | None = None,
    ) -> "WorkloadShm":
        """Create and own a new segment (unlinks any orphan of the same name first)."""
        lib = lib or load_native_library()
        handle = ctypes.c_uint64(0)
        _check(lib.mindie_wl_create(name.encode("utf-8"), int(max_entries), ctypes.byref(handle)), "create")
        return cls(lib, handle.value, created=True)

    @classmethod
    def attach(cls, name: str, *, lib: ctypes.CDLL | None = None) -> "WorkloadShm":
        """Attach to an existing segment (does not own unlink)."""
        lib = lib or load_native_library()
        handle = ctypes.c_uint64(0)
        _check(lib.mindie_wl_attach(name.encode("utf-8"), ctypes.byref(handle)), "attach")
        return cls(lib, handle.value, created=False)

    def snapshot_begin(self) -> None:
        """Mark the segment writer-in-progress (odd seqlock)."""
        _check(self._lib.mindie_wl_snapshot_begin(self._handle), "snapshot_begin")

    def write_entry(self, slot: int, instance_id: int, endpoint_id: int, role: int, active_tokens: float) -> None:
        """Write one 24-byte entry at ``slot`` (call between begin and commit)."""
        _check(
            self._lib.mindie_wl_snapshot_write_entry(
                self._handle, int(slot), int(instance_id), int(endpoint_id), int(role), float(active_tokens)
            ),
            "write_entry",
        )

    def snapshot_commit(self, entry_count: int, bump_instance_version: bool = True) -> None:
        """Publish the snapshot (even seqlock) with ``entry_count`` valid slots."""
        _check(
            self._lib.mindie_wl_snapshot_commit(self._handle, int(entry_count), 1 if bump_instance_version else 0),
            "snapshot_commit",
        )

    def write_snapshot(
        self,
        entries: list[tuple[int, int, int, float]],
        *,
        bump_instance_version: bool = True,
    ) -> None:
        """Write a full snapshot: (instance_id, endpoint_id, role_byte, active_tokens) per slot."""
        self.snapshot_begin()
        for slot, (iid, eid, role, tokens) in enumerate(entries):
            self.write_entry(slot, iid, eid, role, tokens)
        self.snapshot_commit(len(entries), bump_instance_version=bump_instance_version)

    def heartbeat(self) -> None:
        """Bump the heartbeat counter (~1/s) so readers can detect a dead writer."""
        _check(self._lib.mindie_wl_heartbeat(self._handle), "heartbeat")

    def read_header(self) -> dict[str, int]:
        """Read header scalars: schema_version, sequence, entry_count, instance_version, heartbeat."""
        schema = ctypes.c_uint32(0)
        sequence = ctypes.c_int64(0)
        entry_count = ctypes.c_uint32(0)
        instance_version = ctypes.c_uint64(0)
        heartbeat = ctypes.c_uint64(0)
        _check(
            self._lib.mindie_wl_read_header(
                self._handle,
                ctypes.byref(schema),
                ctypes.byref(sequence),
                ctypes.byref(entry_count),
                ctypes.byref(instance_version),
                ctypes.byref(heartbeat),
            ),
            "read_header",
        )
        return {
            "schema_version": schema.value,
            "sequence": sequence.value,
            "entry_count": entry_count.value,
            "instance_version": instance_version.value,
            "heartbeat": heartbeat.value,
        }

    def close(self, unlink: bool | None = None) -> None:
        """Close the handle; unlinks the segment when this instance created it (unless overridden)."""
        if self._handle == 0:
            return
        do_unlink = self._created if unlink is None else unlink
        self._lib.mindie_wl_close(self._handle, 1 if do_unlink else 0)
        self._handle = 0


def _check(status: int, op: str) -> None:
    if status != _STATUS_OK:
        raise NativeWorkloadShmError(f"{op} failed: status={status} ({_STATUS.get(status, 'Unknown')})")
