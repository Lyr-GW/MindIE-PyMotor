#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from motor.engine_server.config.base import ServerConfig
from motor.engine_server.parser.config_parser import ConfigParser
from motor.engine_server.factory.core_factory import ServerCoreFactory
from motor.engine_server.utils.logger import run_log


def main():
    server_config = ServerConfig.init_engine_server_config()
    config_parser = ConfigParser(server_config=server_config)
    config = config_parser.parse()
    run_log.info(f"successfully parsed {server_config.engine_type} engine configuration")

    factory = ServerCoreFactory()
    server_core = factory.create_server_core(config=config)

    server_core.initialize()
    server_core.run()
    server_core.join()


if __name__ == "__main__":
    main()
