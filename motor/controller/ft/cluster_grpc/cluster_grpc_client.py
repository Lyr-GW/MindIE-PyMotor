# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import os
from typing import Callable
import grpc

from motor.controller.ft.cluster_grpc import cluster_fault_pb2
from motor.controller.ft.cluster_grpc import cluster_fault_pb2_grpc
from motor.common.utils.grpc_connect_base import GrpcSecureClientBase
from motor.common.utils.logger import get_logger


logger = get_logger(__name__)

REGISTER_TIMEOUT = 30  # seconds


class ClusterNodeClient(GrpcSecureClientBase):
    def __init__(
        self,
        host: str,
        port: str,
        is_ssl_secure: bool = False,
        root_cert: str = None,
        cert_file: str = None,
        key_file: str = None
    ):
        super().__init__(
            host=host,
            port=port,
            is_ssl_secure=is_ssl_secure,
            root_cert=root_cert,
            cert_file=cert_file,
            key_file=key_file,
        )
        self._stub = None
        self._register_status = False
        self._job_id = os.getenv("MINDX_TASK_ID", "")
        self._role = "controller"
        self._channel = None

    def create_insecure_channel(self, options: list = None):
        """create insecure channel for non-SSL connections"""
        try:
            channel = grpc.insecure_channel(
                f'{self._host}:{self._port}',
                options=options
            )
            return channel
        except Exception as e:
            raise Exception("Failed to create insecure channel.") from e

    def connect(self):
        """connect to grpc server"""
        try:
            # set options config
            options = [
                ('grpc.ssl_target_name_override', 'cluster_fault_client'),
                ('grpc.max_receive_message_length', 100 * 1024 * 1024),
                ('grpc.keepalive_time_ms', 10000),
                ('grpc.keepalive_timeout_ms', 50000),
                ('grpc.initial_reconnect_backoff_ms', 1000),
                ('grpc.max_reconnect_backoff_ms', 10000),
                ('grpc.enable_retries', 1),
                ('grpc.max_retry_attempts', 3),
            ]

            if self._is_ssl_secure:
                self._channel = self.create_secure_channel(options=options)
            else:
                # For non-SSL connections, create insecure channel
                self._channel = self.create_insecure_channel(options=options)

            self._stub = cluster_fault_pb2_grpc.FaultStub(self._channel)
            # only create channel and stub, actual connection test is in register method
            logger.debug("gRPC channel and stub created for %s:%s (SSL: %s)", 
                         self._host, self._port, self._is_ssl_secure)

        except Exception as e:
            logger.error("connect server fail: %s", e)
            raise

    def register(self) -> bool:
        """register job"""
        if self._register_status:
            return True

        try:
            self.connect()
            client_info = cluster_fault_pb2.ClientInfo(jobId=self._job_id, role=self._role)
            # use timeout parameter directly passed to stub method, compatible with grpcio 1.76
            response = self._stub.Register(client_info, timeout=REGISTER_TIMEOUT)

            if response.code != 0:
                self._register_status = False
                logger.error("register fail: %s", response.info)
                return False

            logger.info("connect server success, %s:%s", self._host, self._port)
            logger.info("%s/%s register success: %s", self._job_id, self._role, response.info)
            self._register_status = True
            return True
        except grpc.RpcError as e:
            self._register_status = False
            # More precise gRPC error handling
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                logger.warning(
                    "register timeout: failed to connect to cluster server "
                    "%s:%s, will retry later." % (self._host, self._port)
                )
            elif e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                logger.warning("register timeout: request exceeded %s s timeout", REGISTER_TIMEOUT)
            else:
                logger.error("register call grpc error: %s - %s", e.code(), e.details())
            return False
        except Exception as e:
            self._register_status = False
            logger.error("register call unexpected error: %s.", e)
            return False

    def subscribe_fault_messages(
        self,
        callback: Callable[[cluster_fault_pb2.FaultMsgSignal], None] = None
    ):
        """subscribe fault messages"""
        if not self._register_status:
            logger.warning("must register before subscribing.")
            return

        try:
            client_info = cluster_fault_pb2.ClientInfo(jobId=self._job_id, role=self._role)
            logger.info("starting fault message subscription for job %s", self._job_id)
            fault_messages_stream = self._stub.SubscribeFaultMsgSignal(client_info)
            if callback is not None:
                # Iterate through the stream and call callback for each message
                for fault_msg in fault_messages_stream:
                    callback(fault_msg)
        except grpc.RpcError as e:
            logger.error("gRPC error in fault message subscription: %s - %s", e.code(), e.details())
            raise
        except Exception as e:
            logger.error("unexpected error in fault message subscription: %s", e)
            raise

    def is_registered(self) -> bool:
        """check if registered"""
        return self._register_status

    def close(self):
        """close grpc channel"""
        if self._register_status:
            self._register_status = False
        if self._channel:
            self._channel.close()
        logger.info("close server connect success.")