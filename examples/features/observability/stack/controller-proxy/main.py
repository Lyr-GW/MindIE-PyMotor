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
controller-metrics-proxy
=========================

pyMotor 的 Controller 把可观测性指标通过 ``GET /observability/metrics`` 暴露，
但返回的是 **JSON 信封**（``{"code":200,"message":"Success","data":"<Prometheus 文本>"}``），
而非原生 Prometheus exposition 格式。Prometheus 直接抓取该端点会因解析失败而把
target 标记为 DOWN。

本适配器作为一个轻量级 sidecar exporter：

1. 周期性（或在被抓取时）请求 Controller 的 ``/observability/metrics`` JSON 端点；
2. 取出 ``data`` 字段中的 Prometheus 文本；
3. 以标准 ``text/plain; version=0.0.4`` 形式在 ``/metrics`` 上重新暴露，
   供 Prometheus 正常抓取，从而让 Grafana 接入 Controller 指标接口。

额外注入若干自监控指标（``motor_controller_proxy_*``），便于排障。

仅依赖 Python 标准库，无第三方依赖。
"""

import json
import logging
import os
import ssl
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError

PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    def __init__(self) -> None:
        self.controller_url = os.environ.get(
            "CONTROLLER_METRICS_URL",
            "http://host.docker.internal:1027/observability/metrics",
        )
        self.port = int(os.environ.get("PROXY_PORT", "9106"))
        self.timeout = float(os.environ.get("CONTROLLER_TIMEOUT", "5"))
        # JSON 信封中承载 Prometheus 文本的字段名（pyMotor 默认 "data"）。
        self.json_data_key = os.environ.get("JSON_DATA_KEY", "data")
        # 与 Controller 建立 https 时是否跳过证书校验（自签名场景）。
        self.insecure_skip_verify = _get_bool("INSECURE_SKIP_VERIFY", True)
        # 可选 mTLS：访问启用 TLS 的 Controller observability 端口时使用。
        self.ca_file = os.environ.get("CA_FILE") or None
        self.cert_file = os.environ.get("CERT_FILE") or None
        self.key_file = os.environ.get("KEY_FILE") or None
        self.log_level = os.environ.get("PROXY_LOG_LEVEL", "INFO").upper()


class ControllerClient:
    """拉取 Controller 的 JSON 指标并解包为 Prometheus 文本。"""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._ssl_context = self._build_ssl_context()

    def _build_ssl_context(self):
        if not self._config.controller_url.lower().startswith("https"):
            return None
        ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        if self._config.ca_file:
            ctx.load_verify_locations(cafile=self._config.ca_file)
        if self._config.cert_file and self._config.key_file:
            ctx.load_cert_chain(certfile=self._config.cert_file, keyfile=self._config.key_file)
        if self._config.insecure_skip_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def fetch(self) -> str:
        """返回解包后的 Prometheus 文本；失败时抛出异常。"""
        req = urllib.request.Request(
            self._config.controller_url,
            headers={"Accept": "application/json", "User-Agent": "controller-metrics-proxy/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self._config.timeout, context=self._ssl_context) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        return self._unwrap(raw)

    def _unwrap(self, raw: str) -> str:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # 已经是纯文本（例如用户直接指向 coordinator /metrics），原样透传。
            return raw

        if not isinstance(payload, dict):
            return raw

        key = self._config.json_data_key
        data = payload.get(key, "")
        code = payload.get("code")
        if code is not None and int(code) != 200:
            message = payload.get("message", "")
            raise RuntimeError(f"controller returned code={code} message={message!r}")
        if not isinstance(data, str):
            # data 可能是 dict（例如未启用可观测性时返回 {}），无指标可暴露。
            return ""
        return data


class MetricsHandler(BaseHTTPRequestHandler):
    client: ControllerClient = None  # 由 main() 注入
    config: Config = None

    def log_message(self, fmt, *args):  # noqa: N802 静默默认 access log
        logging.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/healthz", "/-/healthy"):
            self._respond(200, "ok\n", "text/plain; charset=utf-8")
            return
        if self.path.split("?")[0].rstrip("/") not in ("/metrics", ""):
            self._respond(404, "not found\n", "text/plain; charset=utf-8")
            return

        start = time.monotonic()
        up = 1
        body = ""
        try:
            body = self.client.fetch()
        except (HTTPError, URLError, RuntimeError, ValueError, OSError) as exc:
            up = 0
            logging.warning("failed to scrape controller %s: %s", self.config.controller_url, exc)

        duration = time.monotonic() - start
        body += self._self_metrics(up, duration)
        self._respond(200, body, PROM_CONTENT_TYPE)

    def _self_metrics(self, up: int, duration: float) -> str:
        url = self.config.controller_url.replace("\\", "\\\\").replace('"', '\\"')
        lines = [
            "",
            "# HELP motor_controller_proxy_up Whether the last scrape of the controller observability endpoint succeeded.",
            "# TYPE motor_controller_proxy_up gauge",
            f'motor_controller_proxy_up{{controller_url="{url}"}} {up}',
            "# HELP motor_controller_proxy_scrape_duration_seconds Duration of the last controller scrape.",
            "# TYPE motor_controller_proxy_scrape_duration_seconds gauge",
            f'motor_controller_proxy_scrape_duration_seconds{{controller_url="{url}"}} {duration:.6f}',
            "",
        ]
        return "\n".join(lines)

    def _respond(self, status: int, body: str, content_type: str):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    config = Config()
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] controller-proxy: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.info(
        "starting controller-metrics-proxy: upstream=%s listen=:%d timeout=%.1fs json_data_key=%s",
        config.controller_url,
        config.port,
        config.timeout,
        config.json_data_key,
    )

    MetricsHandler.client = ControllerClient(config)
    MetricsHandler.config = config

    server = ThreadingHTTPServer(("0.0.0.0", config.port), MetricsHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
