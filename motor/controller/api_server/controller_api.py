# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import os
import asyncio
import threading
import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Request

from motor.utils.logger import get_logger
from motor.config.controller import ControllerConfig
from motor.resources.http_msg_spec import RegisterMsg, ReregisterMsg, HeartbeatMsg
from motor.controller.core.instance_assembler import InstanceAssembler
from motor.controller.core.instance_manager import InstanceManager


logger = get_logger(__name__)


def validate_cert_and_key(cert_path: str, key_path: str):
    for path, desc in [(cert_path, 'cert file'), (key_path, 'key file')]:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{desc} file is not exist: {path}")
        with open(path, 'r') as f:
            first_line = f.readline().strip()
            if not first_line.startswith('-----BEGIN'):
                raise ValueError(f"{desc} file format is nor correct: {path}")


class ApiAccessFilter(logging.Filter):
    """Suppress uvicorn access logs for specified APIs unless level >= configured level."""

    def __init__(self, api_filters: dict[str, int] = None):
        """
        Args:
            api_filters: dict mapping API paths to minimum log levels.
                        e.g., {"/heartbeat": logging.ERROR, "/register": logging.WARNING}
        """
        super().__init__()
        self.api_filters = api_filters or {}

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if record.name == "uvicorn.access":
            for path, min_level in self.api_filters.items():
                if path in message:
                    return record.levelno >= min_level
        return True


class ControllerAPI:
    def __init__(self, config: ControllerConfig | None = None, host: str = None, port: int = None):
        if config is None:
            config = ControllerConfig()
        self.config = config
        self.host = host if host is not None else config.controller_api_host
        self.port = port if port is not None else config.controller_api_port
        self.server = None
        self.loop = None
        self.app = self._create_app()
        self.api_server_thread = threading.Thread(
            target=self._run_api_server,
            daemon=True,
            name="APIServer"
        )
        logger.info("ControllerAPI initialized.")
        
    def start(self) -> None:
        self.api_server_thread.start()
        logger.info("ControllerAPI started.")

    def stop(self) -> None:
        if self.server and self.loop:
            try:
                future = asyncio.run_coroutine_threadsafe(self.server.shutdown(), self.loop)
                future.result(timeout=3)
                logger.info("API server stopped gracefully")
            except Exception as e:
                logger.error("Error stopping server: %s", e)
                if self.loop and not self.loop.is_closed():
                    self.loop.call_soon_threadsafe(self.loop.stop)

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        if self.config.enable_tls:
            cert_path = self.config.cert_path
            key_path = self.config.key_path
            try:
                validate_cert_and_key(cert_path, key_path)
                logger.info("Cert and key validate pass: %s, %s", cert_path, key_path)
            except Exception as e:
                logger.error("Cert or key validate failed: %s", e)
                raise
        logger.info("API server startup started")
        yield
        logger.info("API server shutdown completed")

    def _create_app(self) -> FastAPI:
        app = FastAPI(lifespan=self._lifespan)

        # Apply filter to suppress access logs for specified APIs unless level >= configured level
        api_filters = {
            "/controller/heartbeat": logging.ERROR,
            "/controller/register": logging.INFO,
            "/controller/reregister": logging.INFO,
        }
        logging.getLogger("uvicorn.access").addFilter(ApiAccessFilter(api_filters))

        # Register routes
        POST_METHODS = ["POST"]
        app.add_api_route("/controller/heartbeat", self._heartbeat, methods=POST_METHODS)
        app.add_api_route("/controller/register", self._register, methods=POST_METHODS)
        app.add_api_route("/controller/reregister", self._reregister, methods=POST_METHODS)

        return app

    async def _heartbeat(self, request: Request):
        body = await request.json()
        try:
            hb_msg = HeartbeatMsg(**body)
        except Exception as e:
            logger.error("Failed to parse HeartbeatMsg: %s, body: %s", e, body)
            return {"error": "Invalid HeartbeatMsg format"}
        ret = InstanceManager().handle_heartbeat(hb_msg)
        return {"result": ret}

    async def _register(self, request: Request) -> dict:
        body = await request.json()
        try:
            register_msg = RegisterMsg(**body)
        except Exception as e:
            logger.error("Failed to parse RegisterMsg: %s, body: %s", e, body)
            return {"error": "Invalid RegisterMsg format"}
        ret = InstanceAssembler().register(register_msg)
        if ret == -1:
            return {"error": "Instance already registered"}
        else:
            return {"result": ret}

    async def _reregister(self, request: Request) -> dict:
        body = await request.json()
        try:
            reregister_msg = ReregisterMsg(**body)
        except Exception as e:
            logger.error("Failed to parse ReregisterMsg: %s, body: %s", e, body)
            return {"error": "Invalid ReregisterMsg format"}
        ret = InstanceAssembler().reregister(reregister_msg)
        if ret == -1:
            return {"error": "Instance already registered"}
        else:
            return {"result": ret}
    
    def _run_api_server(self) -> None:
        try:
            enable_tls = os.environ.get("ENABLE_TLS", "0").lower() in ("1", "true", "yes")
            logger.info("Starting API server on %s:%d TLS=%s", self.host, self.port, enable_tls)
            if enable_tls:
                cert_path = os.environ.get("CERT_PATH", self.config.controller_api_cert_path)
                key_path = os.environ.get("KEY_PATH", self.config.controller_api_key_path)
                server_config = uvicorn.Config(
                    self.app,
                    host=self.host, 
                    port=self.port, 
                    log_level="info", 
                    ssl_certfile=cert_path, 
                    ssl_keyfile=key_path
                )
            else:
                server_config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
            self.server = uvicorn.Server(server_config)
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.server.serve())
        except Exception as e:
            logger.error("API server error: %s", e)
        finally:
            if self.loop and not self.loop.is_closed():
                self.loop.close()
