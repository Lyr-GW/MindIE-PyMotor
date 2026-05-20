#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Lightweight log throttling utilities.

The classes in this module keep log volume bounded when a noisy code path is
on the hot request path. They are intentionally process-local (no IPC) and
synchronous: throttling decisions must be cheap enough to evaluate per
request.

Two primitives are provided:

* :class:`StateLogThrottle` - logs only on *state transitions* (e.g. switching
  from "conductor returns data" to "conductor returns nothing"), plus an
  optional periodic heartbeat to remind operators the bad state is still
  active. Use this when you care about edge transitions more than raw counts.

* :class:`IntervalLogThrottle` - logs at most once per ``interval_seconds``
  per (file, line) key while suppressing intermediate occurrences. Use this
  when the same condition keeps firing and you just want to rate-limit it.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple


class StateLogThrottle:
    """Emit a log only on state transitions, with periodic heartbeats.

    Designed for "stuck in bad state" warnings: by default, the first call
    reporting state ``X`` always logs; subsequent calls reporting the same
    state are suppressed until either the state changes or
    ``heartbeat_seconds`` have elapsed.

    Thread-safe via an internal ``RLock``. Each instance maintains its own
    state machine; create one per distinct logical condition.
    """

    def __init__(self, heartbeat_seconds: float = 60.0) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self._heartbeat = float(heartbeat_seconds)
        self._lock = threading.RLock()
        self._last_state: Any = _UNSET
        self._last_log_at: float = 0.0
        self._suppressed_since_log: int = 0

    def should_log(self, state: Any) -> Tuple[bool, int]:
        """Return ``(should_log, suppressed_count_since_last_log)``.

        Caller is expected to actually emit the log when ``should_log`` is
        ``True``; the suppressed-count is provided so the caller can include
        it in the message (e.g. ``"warning observed N times since last log"``).
        """
        now = time.monotonic()
        with self._lock:
            transition = state != self._last_state
            heartbeat_due = (now - self._last_log_at) >= self._heartbeat
            if transition or heartbeat_due or self._last_state is _UNSET:
                suppressed = self._suppressed_since_log
                self._last_state = state
                self._last_log_at = now
                self._suppressed_since_log = 0
                return True, suppressed
            self._suppressed_since_log += 1
            return False, self._suppressed_since_log

    def reset(self) -> None:
        """Clear internal state. Intended for tests."""
        with self._lock:
            self._last_state = _UNSET
            self._last_log_at = 0.0
            self._suppressed_since_log = 0


class IntervalLogThrottle:
    """Rate-limit log emission per key to at most one per ``interval_seconds``.

    Use when the *quantity* of occurrences matters less than not flooding the
    log pipeline. Returns suppressed count so the caller can surface it.
    """

    def __init__(self, interval_seconds: float = 30.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._interval = float(interval_seconds)
        self._lock = threading.RLock()
        self._last_emit_at: Dict[str, float] = {}
        self._suppressed: Dict[str, int] = {}

    def should_log(self, key: str = "_default_") -> Tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            last = self._last_emit_at.get(key)
            if last is None or (now - last) >= self._interval:
                suppressed = self._suppressed.pop(key, 0)
                self._last_emit_at[key] = now
                return True, suppressed
            self._suppressed[key] = self._suppressed.get(key, 0) + 1
            return False, self._suppressed[key]

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._last_emit_at.clear()
                self._suppressed.clear()
            else:
                self._last_emit_at.pop(key, None)
                self._suppressed.pop(key, None)


# Sentinel for "no state observed yet"; using a private object avoids clashing
# with any meaningful state value a caller might pass.
_UNSET = object()
