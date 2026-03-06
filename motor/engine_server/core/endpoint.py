# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

import threading
from typing import Any

from fastapi import FastAPI, Response
import uvicorn
import prometheus_client
import regex as re
from prometheus_client import CollectorRegistry, multiprocess, make_asgi_app, generate_latest, CONTENT_TYPE_LATEST
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.routing import Mount

from motor.common.utils.cert_util import CertUtil
from motor.engine_server.core.health_collector import HealthCollector
from motor.engine_server.constants.constants import STATUS_INTERFACE, STATUS_KEY, INIT_STATUS, NORMAL_STATUS, \
    ABNORMAL_STATUS
from motor.engine_server.config.base import IConfig
from motor.common.utils.logger import get_logger

logger = get_logger("engine_server")


class PrometheusResponse(Response):
    media_type = prometheus_client.CONTENT_TYPE_LATEST


def attach_metrics_router(app: FastAPI):
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)

    Instrumentator(
        excluded_handlers=[
            "/metrics",
            "/status",
        ],
        registry=registry,
    ).add().instrument(app).expose(app, response_class=PrometheusResponse)

    metrics_route = Mount("/metrics", make_asgi_app(registry=registry))

    metrics_route.path_regex = re.compile("^/metrics(?P<path>.*)$")
    app.routes.append(metrics_route)
    logger.info(f"Created Endpoint metrics route: /metrics successfully")


class Endpoint:
    def __init__(self, config: IConfig):
        self.host = config.get_server_config().server_host
        self.port = config.get_server_config().server_port
        self.mgmt_tls_config = config.get_server_config().deploy_config.mgmt_tls_config
        self.app = FastAPI(title="EngineServer Endpoint")
        attach_metrics_router(self.app)
        self._stop_event = threading.Event()
        self._server_core = None
        self._server: uvicorn.Server | None = None
        self._server_thread = threading.Thread(
            target=self._run_server,
            name="endpoint_server_thread",
            daemon=True
        )
        self.health_collector = HealthCollector(config)
        self.attach_status_router()

    def run(self):
        if self._server_thread and not self._server_thread.is_alive():
            self._server_thread.start()
            logger.info(f"Endpoint server started: http://{self.host}:{self.port}")

    def shutdown(self):
        if self._server:
            self._server.should_exit = True
            logger.info("Endpoint: Uvicorn server exit triggered")
        self._stop_event.set()
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5)
            log_msg = "exited" if not self._server_thread.is_alive() else "timeout"
            logger.info(f"Endpoint server thread {log_msg}")
        logger.info("Endpoint server stopped completely")

    def set_server_core(self, server_core):
        self._server_core = server_core

    def attach_status_router(self):
        @self.app.get(STATUS_INTERFACE)
        async def get_status(response: Response) -> dict[str, Any]:
            response.status_code = 200
            try:
                is_healthy = await self.health_collector.is_healthy()
                if is_healthy:
                    return {STATUS_KEY: NORMAL_STATUS}
                return {STATUS_KEY: ABNORMAL_STATUS}
            except Exception:
                return {STATUS_KEY: INIT_STATUS}

    def _run_server(self):
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            workers=1,
        )

        config.load()
        if self.mgmt_tls_config and self.mgmt_tls_config.enable_tls:
            ssl_context = CertUtil.create_ssl_context(self.mgmt_tls_config)
            if ssl_context:
                config.ssl = ssl_context
            else:
                raise RuntimeError("Failed to create ssl context")
            logger.info(f"Endpoint server started: https://{self.host}:{self.port}")
        else:
            logger.info(f"Endpoint server started: http://{self.host}:{self.port}")

        self._server = uvicorn.Server(config)
        if not self._stop_event.is_set():
            self._server.run()
