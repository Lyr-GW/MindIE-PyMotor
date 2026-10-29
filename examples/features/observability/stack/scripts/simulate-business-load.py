# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Send a bounded-rate stream of synthetic OpenAI-compatible chat requests."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:1027/v1/chat/completions")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", default="Summarize the role of a KV cache in one sentence.")
    parser.add_argument("--duration", type=float, default=60, help="Run duration in seconds (default: 60).")
    parser.add_argument("--rate", type=float, default=1, help="Requests per second, capped at 20 (default: 1).")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--unique-prefixes", action="store_true", help="Append a unique token to each prompt.")
    return parser.parse_args()


def _send_stream(url: str, model: str, prompt: str, max_tokens: int, timeout: float, api_key: str) -> None:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, data=payload, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"unexpected HTTP status {response.status}")
        for _ in response:
            pass


def main() -> int:
    args = _parse_args()
    if args.duration <= 0 or args.rate <= 0 or args.max_tokens <= 0 or args.timeout <= 0:
        print("duration, rate, max-tokens, and timeout must be positive", file=sys.stderr)
        return 2
    if args.rate > 20:
        print("rate is capped at 20 requests per second", file=sys.stderr)
        return 2

    deadline = time.monotonic() + args.duration
    interval = 1.0 / args.rate
    started = 0
    succeeded = 0
    failed = 0
    next_request = time.monotonic()
    api_key = os.getenv("MOTOR_API_KEY", "")
    while time.monotonic() < deadline:
        delay = next_request - time.monotonic()
        if delay > 0:
            time.sleep(min(delay, max(deadline - time.monotonic(), 0)))
        if time.monotonic() >= deadline:
            break
        started += 1
        try:
            prompt = args.prompt
            if args.unique_prefixes:
                prompt = f"{prompt}\nRequest token: {uuid4().hex}"
            request_timeout = min(args.timeout, max(deadline - time.monotonic(), 0.1))
            _send_stream(args.url, args.model, prompt, args.max_tokens, request_timeout, api_key)
            succeeded += 1
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            failed += 1
            print(f"request {started} failed: {exc}", file=sys.stderr)
        next_request += interval
        next_request = max(next_request, time.monotonic())

    print(f"requests={started} succeeded={succeeded} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
