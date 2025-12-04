# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import os
import asyncio
import threading
import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Request

from motor.controller.api_client import NodeManagerApiClient
from motor.common.utils.logger import get_logger, ApiAccessFilter
from motor.config.controller import ControllerConfig
from motor.common.resources.http_msg_spec import RegisterMsg, ReregisterMsg, HeartbeatMsg, TerminateInstanceMsg
from motor.controller.core import InstanceAssembler, InstanceManager
from motor.controller.api_server import probe_api, om_api


logger = get_logger(__name__)


def validate_cert_and_key(cert_path: str, key_path: str):
    for path, desc in [(cert_path, 'cert file'), (key_path, 'key file')]:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{desc} file is not exist: {path}")
        with open(path, 'r') as f:
            first_line = f.readline().strip()
            if not first_line.startswith('-----BEGIN'):
                raise ValueError(f"{desc} file format is nor correct: {path}")



class ControllerAPI:
    def __init__(self, config: ControllerConfig | None = None, host: str = None, port: int = None):
        if config is None:
            config = ControllerConfig()
        self.config = config
        self.host = host if host is not None else config.api_config.controller_api_host
        self.port = port if port is not None else config.api_config.controller_api_port
        self.server = None
        self.loop = None
        self.app = self._create_app()
        self.api_server_thread = None
        logger.info("ControllerAPI initialized.")
        
    def start(self) -> None:
        # Create API server thread
        self.api_server_thread = threading.Thread(
            target=self._run_api_server,
            daemon=True,
            name="APIServer"
        )
        self.api_server_thread.start()
        logger.info("ControllerAPI started.")

    def is_alive(self) -> bool:
        """Check if the API server thread is alive"""
        return self.api_server_thread is not None and self.api_server_thread.is_alive()

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

    def update_config(self, config: ControllerConfig) -> None:
        """Update configuration for the controller API"""
        # Note: API server configuration cannot be updated while running
        # Only update the config reference for future use
        self.config = config
        logger.info("ControllerAPI configuration updated (runtime changes may require restart)")

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        if self.config.tls_config.enable_tls:
            cert_path = self.config.tls_config.cert_path
            key_path = self.config.tls_config.key_path
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
            "/controller/terminate-instance": logging.INFO,
            "/v1/alarm/coordinator": logging.ERROR,
            "/startup": logging.ERROR,
            "/readiness": logging.ERROR,
            "/liveness": logging.ERROR
        }
        logging.getLogger("uvicorn.access").addFilter(ApiAccessFilter(api_filters))

        # Register routes
        POST_METHODS = ["POST"]
        app.add_api_route("/controller/heartbeat", self._heartbeat, methods=POST_METHODS)
        app.add_api_route("/controller/register", self._register, methods=POST_METHODS)
        app.add_api_route("/controller/reregister", self._reregister, methods=POST_METHODS)
        app.add_api_route("/controller/terminate_instance", self._terminate_instance, methods=["POST"])

        app.include_router(probe_api.router)
        app.include_router(om_api.router)

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
                cert_path = os.environ.get("CERT_PATH", self.config.tls_config.cert_path)
                key_path = os.environ.get("KEY_PATH", self.config.tls_config.key_path)
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

    async def _terminate_instance(self, request: Request) -> dict:
        body = await request.json()
        try:
            terminate_instance_msg = TerminateInstanceMsg(**body)
        except Exception as e:
            logger.error("Failed to parse TerminateInstanceMsg: %s, body: %s", e, body)
            return {"error": "Invalid TerminateInstanceMsg format"}
        logger.warning("Terminate instance, reason: %s", terminate_instance_msg.reason)
        instance = InstanceManager().get_instance(terminate_instance_msg.instance_id)

        if instance is None:
            logger.error("Instance %d not found.", terminate_instance_msg.instance_id)
            return {"error": "Instance not found"}

        for node_mgr in instance.get_node_managers():
            NodeManagerApiClient.stop(node_mgr)
        return {"result": "Terminate instance succeed!"}
