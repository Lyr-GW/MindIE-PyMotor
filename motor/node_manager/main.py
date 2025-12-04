#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import signal
import time
import os
from typing import Optional

from motor.common.utils.logger import get_logger
from motor.node_manager.api_server.node_manager_api import NodeManagerAPI
from motor.config.node_manager import NodeManagerConfig
from motor.node_manager.core.daemon import Daemon
from motor.node_manager.core.engine_manager import EngineManager
from motor.node_manager.core.heartbeat_manager import HeartbeatManager
from motor.common.utils.config_watcher import ConfigWatcher
from motor.common.utils.env import Env


logger = get_logger(__name__)

modules = []
_should_exit = False

# Global configuration
config: NodeManagerConfig | None = None

# Global config watcher
config_watcher: ConfigWatcher | None = None


def init_all_modules(config_path: str | None = None, hccl_path: str | None = None) -> None:
    """Initialize all modules but don't start them yet"""

    global config
    if config is None:
        config = NodeManagerConfig.from_json(config_path, hccl_path)

    modules.append(config)
    modules.append(Daemon(config))
    modules.append(EngineManager(config))
    modules.append(HeartbeatManager(config))
    modules.append(NodeManagerAPI(config=config))
    logger.info("All modules initialized")


def stop_all_modules() -> None:
    while modules:
        module = modules.pop()
        if hasattr(module, 'stop'):
            try:
                module.stop()
            except Exception as e:
                logger.error(f"Failed to stop {type(module).__name__}: {e}")
    logger.info("All modules stopped.")


def signal_handler(sig, frame) -> None:
    global _should_exit, config_watcher
    if _should_exit:
        return
    _should_exit = True
    logger.info(f"\nReceive signal {sig},exit gracefully...")

    # Stop config watcher
    if config_watcher:
        config_watcher.stop()

    stop_all_modules()


def main() -> None:
    global _should_exit, config_watcher, config

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # kill

    # Initialize all modules
    init_all_modules(Env.config_path, Env.hccl_path)

    # Start configuration file watcher
    if config.config_path and os.path.exists(config.config_path):
        config_watcher = ConfigWatcher(
            config_path=config.config_path,
            reload_callback=config.reload
        )
        config_watcher.start()
        logger.info("Configuration file watcher started")

    logger.info("All modules started, monitoring...")

    logger.info("Press Ctrl+C or type 'stop' to exit.")
    try:
        while not _should_exit:
            try:
                user_input = input().strip().lower()
                if user_input == 'stop':
                    _should_exit = True
                elif user_input:
                    logger.warning(f"Unknown command: {user_input}")
            except EOFError:
                if not _should_exit:
                    time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, shutting down...")
        _should_exit = True
    finally:
        # Stop config watcher
        if config_watcher:
            config_watcher.stop()
            logger.info("Configuration file watcher stopped")

        stop_all_modules()


if __name__ == '__main__':
    main()