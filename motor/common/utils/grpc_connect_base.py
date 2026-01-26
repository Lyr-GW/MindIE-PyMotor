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

import grpc


class GrpcSecureClientBase:
    def __init__(self, host: str, port: str, is_ssl_secure: bool = False,
                 root_cert: str = None, cert_file: str = None, key_file: str = None):
        self._host = host
        self._port = port
        self._is_ssl_secure = is_ssl_secure
        self._root_cert = root_cert
        self._cert_file = cert_file
        self._key_file = key_file

    def create_secure_channel(self, options: list = None):
        """create secure channel"""
        try:
            channel = grpc.secure_channel(
                f'{self._host}:{self._port}',
                self._load_ssl_credentials(),
                options=options
            )
            return channel
        except Exception as e:
            raise Exception("Failed to create secure channel.") from e

    def connect(self):
        """connect to grpc server"""
        raise NotImplementedError

    def _load_ssl_credentials(self):
        """load ssl certificate and key file"""
        try:
            if self._is_ssl_secure:
                with open(self._root_cert, 'rb') as f:
                    private_key = f.read()
                with open(self._cert_file, 'rb') as f:
                    certificate_chain = f.read()
                with open(self._key_file, 'rb') as f:
                    root_certificates = f.read()

                # create ssl credentials channel
                client_credentials = grpc.ssl_channel_credentials(
                    root_certificates=root_certificates, 
                    private_key=private_key, 
                    certificate_chain=certificate_chain)
            else:
                client_credentials = grpc.ssl_channel_credentials()

            return client_credentials
        except Exception as e:
            raise Exception("Failed to load SSL credentials.") from e