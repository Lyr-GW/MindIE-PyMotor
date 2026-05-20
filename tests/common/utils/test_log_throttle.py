# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 license for more details.

"""Tests for motor.common.utils.log_throttle."""

from __future__ import annotations

import threading
import time
import unittest

from motor.common.utils.log_throttle import IntervalLogThrottle, StateLogThrottle


class TestStateLogThrottle(unittest.TestCase):
    def test_first_call_always_logs(self) -> None:
        t = StateLogThrottle(heartbeat_seconds=60.0)
        should_log, suppressed = t.should_log(True)
        self.assertTrue(should_log)
        self.assertEqual(suppressed, 0)

    def test_same_state_repeats_suppressed(self) -> None:
        t = StateLogThrottle(heartbeat_seconds=60.0)
        t.should_log("bad")
        for _ in range(5):
            should_log, suppressed = t.should_log("bad")
            self.assertFalse(should_log)
        self.assertEqual(suppressed, 5)

    def test_state_transition_logs(self) -> None:
        t = StateLogThrottle(heartbeat_seconds=60.0)
        t.should_log("bad")
        t.should_log("bad")  # suppressed
        should_log, suppressed = t.should_log("good")
        self.assertTrue(should_log)
        self.assertEqual(suppressed, 1)

    def test_heartbeat_relogs_after_interval(self) -> None:
        t = StateLogThrottle(heartbeat_seconds=0.05)
        t.should_log("bad")
        self.assertFalse(t.should_log("bad")[0])
        time.sleep(0.08)
        should_log, _ = t.should_log("bad")
        self.assertTrue(should_log)

    def test_reset_returns_to_unset(self) -> None:
        t = StateLogThrottle(heartbeat_seconds=60.0)
        t.should_log("a")
        t.reset()
        # After reset, the very next call must log again (UNSET sentinel).
        should_log, _ = t.should_log("a")
        self.assertTrue(should_log)

    def test_invalid_heartbeat_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StateLogThrottle(heartbeat_seconds=0)
        with self.assertRaises(ValueError):
            StateLogThrottle(heartbeat_seconds=-1)

    def test_thread_safety(self) -> None:
        t = StateLogThrottle(heartbeat_seconds=60.0)
        results: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(100):
                ok, _ = t.should_log("x")
                with lock:
                    results.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        # Exactly one True overall (first-call transition); rest suppressed.
        self.assertEqual(sum(1 for r in results if r), 1)


class TestIntervalLogThrottle(unittest.TestCase):
    def test_first_call_logs(self) -> None:
        t = IntervalLogThrottle(interval_seconds=30.0)
        should_log, suppressed = t.should_log("k")
        self.assertTrue(should_log)
        self.assertEqual(suppressed, 0)

    def test_subsequent_calls_within_window_suppressed(self) -> None:
        t = IntervalLogThrottle(interval_seconds=30.0)
        t.should_log("k")
        for _ in range(4):
            ok, _ = t.should_log("k")
            self.assertFalse(ok)

    def test_window_elapse_allows_log(self) -> None:
        t = IntervalLogThrottle(interval_seconds=0.05)
        t.should_log("k")
        time.sleep(0.06)
        ok, suppressed = t.should_log("k")
        self.assertTrue(ok)
        # Suppressed count is reset on each successful log.
        self.assertEqual(suppressed, 0)

    def test_keys_are_independent(self) -> None:
        t = IntervalLogThrottle(interval_seconds=30.0)
        self.assertTrue(t.should_log("a")[0])
        self.assertTrue(t.should_log("b")[0])
        self.assertFalse(t.should_log("a")[0])

    def test_reset_specific_key(self) -> None:
        t = IntervalLogThrottle(interval_seconds=30.0)
        t.should_log("a")
        t.reset("a")
        self.assertTrue(t.should_log("a")[0])

    def test_reset_all(self) -> None:
        t = IntervalLogThrottle(interval_seconds=30.0)
        t.should_log("a")
        t.should_log("b")
        t.reset()
        self.assertTrue(t.should_log("a")[0])
        self.assertTrue(t.should_log("b")[0])

    def test_invalid_interval_rejected(self) -> None:
        with self.assertRaises(ValueError):
            IntervalLogThrottle(interval_seconds=0)
        with self.assertRaises(ValueError):
            IntervalLogThrottle(interval_seconds=-5)


if __name__ == "__main__":
    unittest.main()
