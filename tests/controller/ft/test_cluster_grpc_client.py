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

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
import sys
import grpc

# mock pb
mock_pb2 = MagicMock()
mock_pb2_grpc = MagicMock()
mock_pb2.ClientInfo = Mock
mock_pb2.FaultMsgSignal = Mock
# add cluster pb to system
sys.modules['cluster_fault_pb2'] = mock_pb2
sys.modules['cluster_fault_pb2_grpc'] = mock_pb2_grpc

from motor.controller.ft.cluster_grpc.cluster_grpc_client import ClusterNodeClient


class TestClusterNodeClient:
    @pytest.fixture
    def client(self):
        """create a mock ClusterNodeClient"""
        return ClusterNodeClient(
            host="localhost",
            port="50051",
            is_ssl_secure=False
        )

    @pytest.fixture
    def ssl_client(self):
        """create a mock ClusterNodeClient with SSL enabled"""
        return ClusterNodeClient(
            host="localhost",
            port="50051",
            is_ssl_secure=True
        )

    @pytest.fixture
    def mock_channel_insecure(self):
        """mock grpc insecure channel"""
        with patch('motor.controller.ft.cluster_grpc.cluster_grpc_client.ClusterNodeClient.create_insecure_channel') as mock:
            mock_channel = MagicMock()
            mock.return_value = mock_channel
            yield mock_channel

    @pytest.fixture
    def mock_channel_secure(self):
        """mock grpc secure channel"""
        with patch('motor.controller.ft.cluster_grpc.cluster_grpc_client.GrpcSecureClientBase.create_secure_channel') as mock:
            mock_channel = MagicMock()
            mock.return_value = mock_channel
            yield mock_channel

    @pytest.fixture
    def mock_stub_insecure(self, mock_channel_insecure):
        """mock grpc stub for insecure connection"""
        with patch('motor.controller.ft.cluster_grpc.cluster_grpc_client.cluster_fault_pb2_grpc.FaultStub') as mock:
            mock_stub = MagicMock()
            mock.return_value = mock_stub
            yield mock_stub

    @pytest.fixture
    def mock_stub_secure(self, mock_channel_secure):
        """mock grpc stub for secure connection"""
        with patch('motor.controller.ft.cluster_grpc.cluster_grpc_client.cluster_fault_pb2_grpc.FaultStub') as mock:
            mock_stub = MagicMock()
            mock.return_value = mock_stub
            yield mock_stub

    def test_init(self, client):
        """test client init"""
        assert client._host == "localhost"
        assert client._port == "50051"
        assert client._stub is None
        assert client._register_status is False
        assert client._job_id == os.getenv("MINDX_TASK_ID", "")
        assert client._role == "controller"
        assert client._channel is None

    def test_connect_success(self, client, mock_channel_insecure, mock_stub_insecure):
        """test connect success"""
        # exec connect
        client.connect()

        assert client._channel == mock_channel_insecure
        assert client._stub == mock_stub_insecure

        # For non-SSL client, should call create_insecure_channel
        client.create_insecure_channel.assert_called_once()
        call_args = client.create_insecure_channel.call_args
        options = call_args[1]['options']

        expected_options = [
            ('grpc.ssl_target_name_override', 'cluster_fault_client'),
            ('grpc.max_receive_message_length', 100 * 1024 * 1024),
            ('grpc.keepalive_time_ms', 10000),
            ('grpc.keepalive_timeout_ms', 50000),
            # add connection timeout settings
            ('grpc.initial_reconnect_backoff_ms', 1000),
            ('grpc.max_reconnect_backoff_ms', 10000),
            ('grpc.enable_retries', 1),
            ('grpc.max_retry_attempts', 3),
        ]
        assert options == expected_options

    def test_connect_failure(self, client):
        """test connect failure"""
        # mock connect exception based on SSL setting
        if client._is_ssl_secure:
            patch_target = 'motor.controller.ft.cluster_grpc.cluster_grpc_client.GrpcSecureClientBase.create_secure_channel'
        else:
            patch_target = 'motor.controller.ft.cluster_grpc.cluster_grpc_client.ClusterNodeClient.create_insecure_channel'

        with patch(patch_target) as mock:
            mock.side_effect = Exception("Connection failed")

            with pytest.raises(Exception, match="Connection failed"):
                client.connect()

            assert client._stub is None
            assert client._channel is None

    def test_register_success(self, client, mock_channel_insecure, mock_stub_insecure):
        """test register success"""
        # mock server response success
        mock_response = Mock()
        mock_response.code = 0
        mock_response.info = "Registration successful"
        mock_stub_insecure.Register.return_value = mock_response

        result = client.register()
        # verify
        assert result is True
        assert client._register_status is True
        mock_stub_insecure.Register.assert_called_once()

        # verify Register parameter
        call_args = mock_stub_insecure.Register.call_args
        client_info = call_args[0][0]
        assert client_info.jobId == client._job_id
        assert client_info.role == client._role

    def test_register_server_error(self, client, mock_channel_insecure, mock_stub_insecure):
        """test register server error"""
        # mock register response fail
        mock_response = Mock()
        mock_response.code = 1
        mock_response.info = "Registration failed"
        mock_stub_insecure.Register.return_value = mock_response

        result = client.register()
        # verify
        assert result is False
        assert client._register_status is False
        mock_stub_insecure.Register.assert_called_once()

    def test_register_grpc_exception(self, client, mock_channel_insecure, mock_stub_insecure):
        """test register grpc exception"""
        # mock grpc error with proper attributes
        mock_error = grpc.RpcError("gRPC error")
        mock_error.code = lambda: grpc.StatusCode.UNAVAILABLE
        mock_error.details = lambda: "Connection failed"
        mock_stub_insecure.Register.side_effect = mock_error

        # exec register
        result = client.register()

        # verify
        assert result is False
        assert client._register_status is False

    def test_register_already_registered(self, client, mock_channel_insecure, mock_stub_insecure):
        """test register already registered"""
        # set register status
        client._register_status = True

        # exec register
        result = client.register()

        # verify register
        assert result is True
        mock_stub_insecure.Register.assert_not_called()

    def test_subscribe_fault_messages_success(self, client, mock_stub_insecure):
        """test subscribe_fault_messages success"""
        # set register status
        client._register_status = True
        client._stub = mock_stub_insecure

        # mock subscribe response message stream (list of messages)
        mock_fault_msg = Mock()
        mock_stub_insecure.SubscribeFaultMsgSignal.return_value = [mock_fault_msg]

        mock_callback = Mock()
        client.subscribe_fault_messages(callback=mock_callback)

        mock_stub_insecure.SubscribeFaultMsgSignal.assert_called_once()
        mock_callback.assert_called_once_with(mock_fault_msg)
        # verify parameter
        call_args = mock_stub_insecure.SubscribeFaultMsgSignal.call_args
        client_info = call_args[0][0]
        assert client_info.jobId == client._job_id
        assert client_info.role == client._role

    def test_subscribe_fault_messages_not_registered(self, client):
        """test subscribe_fault_messages not registered"""
        # set register status
        client._register_status = False

        client.subscribe_fault_messages()

    def test_subscribe_fault_messages_exception(self, client, mock_stub_insecure):
        """test subscribe_fault_messages exception"""
        # set register status
        client._register_status = True
        client._stub = mock_stub_insecure

        # mock gRPC Exception
        mock_stub_insecure.SubscribeFaultMsgSignal.side_effect = Exception("Subscription failed")

        # verify
        with pytest.raises(Exception, match="Subscription failed"):
            client.subscribe_fault_messages()

    def test_subscribe_fault_messages_no_callback(self, client, mock_stub_insecure):
        """test subscribe_fault_messages no callback"""
        # set register status
        client._register_status = True
        client._stub = mock_stub_insecure

        # mock Subscribe response message stream
        mock_fault_msg = Mock()
        mock_stub_insecure.SubscribeFaultMsgSignal.return_value = [mock_fault_msg]

        client.subscribe_fault_messages()
        mock_stub_insecure.SubscribeFaultMsgSignal.assert_called_once()

    def test_close_success(self, client, mock_channel_insecure):
        """test close success"""
        # set register status
        client._register_status = True
        client._channel = mock_channel_insecure

        # exec close
        client.close()

        # verify
        mock_channel_insecure.close.assert_called_once()
        assert client._register_status is False

    def test_close_not_registered(self, client):
        """test close not registered"""
        # set register status
        client._register_status = False
        client.close()

        # verify
        assert client._register_status is False

    def test_close_no_channel(self, client):
        """test close not registered"""
        # set register status
        client._register_status = True
        client._channel = None
        client.close()

        # verify
        assert client._register_status is False