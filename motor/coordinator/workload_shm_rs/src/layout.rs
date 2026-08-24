// Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
// MindIE is licensed under Mulan PSL v2.
// You can use this software according to the terms and conditions of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
//         http://license.coscl.org.cn/MulanPSL2
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

//! Byte layout for the workload shared-memory segment.
//!
//! This mirrors, byte-for-byte, the Python layout in
//! `motor/coordinator/scheduler/runtime/workload_shm/layout.py` (SCHEMA_VERSION 3):
//! a 64-byte header followed by N 24-byte entries, little-endian, so the existing Python
//! `WorkloadSharedMemoryReader` can read a segment written by this crate unchanged.

/// Magic "WKLD" (0x57 0x4B 0x4C 0x44) little-endian.
pub const MAGIC: u32 = 0x574B_4C44;
/// Layout schema version. Must match the Python reader/writer.
pub const SCHEMA_VERSION: u16 = 3;

pub const HEADER_SIZE: usize = 64;
pub const ENTRY_SIZE: usize = 24;
pub const DEFAULT_MAX_ENTRIES: u32 = 10240;

// Header field byte offsets (see layout.py HEADER_FMT "<I H H q I I Q Q Q Q Q").
pub const OFF_MAGIC: usize = 0; // u32
pub const OFF_SCHEMA: usize = 4; // u16
pub const OFF_SEQUENCE: usize = 8; // i64 (seqlock; odd = write in progress)
pub const OFF_ENTRY_COUNT: usize = 16; // u32
pub const OFF_MAX_ENTRIES: usize = 20; // u32
pub const OFF_INSTANCE_VERSION: usize = 24; // u64
pub const OFF_HEARTBEAT: usize = 32; // u64
pub const OFF_PREFILL_SEQ: usize = 40; // u64
pub const OFF_DECODE_SEQ: usize = 48; // u64
pub const OFF_HYBRID_SEQ: usize = 56; // u64

// Entry field byte offsets within a 24-byte slot (see layout.py ENTRY_FMT "<i i B 3x d 4x").
pub const ENTRY_OFF_INSTANCE_ID: usize = 0; // i32
pub const ENTRY_OFF_ENDPOINT_ID: usize = 4; // i32
pub const ENTRY_OFF_ROLE: usize = 8; // u8
pub const ENTRY_OFF_ACTIVE_TOKENS: usize = 12; // f64 (4-byte aligned only; not atomic)

// shm role bytes (layout.py: prefill=0, decode=1, hybrid=2, encode=3).
pub const ROLE_PREFILL: u8 = 0;
pub const ROLE_DECODE: u8 = 1;
pub const ROLE_HYBRID: u8 = 2;
pub const ROLE_ENCODE: u8 = 3;

// ---------------------------------------------------------------------------
// Schema 4 (P2): per-slot atomic CAS layout. Header is unchanged (64B); the schema_version field
// is 4 and the seqlock now covers only membership changes (token CAS does NOT bump it), so readers
// must atomic-load tokens on every scoring pass.
// ---------------------------------------------------------------------------

pub const SCHEMA_VERSION_V4: u16 = 4;

// Entry field byte offsets within a 24-byte slot for schema 4.
//
// active_tokens is placed at offset 16 so that, with an 8-aligned segment base and a 24B stride,
// it is always 8-byte aligned and can host a sound hardware `AtomicU64` CAS (mandatory on
// aarch64 / Ascend hosts, where a misaligned 8-byte atomic faults).
//
// NOTE: design §5.2 lists active_tokens at offset 12; under a 24B stride that is only 4-byte
// aligned (64 + slot*24 + 12 ≡ 4 mod 8) and cannot host an aligned u64 atomic. We keep every field,
// the 24B size, and all semantics; only the intra-entry offset of active_tokens/reserved moved.
pub const ENTRY_V4_OFF_INSTANCE_ID: usize = 0; // i32 (written on snapshot only)
pub const ENTRY_V4_OFF_ENDPOINT_ID: usize = 4; // i32 (written on snapshot only)
pub const ENTRY_V4_OFF_ROLE: usize = 8; // u8 (written on snapshot only)
pub const ENTRY_V4_OFF_FLAGS: usize = 9; // u8, AtomicU8 (BLOCKED / VALID)
pub const ENTRY_V4_OFF_GENERATION: usize = 10; // u16 (written on snapshot only; ABA guard)
pub const ENTRY_V4_OFF_RESERVED: usize = 12; // u32
pub const ENTRY_V4_OFF_ACTIVE_TOKENS: usize = 16; // u64 (f64::to_bits), AtomicU64, 8-aligned

// Entry flags bits.
pub const FLAG_BLOCKED: u8 = 0b0000_0001; // circuit-breaker OPEN: allocate CAS must refuse
pub const FLAG_VALID: u8 = 0b0000_0010; // slot holds a live (instance, endpoint)

// Compile-time guarantee that the 8-byte atomic active_tokens fits inside a 24B entry.
const _: () = assert!(ENTRY_V4_OFF_ACTIVE_TOKENS + 8 <= ENTRY_SIZE);

/// Total segment size in bytes for `max_entries` slots.
pub fn total_size(max_entries: u32) -> usize {
    HEADER_SIZE + (max_entries as usize) * ENTRY_SIZE
}

/// Byte offset of the given slot's entry.
pub fn entry_offset(slot: u32) -> usize {
    HEADER_SIZE + (slot as usize) * ENTRY_SIZE
}

/// One workload entry.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Entry {
    pub instance_id: i32,
    pub endpoint_id: i32,
    pub role: u8,
    pub active_tokens: f64,
}

/// Write an entry's 24 bytes into `slot_bytes` (must be at least ENTRY_SIZE long).
pub fn pack_entry(slot_bytes: &mut [u8], entry: &Entry) {
    slot_bytes[ENTRY_OFF_INSTANCE_ID..ENTRY_OFF_INSTANCE_ID + 4]
        .copy_from_slice(&entry.instance_id.to_le_bytes());
    slot_bytes[ENTRY_OFF_ENDPOINT_ID..ENTRY_OFF_ENDPOINT_ID + 4]
        .copy_from_slice(&entry.endpoint_id.to_le_bytes());
    slot_bytes[ENTRY_OFF_ROLE] = entry.role;
    slot_bytes[ENTRY_OFF_ROLE + 1..ENTRY_OFF_ROLE + 4].fill(0);
    slot_bytes[ENTRY_OFF_ACTIVE_TOKENS..ENTRY_OFF_ACTIVE_TOKENS + 8]
        .copy_from_slice(&entry.active_tokens.to_le_bytes());
    slot_bytes[ENTRY_OFF_ACTIVE_TOKENS + 8..ENTRY_SIZE].fill(0);
}

/// Read an entry's 24 bytes back (used by cargo tests / native reader).
pub fn unpack_entry(slot_bytes: &[u8]) -> Entry {
    let mut iid = [0u8; 4];
    iid.copy_from_slice(&slot_bytes[ENTRY_OFF_INSTANCE_ID..ENTRY_OFF_INSTANCE_ID + 4]);
    let mut eid = [0u8; 4];
    eid.copy_from_slice(&slot_bytes[ENTRY_OFF_ENDPOINT_ID..ENTRY_OFF_ENDPOINT_ID + 4]);
    let mut tokens = [0u8; 8];
    tokens.copy_from_slice(&slot_bytes[ENTRY_OFF_ACTIVE_TOKENS..ENTRY_OFF_ACTIVE_TOKENS + 8]);
    Entry {
        instance_id: i32::from_le_bytes(iid),
        endpoint_id: i32::from_le_bytes(eid),
        role: slot_bytes[ENTRY_OFF_ROLE],
        active_tokens: f64::from_le_bytes(tokens),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn entry_roundtrips_24_bytes() {
        let mut buf = [0xAAu8; ENTRY_SIZE];
        let e = Entry {
            instance_id: 7,
            endpoint_id: 21,
            role: ROLE_DECODE,
            active_tokens: 12.5,
        };
        pack_entry(&mut buf, &e);
        // padding bytes must be zeroed.
        assert_eq!(&buf[9..12], &[0, 0, 0]);
        assert_eq!(&buf[20..24], &[0, 0, 0, 0]);
        assert_eq!(unpack_entry(&buf), e);
    }

    #[test]
    fn sizes_match_python_layout() {
        assert_eq!(HEADER_SIZE, 64);
        assert_eq!(ENTRY_SIZE, 24);
        assert_eq!(total_size(10240), 64 + 10240 * 24);
        assert_eq!(entry_offset(0), 64);
        assert_eq!(entry_offset(1), 88);
    }

    #[test]
    fn schema4_active_tokens_is_8_byte_aligned_for_every_slot() {
        // A sound AtomicU64 CAS requires the address be 8-aligned on all slots.
        for slot in 0..1024u32 {
            let off = entry_offset(slot) + ENTRY_V4_OFF_ACTIVE_TOKENS;
            assert_eq!(
                off % 8,
                0,
                "slot {slot} active_tokens offset {off} not 8-aligned"
            );
        }
    }
}
