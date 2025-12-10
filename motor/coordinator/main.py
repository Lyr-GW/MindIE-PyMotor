#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.

import asyncio
import sys
import os
import traceback
from typing import Any

# Add project root directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

from motor.coordinator.api_server.coordinator_server import (
    CoordinatorServer
)
from motor.coordinator.core.instance_manager import InstanceManager
from motor.coordinator.core.request_manager import RequestManager
from motor.coordinator.core.instance_healthchecker import InstanceHealthChecker
from motor.config.coordinator import CoordinatorConfig
from motor.coordinator.metrics.metrics_collector import MetricsCollector
from motor.common.standby.standby_manager import StandbyManager
from motor.common.utils.config_watcher import ConfigWatcher
from motor.common.utils.logger import get_logger


logger = get_logger(__name__)

modules: dict[str, Any] = {}

# Global config watcher
config_watcher: ConfigWatcher | None = None


def start_all_modules(exclude_modules: set[str] | None = None) -> None:
    """Start all modules gracefully, optionally excluding some modules"""
    logger.info("Starting all modules...")
    if exclude_modules is None:
        exclude_modules = set()

    for module_name, module in modules.items():
        if module_name in exclude_modules:
            continue
        if hasattr(module, 'start'):
            logger.info(f"Starting {module_name}...")
            try:
                module.start()
            except Exception as e:
                logger.error(f"Error starting {module_name}: {e}")
    logger.info("All modules started.")


def stop_all_modules() -> None:
    """Stop all modules gracefully"""
    for module_name, module in modules.items():
        if hasattr(module, 'stop'):
            logger.info(f"Stopping {module_name}...")
            try:
                module.stop()
            except Exception as e:
                logger.error(f"Error stopping {module_name}: {e}")
    logger.info("All modules stopped.")


def on_become_master() -> None:
    """Callback when becoming master - start all modules"""
    logger.info("Becoming master, starting all modules...")
    # Start all modules
    if not modules:
        initialize_components()
    start_all_modules()


def on_become_standby() -> None:
    """Callback when becoming standby - stop all modules"""
    logger.info("Becoming standby, stopping all modules...")
    # Stop all modules
    stop_all_modules()


def initialize_components():
    """Initialize all coordinator components"""
    logger.info("Initializing coordinator components...")
    
    logger.info("Initializing CoordinatorConfig...")
    try:
        modules["CoordinatorConfig"] = CoordinatorConfig()
    except Exception as e:
        logger.error(f"Failed to initialize CoordinatorConfig: {e}")
        raise RuntimeError("Failed to initialize CoordinatorConfig") from e
    
    logger.info("Initializing InstanceManager...")
    modules["InstanceManager"] = InstanceManager()
    
    logger.info("Initializing RequestManager...")
    modules["RequestManager"] = RequestManager()

    logger.info("Initializing MetricsListener...")
    modules["MetricsListener"] = MetricsCollector()
    
    logger.info("Initializing InstanceHealthChecker...")
    modules["InstanceHealthChecker"] = InstanceHealthChecker()
    
    logger.info("Creating server configurations...")
    coordinator_config = modules.get("CoordinatorConfig")
    
    logger.info("Initializing CoordinatorServer...")
    coordinator_server = CoordinatorServer(
        coordinator_config=coordinator_config
    )
    modules["CoordinatorServer"] = coordinator_server
    
    logger.info("All components initialized successfully")


async def main():
    global config_watcher

    try:
        logger.info("Starting Motor Coordinator HTTP server...")

        initialize_components()

        # Start configuration file watcher
        coordinator_config = modules.get("CoordinatorConfig")
        if (
            coordinator_config and coordinator_config.config_file_path and 
            os.path.exists(coordinator_config.config_file_path)
        ):
            config_watcher = ConfigWatcher(
                config_path=coordinator_config.config_file_path,
                reload_callback=coordinator_config.reload
            )
            config_watcher.start()
            logger.info("Configuration file watcher started")

        if coordinator_config.standby_config.enable_master_standby:
            logger.info("Master/standby feature is enabled, running in master-standby mode")
            standby_manager = StandbyManager(coordinator_config)
            standby_manager.start(
                on_become_master=on_become_master,
                on_become_standby=on_become_standby
            )
        else:
            logger.info("Master/standby feature is disabled, running in standalone mode")
            start_all_modules()

        coordinator_server = modules.get("CoordinatorServer")

        if not coordinator_server:
            raise RuntimeError("Failed to initialize server")

        await coordinator_server.run()

    except KeyboardInterrupt:
        logger.info("Received stop signal")
    except asyncio.CancelledError:
        logger.info("Server task cancelled")
    except Exception as e:
        logger.error(f"Server startup failed: {e}")
        raise
    finally:
        # Stop config watcher
        if config_watcher:
            config_watcher.stop()
            logger.info("Configuration file watcher stopped")

        stop_all_modules()
        logger.info("Coordinator server shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, server stopped")
    except asyncio.CancelledError:
        logger.info("Server task cancelled")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)
