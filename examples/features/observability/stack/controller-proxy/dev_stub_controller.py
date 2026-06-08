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

"""
本地联调用的 **Controller 指标接口** 桩 (stub)。

仅用于离线验证 controller-metrics-proxy → Prometheus → Grafana 链路，
不依赖完整 pyMotor 集群。它在 :1027/observability/metrics 上返回与真实
Controller **完全相同的 JSON 信封**：

    {"code": 200, "message": "Success", "data": "<Prometheus 文本>"}

``data`` 内的指标取自 ``tests/coordinator/core/metrics_example.txt``（真实
Engine /metrics 抓取样本），并追加 Coordinator 聚合的 ``motor_*`` gauge；
计数器会随时间单调递增、gauge 轻微抖动，使 Grafana 面板呈现动态曲线。

用法：
    python dev_stub_controller.py                 # 默认 :1027
    SAMPLE_FILE=/path/to/metrics_example.txt python dev_stub_controller.py
    STUB_PORT=1027 python dev_stub_controller.py

随后让 proxy 指向它（默认即 host.docker.internal:1027）并启动观测栈即可。
"""

import json
import math
import os
import random
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_DEFAULT_SAMPLE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "..", "tests", "coordinator", "core", "metrics_example.txt",
)
SAMPLE_FILE = os.environ.get("SAMPLE_FILE", os.path.normpath(_DEFAULT_SAMPLE))
PORT = int(os.environ.get("STUB_PORT", "1027"))

# 当样本文件缺失时使用的最小内置样本，保证脚本独立可跑。
_FALLBACK_SAMPLE = """# HELP vllm:num_requests_running Number of requests in model execution batches.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="demo"} 0.0
# HELP vllm:num_requests_waiting Number of requests waiting to be processed.
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting{engine="0",model_name="demo"} 0.0
# HELP vllm:kv_cache_usage_perc KV-cache usage. 1 means 100 percent usage.
# TYPE vllm:kv_cache_usage_perc gauge
vllm:kv_cache_usage_perc{engine="0",model_name="demo"} 0.0
# HELP vllm:prompt_tokens_total Number of prefill tokens processed.
# TYPE vllm:prompt_tokens_total counter
vllm:prompt_tokens_total{engine="0",model_name="demo"} 1000.0
# HELP vllm:generation_tokens_total Number of generation tokens processed.
# TYPE vllm:generation_tokens_total counter
vllm:generation_tokens_total{engine="0",model_name="demo"} 2000.0
"""

if os.path.isfile(SAMPLE_FILE):
    with open(SAMPLE_FILE, "r", encoding="utf-8") as fh:
        RAW_LINES = fh.read().splitlines()
    _src = SAMPLE_FILE
else:
    RAW_LINES = _FALLBACK_SAMPLE.splitlines()
    _src = "<builtin fallback sample>"

_TYPE_RE = re.compile(r"^#\s*TYPE\s+(\S+)\s+(\S+)")
_SAMPLE_RE = re.compile(r"^([^#\s][^\s{]*)(\{[^}]*\})?\s+([0-9eE.+\-]+)(\s+\d+)?$")

_metric_types = {}
for _ln in RAW_LINES:
    _m = _TYPE_RE.match(_ln)
    if _m:
        _metric_types[_m.group(1)] = _m.group(2)

_START = time.time()
_counter_state = {}


def _evolve(name, labels, base, t):
    mtype = _metric_types.get(name, "untyped")
    key = name + (labels or "")
    if mtype == "counter":
        rate = max(base * 0.0005, 0.05)
        cur = _counter_state.get(key, base)
        cur += rate * (1.0 + 0.4 * math.sin(t / 20.0)) * random.uniform(0.5, 1.5)
        _counter_state[key] = cur
        return cur
    if mtype == "gauge":
        if base == 0:
            if "num_requests" in name or "usage" in name:
                return max(0.0, 4 + 4 * math.sin(t / 15.0) + random.uniform(-1, 1))
            return 0.0
        amp = abs(base) * 0.12
        return base + amp * math.sin(t / 18.0) + random.uniform(-amp * 0.3, amp * 0.3)
    return base


def _render_prom_text() -> str:
    t = time.time() - _START
    out = []
    for ln in RAW_LINES:
        m = _SAMPLE_RE.match(ln)
        if not m:
            out.append(ln)
            continue
        name, labels, val = m.group(1), m.group(2) or "", m.group(3)
        try:
            base = float(val)
        except ValueError:
            out.append(ln)
            continue
        out.append(f"{name}{labels} {_evolve(name, labels, base, t)}")
    out += [
        "# HELP motor_active_prefill_workers Number of active prefill workers.",
        "# TYPE motor_active_prefill_workers gauge",
        f"motor_active_prefill_workers {2 if math.sin(t / 30) > -0.9 else 1}",
        "# HELP motor_active_decode_workers Number of active decode workers.",
        "# TYPE motor_active_decode_workers gauge",
        f"motor_active_decode_workers {4 if math.sin(t / 25) > -0.8 else 3}",
        "# HELP motor_inactive_prefill_workers Number of inactive prefill workers.",
        "# TYPE motor_inactive_prefill_workers gauge",
        "motor_inactive_prefill_workers 0",
        "# HELP motor_inactive_decode_workers Number of inactive decode workers.",
        "# TYPE motor_inactive_decode_workers gauge",
        "motor_inactive_decode_workers 0",
        "",
    ]
    return "\n".join(out)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        if path == "/observability/metrics":
            payload = json.dumps(
                {"code": 200, "message": "Success", "data": _render_prom_text()}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif path in ("/observability/inventory", "/observability/alarms"):
            payload = json.dumps({"code": 200, "message": "Success", "data": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    print(
        f"[dev_stub_controller] serving Controller JSON envelope on "
        f":{PORT}/observability/metrics  (sample={_src}, {len(_metric_types)} typed metrics)"
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), _Handler).serve_forever()
