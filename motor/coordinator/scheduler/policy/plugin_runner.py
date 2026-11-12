# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Bounded external-policy execution with a killable subprocess and fail-open cooldown."""

import asyncio
import json
import math
import os
import signal
import sys
import time
from asyncio.subprocess import Process
from collections import Counter
from dataclasses import asdict

from motor.common.logger import get_logger
from motor.config.coordinator import PolicyPluginConfig
from motor.coordinator.scheduler.policy.api import CandidateId, RankedCandidate, SelectionInput
from motor.coordinator.scheduler.policy.plugin_worker import MAX_MESSAGE_BYTES

logger = get_logger(__name__)


class PolicyRunner:
    """One subprocess per configured inference worker, with no unbounded task queue."""

    def __init__(self, config: PolicyPluginConfig) -> None:
        self.config = config
        self._process: Process | None = None
        self._lock = asyncio.Lock()
        self._restart_task: asyncio.Task | None = None
        self._retry_after = 0.0
        self._closed = False
        self._counts: Counter = Counter()
        self._seconds = 0.0

    async def start(self) -> None:
        """Preload outside the request path. Load errors leave the built-in strategy active."""
        if self._closed or self._lock.locked() or self._process is not None or time.monotonic() < self._retry_after:
            return
        async with self._lock:
            try:
                self._process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    "import sys; stream = sys.stdout; sys.stdout = sys.stderr; "
                    "from motor.coordinator.scheduler.policy.plugin_worker import main; main(stream)",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    limit=MAX_MESSAGE_BYTES + 1,
                    start_new_session=True,
                )
                response = await asyncio.wait_for(
                    self._exchange({"name": self.config.name, "options": self.config.options}),
                    timeout=self.config.startup_timeout_ms / 1000,
                )
                if response.get("ready") is not True:
                    raise ValueError(response.get("error", "Missing plugin ready response"))
                self._counts["loads"] += 1
                logger.info("Scheduling plugin loaded name=%s api_version=1", self.config.name)
            except asyncio.CancelledError:
                await self._stop()
                raise
            except Exception as exc:
                self._counts["load_errors"] += 1
                await self._fail(exc)

    async def rank(self, selection: SelectionInput) -> tuple[RankedCandidate, ...] | None:
        """Return None to request the existing built-in policy, never wait behind another call."""
        if self._closed or self._lock.locked():
            self._counts["fallbacks"] += 1
            return None
        if self._process is None:
            if time.monotonic() >= self._retry_after and self._restart_task is None:
                self._restart_task = asyncio.create_task(self._restart())
            self._counts["fallbacks"] += 1
            return None
        async with self._lock:
            started = time.monotonic()
            self._counts["calls"] += 1
            try:
                payload = asdict(selection)
                payload["excluded"] = [asdict(item) for item in selection.excluded]
                response = await asyncio.wait_for(self._exchange(payload), timeout=self.config.timeout_ms / 1000)
                return self._validate(response, selection)
            except asyncio.CancelledError:
                # A late response must not be consumed by the next request.
                await self._stop()
                raise
            except Exception as exc:
                self._counts["timeouts" if isinstance(exc, asyncio.TimeoutError) else "errors"] += 1
                self._counts["fallbacks"] += 1
                await self._fail(exc)
                return None
            finally:
                self._seconds += time.monotonic() - started

    async def close(self) -> None:
        """Cancel recovery and reap the child during worker shutdown."""
        self._closed = True
        if self._restart_task is not None:
            self._restart_task.cancel()
            await asyncio.gather(self._restart_task, return_exceptions=True)
        # Interrupt an in-flight rank before waiting for its lock (its budget may be 60s).
        await self._stop()
        async with self._lock:
            await self._stop()

    def metrics_text(self) -> str:
        """Worker-local Prometheus counters; scrape every worker's metaserver."""
        label = '{policy=%s}' % json.dumps(self.config.name, ensure_ascii=False)
        lines = []
        for event in ("loads", "load_errors", "calls", "errors", "timeouts", "fallbacks"):
            name = "motor_policy_%s_total" % event
            lines.extend(("# TYPE %s counter" % name, "%s%s %s" % (name, label, self._counts[event])))
        lines.append("# TYPE motor_policy_selection_seconds summary")
        lines.append("motor_policy_selection_seconds_sum%s %s" % (label, self._seconds))
        lines.append("motor_policy_selection_seconds_count%s %s" % (label, self._counts["calls"]))
        return "\n".join(lines) + "\n"

    def record_fallback(self, reason: str) -> None:
        """Count core-side fallbacks that happen outside a plugin invocation."""
        self._counts["fallbacks"] += 1
        logger.warning("Scheduling plugin fallback name=%s reason=%s", self.config.name, reason)

    async def _exchange(self, payload: dict) -> dict:
        encoded = json.dumps(payload, allow_nan=False).encode("utf-8") + b"\n"
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise ValueError("Policy input exceeds message limit")
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("Policy process unavailable")
        process.stdin.write(encoded)
        await process.stdin.drain()
        line = await process.stdout.readline()
        if not line or len(line) > MAX_MESSAGE_BYTES:
            raise ValueError("Policy process exited or exceeded message limit")
        response = json.loads(line)
        if not isinstance(response, dict):
            raise ValueError("Policy response must be an object")
        return response

    @staticmethod
    def _validate(response: dict, selection: SelectionInput) -> tuple[RankedCandidate, ...]:
        raw = response.get("ranked")
        if not isinstance(raw, list) or not raw or len(raw) > len(selection.candidates):
            raise ValueError(response.get("error", "Empty or invalid policy ranking"))
        allowed = {item.id for item in selection.candidates} - selection.excluded
        seen = set()
        ranked = []
        for item in raw:
            candidate = CandidateId(**item["id"])
            score = item["score"]
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (candidate.instance_id, candidate.endpoint_id)
            ):
                raise ValueError("Policy candidate IDs must be integers")
            if candidate not in allowed or candidate in seen:
                raise ValueError("Unknown, excluded or duplicate candidate")
            if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score):
                raise ValueError("Policy score must be finite")
            seen.add(candidate)
            ranked.append(RankedCandidate(candidate, score))
        return tuple(ranked)

    async def _fail(self, exc: Exception) -> None:
        logger.warning(
            "Scheduling plugin failed name=%s reason=%s error=%s; falling back to configured built-in strategy",
            self.config.name,
            type(exc).__name__,
            str(exc)[:512],
        )
        self._retry_after = time.monotonic() + self.config.cooldown_seconds
        await self._stop()

    async def _stop(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await process.wait()

    async def _restart(self) -> None:
        try:
            await self.start()
        finally:
            self._restart_task = None
