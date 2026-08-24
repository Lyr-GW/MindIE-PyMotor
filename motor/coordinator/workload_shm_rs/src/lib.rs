// Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
// MindIE is licensed under Mulan PSL v2.
// You can use this software according to the terms and conditions of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
//         http://license.coscl.org.cn/MulanPSL2
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

//! In-process POSIX shared-memory workload ledger for the MindIE-PyMotor coordinator.
//!
//! P1 scope (see `docs/zh/design/coordinator_scheduler_rust.md` §12.2): a single-writer,
//! schema-3-compatible segment written through a narrow C ABI (loaded from Python via ctypes),
//! so the existing Python `WorkloadSharedMemoryReader` reads bytes produced by this crate
//! unchanged. Per-slot atomic CAS / schema 4 / multi-writer arrive in P2 and are intentionally
//! NOT implemented here (their status codes are reserved in `error`).

use std::ffi::CStr;
use std::os::raw::{c_char, c_int};
use std::ptr;
use std::sync::atomic::{fence, AtomicI64, AtomicU32, AtomicU64, AtomicU8, Ordering};

pub mod error;
pub mod layout;

use error::ShmStatus;
use layout::{Entry, MAGIC, SCHEMA_VERSION, SCHEMA_VERSION_V4};

/// ABI version, independent of the on-wire SCHEMA_VERSION (the ABI may evolve without the layout).
pub const ABI_VERSION: u32 = 1;

/// A mapped workload segment. Not thread-safe; the coordinator drives it from one writer.
pub struct Segment {
    base: *mut u8,
    size: usize,
    max_entries: u32,
    entry_count: u32,
    instance_version: u64,
    heartbeat: u64,
    role_seq: [u64; 3], // prefill, decode, hybrid
    sequence: i64,
    schema: u16,   // on-wire schema_version this segment carries (3 or 4)
    name: Vec<u8>, // NUL-terminated POSIX name, for shm_unlink on close
    created: bool,
}

impl Segment {
    // --- atomic accessors into the mapped bytes ---
    #[inline]
    unsafe fn atomic_u64(&self, off: usize) -> &AtomicU64 {
        &*(self.base.add(off) as *const AtomicU64)
    }
    #[inline]
    unsafe fn atomic_i64(&self, off: usize) -> &AtomicI64 {
        &*(self.base.add(off) as *const AtomicI64)
    }
    #[inline]
    unsafe fn atomic_u32(&self, off: usize) -> &AtomicU32 {
        &*(self.base.add(off) as *const AtomicU32)
    }

    fn write_static_header(&self) {
        unsafe {
            self.atomic_u32(layout::OFF_MAGIC)
                .store(MAGIC, Ordering::Relaxed);
            // schema (u16) + padding (u16) share one aligned u32 slot at offset 4.
            let schema_word = self.schema as u32; // padding = 0 in the high half
            self.atomic_u32(layout::OFF_SCHEMA)
                .store(schema_word, Ordering::Relaxed);
            self.atomic_u32(layout::OFF_MAX_ENTRIES)
                .store(self.max_entries, Ordering::Relaxed);
            self.atomic_u32(layout::OFF_ENTRY_COUNT)
                .store(self.entry_count, Ordering::Relaxed);
            self.atomic_u64(layout::OFF_INSTANCE_VERSION)
                .store(self.instance_version, Ordering::Relaxed);
            self.atomic_u64(layout::OFF_HEARTBEAT)
                .store(self.heartbeat, Ordering::Relaxed);
            self.atomic_u64(layout::OFF_PREFILL_SEQ)
                .store(self.role_seq[0], Ordering::Relaxed);
            self.atomic_u64(layout::OFF_DECODE_SEQ)
                .store(self.role_seq[1], Ordering::Relaxed);
            self.atomic_u64(layout::OFF_HYBRID_SEQ)
                .store(self.role_seq[2], Ordering::Relaxed);
            self.store_sequence(self.sequence, Ordering::Release);
        }
    }

    #[inline]
    unsafe fn store_sequence(&self, seq: i64, ordering: Ordering) {
        self.atomic_i64(layout::OFF_SEQUENCE).store(seq, ordering);
    }

    fn begin_write(&mut self) {
        // Move to an odd sequence (writer in progress), publish it before touching entries.
        self.sequence = if self.sequence % 2 == 0 {
            self.sequence + 1
        } else {
            self.sequence + 2
        };
        unsafe { self.store_sequence(self.sequence, Ordering::Release) };
        fence(Ordering::Release);
    }

    fn end_write(&mut self) {
        // Publish all entry bytes before flipping the sequence back to even (stable).
        fence(Ordering::Release);
        self.sequence = if self.sequence % 2 == 1 {
            self.sequence + 1
        } else {
            self.sequence + 2
        };
        unsafe {
            self.atomic_u32(layout::OFF_ENTRY_COUNT)
                .store(self.entry_count, Ordering::Release);
            self.atomic_u64(layout::OFF_INSTANCE_VERSION)
                .store(self.instance_version, Ordering::Release);
            self.atomic_u64(layout::OFF_PREFILL_SEQ)
                .store(self.role_seq[0], Ordering::Release);
            self.atomic_u64(layout::OFF_DECODE_SEQ)
                .store(self.role_seq[1], Ordering::Release);
            self.atomic_u64(layout::OFF_HYBRID_SEQ)
                .store(self.role_seq[2], Ordering::Release);
            self.store_sequence(self.sequence, Ordering::Release);
        }
    }

    fn write_entry(&self, slot: u32, entry: &Entry) -> ShmStatus {
        if slot >= self.max_entries {
            return error::NO_SPACE;
        }
        let off = layout::entry_offset(slot);
        unsafe {
            let dst = std::slice::from_raw_parts_mut(self.base.add(off), layout::ENTRY_SIZE);
            layout::pack_entry(dst, entry);
        }
        error::OK
    }

    fn snapshot_begin(&mut self) {
        self.begin_write();
    }

    fn snapshot_commit(&mut self, entry_count: u32, bump_instance_version: bool) {
        self.entry_count = entry_count.min(self.max_entries);
        if bump_instance_version {
            self.instance_version = self.instance_version.wrapping_add(1);
        }
        // Single-writer P1: bump all role change counters so a role-scoped reader re-scans.
        for s in self.role_seq.iter_mut() {
            *s = s.wrapping_add(1);
        }
        self.end_write();
    }

    fn heartbeat(&mut self) {
        self.heartbeat = self.heartbeat.wrapping_add(1);
        unsafe {
            self.atomic_u64(layout::OFF_HEARTBEAT)
                .store(self.heartbeat, Ordering::Release);
        }
    }

    // ----------------------------------------------------------------------
    // Schema 4: per-slot atomic CAS data plane
    // ----------------------------------------------------------------------

    #[inline]
    unsafe fn v4_tokens(&self, slot: u32) -> &AtomicU64 {
        &*(self
            .base
            .add(layout::entry_offset(slot) + layout::ENTRY_V4_OFF_ACTIVE_TOKENS)
            as *const AtomicU64)
    }

    #[inline]
    unsafe fn v4_flags(&self, slot: u32) -> &AtomicU8 {
        &*(self
            .base
            .add(layout::entry_offset(slot) + layout::ENTRY_V4_OFF_FLAGS)
            as *const AtomicU8)
    }

    #[inline]
    unsafe fn v4_read_i32(&self, slot: u32, field_off: usize) -> i32 {
        let off = layout::entry_offset(slot) + field_off;
        let mut b = [0u8; 4];
        std::ptr::copy_nonoverlapping(self.base.add(off), b.as_mut_ptr(), 4);
        i32::from_le_bytes(b)
    }

    #[inline]
    unsafe fn v4_generation(&self, slot: u32) -> u16 {
        let off = layout::entry_offset(slot) + layout::ENTRY_V4_OFF_GENERATION;
        let mut b = [0u8; 2];
        std::ptr::copy_nonoverlapping(self.base.add(off), b.as_mut_ptr(), 2);
        u16::from_le_bytes(b)
    }

    #[inline]
    unsafe fn v4_role(&self, slot: u32) -> u8 {
        *self
            .base
            .add(layout::entry_offset(slot) + layout::ENTRY_V4_OFF_ROLE)
    }

    fn current_entry_count(&self) -> u32 {
        unsafe {
            self.atomic_u32(layout::OFF_ENTRY_COUNT)
                .load(Ordering::Acquire)
        }
    }

    /// Snapshot-write one schema-4 entry (call between snapshot_begin/commit). Sets VALID.
    #[allow(clippy::too_many_arguments)]
    fn write_entry_v4(
        &self,
        slot: u32,
        instance_id: i32,
        endpoint_id: i32,
        role: u8,
        generation: u16,
        flags: u8,
        active_tokens: f64,
    ) -> ShmStatus {
        if slot >= self.max_entries {
            return error::NO_SPACE;
        }
        let base_off = layout::entry_offset(slot);
        unsafe {
            let p = self.base.add(base_off);
            std::ptr::copy_nonoverlapping(instance_id.to_le_bytes().as_ptr(), p.add(0), 4);
            std::ptr::copy_nonoverlapping(endpoint_id.to_le_bytes().as_ptr(), p.add(4), 4);
            *p.add(layout::ENTRY_V4_OFF_ROLE) = role;
            std::ptr::copy_nonoverlapping(
                generation.to_le_bytes().as_ptr(),
                p.add(layout::ENTRY_V4_OFF_GENERATION),
                2,
            );
            std::ptr::write_bytes(p.add(layout::ENTRY_V4_OFF_RESERVED), 0, 4);
            self.v4_tokens(slot)
                .store(active_tokens.to_bits(), Ordering::Release);
            self.v4_flags(slot)
                .store(flags | layout::FLAG_VALID, Ordering::Release);
        }
        error::OK
    }

    /// Find the VALID slot matching (instance_id, endpoint_id) within the current entry_count.
    fn find_slot(&self, instance_id: i32, endpoint_id: i32) -> Option<u32> {
        let count = self.current_entry_count().min(self.max_entries);
        for slot in 0..count {
            unsafe {
                let flags = self.v4_flags(slot).load(Ordering::Acquire);
                if flags & layout::FLAG_VALID == 0 {
                    continue;
                }
                if self.v4_read_i32(slot, layout::ENTRY_V4_OFF_INSTANCE_ID) == instance_id
                    && self.v4_read_i32(slot, layout::ENTRY_V4_OFF_ENDPOINT_ID) == endpoint_id
                {
                    return Some(slot);
                }
            }
        }
        None
    }

    /// CAS-add `delta` iff the slot's tokens still equal `expected` and it is not BLOCKED.
    /// Returns (status, actual_bits). See design §5.4 / §6.
    fn cas_add(
        &self,
        instance_id: i32,
        endpoint_id: i32,
        generation: u16,
        expected: f64,
        delta: f64,
    ) -> (ShmStatus, u64) {
        let slot = match self.find_slot(instance_id, endpoint_id) {
            Some(s) => s,
            None => return (error::SLOT_INVALID, 0),
        };
        unsafe {
            if self.v4_generation(slot) != generation {
                return (
                    error::SLOT_INVALID,
                    self.v4_tokens(slot).load(Ordering::Acquire),
                );
            }
            let expected_bits = expected.to_bits();
            let cur = self.v4_tokens(slot).load(Ordering::Acquire);
            if self.v4_flags(slot).load(Ordering::Acquire) & layout::FLAG_BLOCKED != 0 {
                return (error::BLOCKED, cur);
            }
            if cur != expected_bits {
                // Ledger moved: caller must re-score with the fresh value, never blind-add.
                return (error::CHANGED, cur);
            }
            let new_bits = (f64::from_bits(cur) + delta).to_bits();
            match self.v4_tokens(slot).compare_exchange(
                cur,
                new_bits,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => (error::OK, new_bits),
                Err(actual) => (error::CHANGED, actual),
            }
        }
    }

    /// CAS-subtract `delta`, flooring at 0 (release path). No `expected`: the slot value having
    /// moved since allocate is normal. Returns (status, actual_bits).
    fn cas_sub_floor0(
        &self,
        instance_id: i32,
        endpoint_id: i32,
        generation: u16,
        delta: f64,
    ) -> (ShmStatus, u64) {
        let slot = match self.find_slot(instance_id, endpoint_id) {
            Some(s) => s,
            None => return (error::SLOT_INVALID, 0),
        };
        unsafe {
            if self.v4_generation(slot) != generation {
                return (
                    error::SLOT_INVALID,
                    self.v4_tokens(slot).load(Ordering::Acquire),
                );
            }
            loop {
                let cur = self.v4_tokens(slot).load(Ordering::Acquire);
                let new_val = (f64::from_bits(cur) - delta).max(0.0);
                match self.v4_tokens(slot).compare_exchange(
                    cur,
                    new_val.to_bits(),
                    Ordering::AcqRel,
                    Ordering::Acquire,
                ) {
                    Ok(_) => return (error::OK, new_val.to_bits()),
                    Err(_) => continue,
                }
            }
        }
    }

    /// Set/clear the BLOCKED flag on every VALID slot of `instance_id` (circuit-breaker gate).
    fn set_blocked(&self, instance_id: i32, blocked: bool) -> u32 {
        let count = self.current_entry_count().min(self.max_entries);
        let mut touched = 0u32;
        for slot in 0..count {
            unsafe {
                let flags = self.v4_flags(slot).load(Ordering::Acquire);
                if flags & layout::FLAG_VALID == 0 {
                    continue;
                }
                if self.v4_read_i32(slot, layout::ENTRY_V4_OFF_INSTANCE_ID) != instance_id {
                    continue;
                }
                let new = if blocked {
                    flags | layout::FLAG_BLOCKED
                } else {
                    flags & !layout::FLAG_BLOCKED
                };
                self.v4_flags(slot).store(new, Ordering::Release);
                touched += 1;
            }
        }
        touched
    }
}

impl Drop for Segment {
    fn drop(&mut self) {
        unsafe {
            if !self.base.is_null() {
                libc::munmap(self.base as *mut libc::c_void, self.size);
                self.base = ptr::null_mut();
            }
        }
    }
}

// ---------------------------------------------------------------------------
// POSIX shm helpers
// ---------------------------------------------------------------------------

/// Build a NUL-terminated POSIX shm name. glibc `shm_open` strips a leading '/'
/// and maps to `/dev/shm/<name>`, matching CPython's `multiprocessing.shared_memory`.
fn cname(name: &str) -> Vec<u8> {
    let mut v = Vec::with_capacity(name.len() + 2);
    if !name.starts_with('/') {
        v.push(b'/');
    }
    v.extend_from_slice(name.as_bytes());
    v.push(0);
    v
}

unsafe fn map_fd(fd: c_int, size: usize) -> *mut u8 {
    let p = libc::mmap(
        ptr::null_mut(),
        size,
        libc::PROT_READ | libc::PROT_WRITE,
        libc::MAP_SHARED,
        fd,
        0,
    );
    if p == libc::MAP_FAILED {
        ptr::null_mut()
    } else {
        p as *mut u8
    }
}

fn boxed_handle(seg: Segment) -> u64 {
    Box::into_raw(Box::new(seg)) as u64
}

/// # Safety
/// `handle` must be a live handle previously returned by create/attach and not yet closed.
unsafe fn seg_mut<'a>(handle: u64) -> Option<&'a mut Segment> {
    if handle == 0 {
        None
    } else {
        Some(&mut *(handle as *mut Segment))
    }
}

// ---------------------------------------------------------------------------
// C ABI
// ---------------------------------------------------------------------------

/// ABI version (decoupled from the on-wire schema version).
#[no_mangle]
pub extern "C" fn mindie_wl_abi_version() -> u32 {
    ABI_VERSION
}

/// On-wire schema version this build writes.
#[no_mangle]
pub extern "C" fn mindie_wl_schema_version() -> u32 {
    SCHEMA_VERSION as u32
}

/// Shared create implementation for a given on-wire schema (3 = P1 single-writer, 4 = P2 CAS).
///
/// Orphan recovery: if the name already exists it is unlinked and recreated, matching the Python
/// writer's FileExistsError handling.
///
/// # Safety
/// `name` must be a valid NUL-terminated C string; `out_handle` a valid, writable pointer.
unsafe fn create_segment(
    name: *const c_char,
    max_entries: u32,
    schema: u16,
    out_handle: *mut u64,
) -> ShmStatus {
    if name.is_null() || out_handle.is_null() || max_entries == 0 {
        return error::BAD_ARG;
    }
    let name_str = match CStr::from_ptr(name).to_str() {
        Ok(s) => s,
        Err(_) => return error::BAD_ARG,
    };
    let cn = cname(name_str);
    let size = layout::total_size(max_entries);
    let mode: libc::mode_t = 0o600;
    let mut fd = libc::shm_open(
        cn.as_ptr() as *const c_char,
        libc::O_CREAT | libc::O_EXCL | libc::O_RDWR,
        mode as libc::c_uint,
    );
    if fd < 0 {
        // Stale/orphan segment: unlink and retry once.
        libc::shm_unlink(cn.as_ptr() as *const c_char);
        fd = libc::shm_open(
            cn.as_ptr() as *const c_char,
            libc::O_CREAT | libc::O_EXCL | libc::O_RDWR,
            mode as libc::c_uint,
        );
    }
    if fd < 0 {
        return error::SYSCALL;
    }
    if libc::ftruncate(fd, size as libc::off_t) != 0 {
        libc::close(fd);
        libc::shm_unlink(cn.as_ptr() as *const c_char);
        return error::SYSCALL;
    }
    let base = map_fd(fd, size);
    libc::close(fd);
    if base.is_null() {
        libc::shm_unlink(cn.as_ptr() as *const c_char);
        return error::SYSCALL;
    }
    let seg = Segment {
        base,
        size,
        max_entries,
        entry_count: 0,
        instance_version: 0,
        heartbeat: 0,
        role_seq: [0; 3],
        sequence: 0,
        schema,
        name: cn,
        created: true,
    };
    seg.write_static_header();
    *out_handle = boxed_handle(seg);
    error::OK
}

/// Create (and own) a schema-3 (P1 single-writer) segment.
///
/// # Safety
/// `name` must be a valid NUL-terminated C string; `out_handle` a valid, writable pointer.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_create(
    name: *const c_char,
    max_entries: u32,
    out_handle: *mut u64,
) -> ShmStatus {
    create_segment(name, max_entries, SCHEMA_VERSION, out_handle)
}

/// Create (and own) a schema-4 (P2 per-slot CAS) segment.
///
/// # Safety
/// `name` must be a valid NUL-terminated C string; `out_handle` a valid, writable pointer.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_create_v4(
    name: *const c_char,
    max_entries: u32,
    out_handle: *mut u64,
) -> ShmStatus {
    create_segment(name, max_entries, SCHEMA_VERSION_V4, out_handle)
}

/// Attach to an existing segment (read/write mapping; does not own unlink).
///
/// # Safety
/// `name` must be a valid NUL-terminated C string; `out_handle` a valid, writable pointer.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_attach(name: *const c_char, out_handle: *mut u64) -> ShmStatus {
    if name.is_null() || out_handle.is_null() {
        return error::BAD_ARG;
    }
    let name_str = match CStr::from_ptr(name).to_str() {
        Ok(s) => s,
        Err(_) => return error::BAD_ARG,
    };
    let cn = cname(name_str);
    let fd = libc::shm_open(cn.as_ptr() as *const c_char, libc::O_RDWR, 0);
    if fd < 0 {
        return error::SYSCALL;
    }
    let mut st: libc::stat = std::mem::zeroed();
    if libc::fstat(fd, &mut st) != 0 || (st.st_size as usize) < layout::HEADER_SIZE {
        libc::close(fd);
        return error::SYSCALL;
    }
    let size = st.st_size as usize;
    let base = map_fd(fd, size);
    libc::close(fd);
    if base.is_null() {
        return error::SYSCALL;
    }
    let magic = (*(base.add(layout::OFF_MAGIC) as *const AtomicU32)).load(Ordering::Acquire);
    if magic != MAGIC {
        libc::munmap(base as *mut libc::c_void, size);
        return error::SCHEMA_MISMATCH;
    }
    let max_entries =
        (*(base.add(layout::OFF_MAX_ENTRIES) as *const AtomicU32)).load(Ordering::Acquire);
    let schema = ((*(base.add(layout::OFF_SCHEMA) as *const AtomicU32)).load(Ordering::Acquire)
        & 0xFFFF) as u16;
    let seg = Segment {
        base,
        size,
        max_entries,
        entry_count: (*(base.add(layout::OFF_ENTRY_COUNT) as *const AtomicU32))
            .load(Ordering::Acquire),
        instance_version: (*(base.add(layout::OFF_INSTANCE_VERSION) as *const AtomicU64))
            .load(Ordering::Acquire),
        heartbeat: (*(base.add(layout::OFF_HEARTBEAT) as *const AtomicU64)).load(Ordering::Acquire),
        role_seq: [
            (*(base.add(layout::OFF_PREFILL_SEQ) as *const AtomicU64)).load(Ordering::Acquire),
            (*(base.add(layout::OFF_DECODE_SEQ) as *const AtomicU64)).load(Ordering::Acquire),
            (*(base.add(layout::OFF_HYBRID_SEQ) as *const AtomicU64)).load(Ordering::Acquire),
        ],
        sequence: (*(base.add(layout::OFF_SEQUENCE) as *const AtomicI64)).load(Ordering::Acquire),
        schema,
        name: cn,
        created: false,
    };
    *out_handle = boxed_handle(seg);
    error::OK
}

/// Close a handle. `unlink != 0` also removes the shm object (only the creator should unlink).
///
/// # Safety
/// `handle` must be a live handle from create/attach; it must not be used afterwards.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_close(handle: u64, unlink: c_int) -> ShmStatus {
    if handle == 0 {
        return error::NOT_ATTACHED;
    }
    let seg = Box::from_raw(handle as *mut Segment);
    if unlink != 0 && seg.created {
        libc::shm_unlink(seg.name.as_ptr() as *const c_char);
    }
    drop(seg); // munmap via Drop
    error::OK
}

/// # Safety
/// `handle` must be a live handle from create/attach.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_snapshot_begin(handle: u64) -> ShmStatus {
    match seg_mut(handle) {
        Some(seg) => {
            seg.snapshot_begin();
            error::OK
        }
        None => error::NOT_ATTACHED,
    }
}

/// # Safety
/// `handle` must be a live handle from create/attach.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_snapshot_write_entry(
    handle: u64,
    slot: u32,
    instance_id: i32,
    endpoint_id: i32,
    role: u8,
    active_tokens: f64,
) -> ShmStatus {
    match seg_mut(handle) {
        Some(seg) => seg.write_entry(
            slot,
            &Entry {
                instance_id,
                endpoint_id,
                role,
                active_tokens,
            },
        ),
        None => error::NOT_ATTACHED,
    }
}

/// # Safety
/// `handle` must be a live handle from create/attach.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_snapshot_commit(
    handle: u64,
    entry_count: u32,
    bump_instance_version: c_int,
) -> ShmStatus {
    match seg_mut(handle) {
        Some(seg) => {
            seg.snapshot_commit(entry_count, bump_instance_version != 0);
            error::OK
        }
        None => error::NOT_ATTACHED,
    }
}

/// # Safety
/// `handle` must be a live handle from create/attach.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_heartbeat(handle: u64) -> ShmStatus {
    match seg_mut(handle) {
        Some(seg) => {
            seg.heartbeat();
            error::OK
        }
        None => error::NOT_ATTACHED,
    }
}

/// Read the header scalar fields (for a native reader / diagnostics). Any out-pointer may be null.
///
/// # Safety
/// `handle` must be a live handle from create/attach; non-null out-pointers must be writable.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_read_header(
    handle: u64,
    out_schema: *mut u32,
    out_sequence: *mut i64,
    out_entry_count: *mut u32,
    out_instance_version: *mut u64,
    out_heartbeat: *mut u64,
) -> ShmStatus {
    let seg = match seg_mut(handle) {
        Some(seg) => seg,
        None => return error::NOT_ATTACHED,
    };
    if !out_schema.is_null() {
        *out_schema = seg.atomic_u32(layout::OFF_SCHEMA).load(Ordering::Acquire) & 0xFFFF;
    }
    if !out_sequence.is_null() {
        *out_sequence = seg.atomic_i64(layout::OFF_SEQUENCE).load(Ordering::Acquire);
    }
    if !out_entry_count.is_null() {
        *out_entry_count = seg
            .atomic_u32(layout::OFF_ENTRY_COUNT)
            .load(Ordering::Acquire);
    }
    if !out_instance_version.is_null() {
        *out_instance_version = seg
            .atomic_u64(layout::OFF_INSTANCE_VERSION)
            .load(Ordering::Acquire);
    }
    if !out_heartbeat.is_null() {
        *out_heartbeat = seg
            .atomic_u64(layout::OFF_HEARTBEAT)
            .load(Ordering::Acquire);
    }
    error::OK
}

// ---------------------------------------------------------------------------
// C ABI: schema 4 per-slot CAS data plane
// ---------------------------------------------------------------------------

/// Snapshot-write one schema-4 entry (call between snapshot_begin/commit); sets VALID.
///
/// # Safety
/// `handle` must be a live handle from create_v4/attach.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn mindie_wl_snapshot_write_entry_v4(
    handle: u64,
    slot: u32,
    instance_id: i32,
    endpoint_id: i32,
    role: u8,
    generation: u16,
    flags: u8,
    active_tokens: f64,
) -> ShmStatus {
    match seg_mut(handle) {
        Some(seg) => seg.write_entry_v4(
            slot,
            instance_id,
            endpoint_id,
            role,
            generation,
            flags,
            active_tokens,
        ),
        None => error::NOT_ATTACHED,
    }
}

/// CAS-add on the (instance_id, endpoint_id) slot. `out_actual` receives the new value on Ok, or
/// the current value on Changed/Blocked. Returns Ok/Changed/Blocked/SlotInvalid.
///
/// # Safety
/// `handle` must be a live handle from create_v4/attach; `out_actual` may be null.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_cas_add(
    handle: u64,
    instance_id: i32,
    endpoint_id: i32,
    generation: u16,
    expected: f64,
    delta: f64,
    out_actual: *mut f64,
) -> ShmStatus {
    let seg = match seg_mut(handle) {
        Some(seg) => seg,
        None => return error::NOT_ATTACHED,
    };
    let (status, actual_bits) = seg.cas_add(instance_id, endpoint_id, generation, expected, delta);
    if !out_actual.is_null() {
        *out_actual = f64::from_bits(actual_bits);
    }
    status
}

/// CAS-subtract on the (instance_id, endpoint_id) slot, flooring at 0. `out_actual` receives the
/// new value on Ok. Returns Ok/SlotInvalid.
///
/// # Safety
/// `handle` must be a live handle from create_v4/attach; `out_actual` may be null.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_cas_sub_floor0(
    handle: u64,
    instance_id: i32,
    endpoint_id: i32,
    generation: u16,
    delta: f64,
    out_actual: *mut f64,
) -> ShmStatus {
    let seg = match seg_mut(handle) {
        Some(seg) => seg,
        None => return error::NOT_ATTACHED,
    };
    let (status, actual_bits) = seg.cas_sub_floor0(instance_id, endpoint_id, generation, delta);
    if !out_actual.is_null() {
        *out_actual = f64::from_bits(actual_bits);
    }
    status
}

/// Set/clear the BLOCKED flag on all VALID slots of an instance. `out_touched` gets the slot count.
///
/// # Safety
/// `handle` must be a live handle from create_v4/attach; `out_touched` may be null.
#[no_mangle]
pub unsafe extern "C" fn mindie_wl_set_blocked(
    handle: u64,
    instance_id: i32,
    blocked: c_int,
    out_touched: *mut u32,
) -> ShmStatus {
    let seg = match seg_mut(handle) {
        Some(seg) => seg,
        None => return error::NOT_ATTACHED,
    };
    let touched = seg.set_blocked(instance_id, blocked != 0);
    if !out_touched.is_null() {
        *out_touched = touched;
    }
    error::OK
}

/// Read one schema-4 entry's fields. Any out-pointer may be null.
///
/// # Safety
/// `handle` must be a live handle from create_v4/attach; non-null out-pointers must be writable.
#[no_mangle]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn mindie_wl_load_entry(
    handle: u64,
    slot: u32,
    out_instance_id: *mut i32,
    out_endpoint_id: *mut i32,
    out_role: *mut u8,
    out_flags: *mut u8,
    out_generation: *mut u16,
    out_active_tokens: *mut f64,
) -> ShmStatus {
    let seg = match seg_mut(handle) {
        Some(seg) => seg,
        None => return error::NOT_ATTACHED,
    };
    if slot >= seg.max_entries {
        return error::NO_SPACE;
    }
    if !out_instance_id.is_null() {
        *out_instance_id = seg.v4_read_i32(slot, layout::ENTRY_V4_OFF_INSTANCE_ID);
    }
    if !out_endpoint_id.is_null() {
        *out_endpoint_id = seg.v4_read_i32(slot, layout::ENTRY_V4_OFF_ENDPOINT_ID);
    }
    if !out_role.is_null() {
        *out_role = seg.v4_role(slot);
    }
    if !out_flags.is_null() {
        *out_flags = seg.v4_flags(slot).load(Ordering::Acquire);
    }
    if !out_generation.is_null() {
        *out_generation = seg.v4_generation(slot);
    }
    if !out_active_tokens.is_null() {
        *out_active_tokens = f64::from_bits(seg.v4_tokens(slot).load(Ordering::Acquire));
    }
    error::OK
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CString;

    fn unique_name(tag: &str) -> String {
        format!("mindie_wl_rs_test_{}_{}", tag, std::process::id())
    }

    #[test]
    fn create_write_reattach_roundtrip() {
        let name = unique_name("rt");
        let cn = CString::new(name.clone()).unwrap();
        unsafe {
            let mut h: u64 = 0;
            assert_eq!(mindie_wl_create(cn.as_ptr(), 16, &mut h), error::OK);
            assert_eq!(mindie_wl_snapshot_begin(h), error::OK);
            assert_eq!(
                mindie_wl_snapshot_write_entry(h, 0, 1, 10, layout::ROLE_PREFILL, 7.0),
                error::OK
            );
            assert_eq!(
                mindie_wl_snapshot_write_entry(h, 1, 2, 20, layout::ROLE_PREFILL, 9.0),
                error::OK
            );
            assert_eq!(mindie_wl_snapshot_commit(h, 2, 1), error::OK);
            assert_eq!(mindie_wl_heartbeat(h), error::OK);

            // Independent attach observes the committed, stable (even) snapshot.
            let mut h2: u64 = 0;
            assert_eq!(mindie_wl_attach(cn.as_ptr(), &mut h2), error::OK);
            let mut schema = 0u32;
            let mut seq = 0i64;
            let mut count = 0u32;
            let mut ver = 0u64;
            let mut hb = 0u64;
            assert_eq!(
                mindie_wl_read_header(h2, &mut schema, &mut seq, &mut count, &mut ver, &mut hb),
                error::OK
            );
            assert_eq!(schema, SCHEMA_VERSION as u32);
            assert_eq!(seq % 2, 0);
            assert_eq!(count, 2);
            assert_eq!(ver, 1);
            assert_eq!(hb, 1);

            let base = seg_mut(h2).unwrap().base;
            let e0 = layout::unpack_entry(std::slice::from_raw_parts(
                base.add(layout::entry_offset(0)),
                layout::ENTRY_SIZE,
            ));
            assert_eq!(e0.instance_id, 1);
            assert_eq!(e0.active_tokens, 7.0);

            assert_eq!(mindie_wl_close(h2, 0), error::OK);
            assert_eq!(mindie_wl_close(h, 1), error::OK); // creator unlinks
        }
    }

    #[test]
    fn odd_sequence_visible_during_write() {
        let name = unique_name("odd");
        let cn = CString::new(name).unwrap();
        unsafe {
            let mut h: u64 = 0;
            assert_eq!(mindie_wl_create(cn.as_ptr(), 4, &mut h), error::OK);
            assert_eq!(mindie_wl_snapshot_begin(h), error::OK);
            let seq = seg_mut(h)
                .unwrap()
                .atomic_i64(layout::OFF_SEQUENCE)
                .load(Ordering::Acquire);
            assert_eq!(seq % 2, 1, "sequence must be odd mid-write");
            assert_eq!(mindie_wl_snapshot_commit(h, 0, 0), error::OK);
            let seq2 = seg_mut(h)
                .unwrap()
                .atomic_i64(layout::OFF_SEQUENCE)
                .load(Ordering::Acquire);
            assert_eq!(seq2 % 2, 0, "sequence must be even after commit");
            assert_eq!(mindie_wl_close(h, 1), error::OK);
        }
    }

    #[test]
    fn create_recovers_from_orphan() {
        let name = unique_name("orphan");
        let cn = CString::new(name).unwrap();
        unsafe {
            let mut h1: u64 = 0;
            assert_eq!(mindie_wl_create(cn.as_ptr(), 4, &mut h1), error::OK);
            // Leak the mapping (simulate a crashed writer that never unlinked).
            std::mem::forget(Box::from_raw(h1 as *mut Segment));
            // A fresh create over the orphan must succeed (unlink + recreate).
            let mut h2: u64 = 0;
            assert_eq!(mindie_wl_create(cn.as_ptr(), 4, &mut h2), error::OK);
            assert_eq!(mindie_wl_close(h2, 1), error::OK);
        }
    }

    // --- schema 4 CAS ---

    unsafe fn v4_single_entry(tag: &str) -> (u64, CString) {
        let cn = CString::new(unique_name(tag)).unwrap();
        let mut h: u64 = 0;
        assert_eq!(mindie_wl_create_v4(cn.as_ptr(), 8, &mut h), error::OK);
        assert_eq!(mindie_wl_snapshot_begin(h), error::OK);
        // slot 0: instance 1, endpoint 10, generation 0, tokens 0.0
        assert_eq!(
            mindie_wl_snapshot_write_entry_v4(h, 0, 1, 10, layout::ROLE_PREFILL, 0, 0, 0.0),
            error::OK
        );
        assert_eq!(mindie_wl_snapshot_commit(h, 1, 1), error::OK);
        (h, cn)
    }

    #[test]
    fn cas_add_ok_and_stale_changed() {
        unsafe {
            let (h, _cn) = v4_single_entry("cas_ok");
            let mut actual = -1.0f64;
            // expected matches current (0.0) -> Ok, tokens become 3.0
            assert_eq!(
                mindie_wl_cas_add(h, 1, 10, 0, 0.0, 3.0, &mut actual),
                error::OK
            );
            assert_eq!(actual, 3.0);
            // stale expected (0.0 != 3.0) -> Changed, returns current 3.0, no add
            assert_eq!(
                mindie_wl_cas_add(h, 1, 10, 0, 0.0, 100.0, &mut actual),
                error::CHANGED
            );
            assert_eq!(actual, 3.0);
            assert_eq!(mindie_wl_close(h, 1), error::OK);
        }
    }

    #[test]
    fn cas_sub_floor0_never_negative() {
        unsafe {
            let (h, _cn) = v4_single_entry("floor0");
            let mut actual = -1.0f64;
            assert_eq!(
                mindie_wl_cas_add(h, 1, 10, 0, 0.0, 5.0, &mut actual),
                error::OK
            );
            // subtract more than present -> floors at 0
            assert_eq!(
                mindie_wl_cas_sub_floor0(h, 1, 10, 0, 9.0, &mut actual),
                error::OK
            );
            assert_eq!(actual, 0.0);
            assert_eq!(mindie_wl_close(h, 1), error::OK);
        }
    }

    #[test]
    fn blocked_flag_gates_cas_add() {
        unsafe {
            let (h, _cn) = v4_single_entry("blocked");
            let mut touched = 0u32;
            assert_eq!(mindie_wl_set_blocked(h, 1, 1, &mut touched), error::OK);
            assert_eq!(touched, 1);
            let mut actual = -1.0f64;
            assert_eq!(
                mindie_wl_cas_add(h, 1, 10, 0, 0.0, 1.0, &mut actual),
                error::BLOCKED
            );
            assert_eq!(actual, 0.0); // unchanged
                                     // clearing the flag re-enables allocation
            assert_eq!(mindie_wl_set_blocked(h, 1, 0, &mut touched), error::OK);
            assert_eq!(
                mindie_wl_cas_add(h, 1, 10, 0, 0.0, 1.0, &mut actual),
                error::OK
            );
            assert_eq!(actual, 1.0);
            assert_eq!(mindie_wl_close(h, 1), error::OK);
        }
    }

    #[test]
    fn generation_mismatch_is_slot_invalid() {
        unsafe {
            let (h, _cn) = v4_single_entry("gen");
            let mut actual = -1.0f64;
            // slot generation is 0; caller remembers 1 -> SlotInvalid (ABA guard)
            assert_eq!(
                mindie_wl_cas_add(h, 1, 10, 1, 0.0, 1.0, &mut actual),
                error::SLOT_INVALID
            );
            assert_eq!(mindie_wl_close(h, 1), error::OK);
        }
    }

    #[test]
    fn missing_slot_is_slot_invalid() {
        unsafe {
            let (h, _cn) = v4_single_entry("missing");
            let mut actual = -1.0f64;
            assert_eq!(
                mindie_wl_cas_add(h, 999, 999, 0, 0.0, 1.0, &mut actual),
                error::SLOT_INVALID
            );
            assert_eq!(mindie_wl_close(h, 1), error::OK);
        }
    }

    #[test]
    fn multithread_cas_add_conserves_total() {
        // R1 core: N threads each add 1.0 M times with a CAS-expected retry loop; the final value
        // must equal N*M exactly (no lost updates), proving hardware-atomic multi-writer accounting.
        unsafe {
            let cn = CString::new(unique_name("conserve")).unwrap();
            let mut h: u64 = 0;
            assert_eq!(mindie_wl_create_v4(cn.as_ptr(), 8, &mut h), error::OK);
            assert_eq!(mindie_wl_snapshot_begin(h), error::OK);
            assert_eq!(
                mindie_wl_snapshot_write_entry_v4(h, 0, 1, 10, layout::ROLE_PREFILL, 0, 0, 0.0),
                error::OK
            );
            assert_eq!(mindie_wl_snapshot_commit(h, 1, 1), error::OK);

            let n_threads = 8usize;
            let per_thread = 2000usize;
            let handle_val = h;
            let mut joins = Vec::new();
            for _ in 0..n_threads {
                let hv = handle_val;
                joins.push(std::thread::spawn(move || {
                    for _ in 0..per_thread {
                        loop {
                            let mut actual = 0.0f64;
                            let status = mindie_wl_cas_add(
                                hv,
                                1,
                                10,
                                0,
                                {
                                    // read current value as expected
                                    let mut cur = 0.0f64;
                                    mindie_wl_load_entry(
                                        hv,
                                        0,
                                        std::ptr::null_mut(),
                                        std::ptr::null_mut(),
                                        std::ptr::null_mut(),
                                        std::ptr::null_mut(),
                                        std::ptr::null_mut(),
                                        &mut cur,
                                    );
                                    cur
                                },
                                1.0,
                                &mut actual,
                            );
                            if status == error::OK {
                                break;
                            }
                            // Changed: retry with the fresh value.
                        }
                    }
                }));
            }
            for j in joins {
                j.join().unwrap();
            }
            let mut total = 0.0f64;
            assert_eq!(
                mindie_wl_load_entry(
                    h,
                    0,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    &mut total
                ),
                error::OK
            );
            assert_eq!(total, (n_threads * per_thread) as f64);
            assert_eq!(mindie_wl_close(h, 1), error::OK);
        }
    }
}
