# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import os
import sys
import signal
import argparse
import threading
import time
from typing import Any

from motor.config.controller import ControllerConfig, set_config_path, find_config_file
from motor.controller.api_server import ControllerAPI
from motor.controller.core import InstanceAssembler, InstanceManager, EventPusher
from motor.common.standby.standby_manager import StandbyManager
from motor.common.utils.config_watcher import ConfigWatcher
from motor.common.utils.logger import get_logger


logger = get_logger(__name__)

# Global stop event for main loop
stop_event = threading.Event()

# Global modules dictionary
modules: dict[str, Any] = {}

# Global configuration
config: ControllerConfig | None = None

# Global config watcher
config_watcher: ConfigWatcher | None = None

# Global previous fault tolerance state for change detection
previous_fault_tolerance_enabled: bool = False


def on_config_updated() -> None:
    """Callback function called when configuration is updated"""
    global config, modules, previous_fault_tolerance_enabled

    if config is None:
        logger.error("Configuration is None in config update callback")
        return

    # Check if fault tolerance configuration has changed
    current_fault_tolerance_enabled = config.fault_tolerance_config.enable_fault_tolerance

    if current_fault_tolerance_enabled != previous_fault_tolerance_enabled:
        if current_fault_tolerance_enabled:
            # Fault tolerance was enabled
            logger.info("Fault tolerance feature enabled, starting FaultManager...")
            try:
                from motor.controller.ft.fault_manager import FaultManager
                fault_manager = FaultManager(config)
                modules["FaultManager"] = fault_manager

                # Attach to instance manager as observer
                instance_manager = modules.get("InstanceManager")
                if instance_manager is not None:
                    logger.info("Attaching FaultManager to instance manager")
                    instance_manager.attach(fault_manager)

                # Start the fault manager
                fault_manager.start()
                logger.info("FaultManager started successfully")
            except Exception as e:
                logger.error(f"Failed to start FaultManager: {e}")
        else:
            # Fault tolerance was disabled
            logger.info("Fault tolerance feature disabled, stopping FaultManager...")
            try:
                fault_manager = modules.get("FaultManager")
                if fault_manager is not None:
                    # Stop the fault manager
                    fault_manager.stop()
                    logger.info("FaultManager stopped successfully")

                    # Remove from modules
                    modules.pop("FaultManager", None)
                    logger.info("FaultManager removed from modules")
                else:
                    logger.warning("FaultManager not found in modules")
            except Exception as e:
                logger.error(f"Failed to stop FaultManager: {e}")

        # Update previous state
        previous_fault_tolerance_enabled = current_fault_tolerance_enabled

    # Update configuration for all modules
    logger.info("Updating configuration for all modules...")
    for module_name, module in modules.items():
        if hasattr(module, 'update_config'):
            try:
                module.update_config(config)
                logger.info(f"Updated configuration for {module_name}")
            except Exception as e:
                logger.error(f"Failed to update configuration for {module_name}: {e}")


observers_list = {
    "EventPusher",
    "FaultManager",
}


def init_all_modules() -> None:
    """Initialize all modules but don't start them yet"""

    global config, modules
    if config is None:
        config = ControllerConfig()

    modules["InstanceAssembler"] = InstanceAssembler(config)
    modules["EventPusher"] = EventPusher(config)
    modules["ControllerAPI"] = ControllerAPI(config, modules)
    if config.fault_tolerance_config.enable_fault_tolerance:
        from motor.controller.ft.fault_manager import FaultManager
        modules["FaultManager"] = FaultManager(config)
    modules["InstanceManager"] = InstanceManager(config)

    # Attach observers before starting modules
    instance_manager = modules.get("InstanceManager")
    if instance_manager is None:
        logger.error("InstanceManager not found in modules")
        return

    for module_name, module in modules.items():
        if module_name in observers_list:
            logger.info("Attaching %s to instance manager", module_name)
            instance_manager.attach(module)
    logger.info("All observers attached to instance manager")


def start_all_modules(exclude_modules: set[str] | None = None) -> None:
    """Start all modules, optionally excluding some modules"""
    if exclude_modules is None:
        exclude_modules = set()

    for module_name, module in modules.items():
        if module_name in exclude_modules:
            continue
        if hasattr(module, 'start'):
            try:
                logger.info(f"Starting {module_name}")
                module.start()
            except Exception as e:
                logger.error(f"Error starting module {module_name}: {e}")
    logger.info("All modules started")


def stop_all_modules(exclude_modules: set[str] | None = None) -> None:
    """Stop all modules, optionally excluding some modules"""
    if exclude_modules is None:
        exclude_modules = set()

    for module_name, module in modules.items():
        if module_name in exclude_modules:
            continue
        if hasattr(module, 'stop'):
            try:
                module.stop()
            except Exception as e:
                logger.error(f"Error stopping module {module_name}: {e}")
    logger.info("All modules stopped.")


def on_become_master() -> None:
    """Callback when becoming master - start all modules except ControllerAPI (which runs always)"""
    logger.info("Becoming master, starting all modules except ControllerAPI...")
    global config
    if not modules:  # Only initialize if not already initialized
        init_all_modules()
    # Start all modules except ControllerAPI, which should always be running
    start_all_modules(exclude_modules={"ControllerAPI"})


def on_become_standby() -> None:
    """Callback when becoming standby - stop all modules except ControllerAPI (which runs always)"""
    logger.info("Becoming standby, stopping all modules except ControllerAPI...")
    # Stop all modules except ControllerAPI, which should always be running
    stop_all_modules(exclude_modules={"ControllerAPI"})


def get_controller_status() -> dict:
    """
    Get controller status including:
    - deploy mode: "master_standby" or "standalone"
    - role(Optional): "master" or "standby"
    - overall health of all modules
    """
    status = {}

    # Check module health
    unhealthy_modules = []
    for name, module in modules.items():
        if not hasattr(module, 'is_alive'):
            continue
        alive = module.is_alive()
        if not alive:
            unhealthy_modules.append(name)

    if unhealthy_modules:
        status["overall_healthy"] = False
        logger.error("Unhealthy modules: %s", unhealthy_modules)
    else:
        status["overall_healthy"] = True

    # Set deploy mode and role
    if config.standby_config.enable_master_standby:
        status["deploy_mode"] = "master_standby"
        # Get singleton instance (assumes it has been initialized)
        status["role"] = "master" if StandbyManager().is_master() else "standby"
    else:
        status["deploy_mode"] = "standalone"

    return status


def signal_handler(sig, frame) -> None:
    global config_watcher
    logger.warning("Receive signal %d, exit gracefully...", sig)
    stop_event.set()
    stop_all_modules()

    # Stop config watcher
    if config_watcher:
        config_watcher.stop()

    sys.exit(0)


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Motor Controller')
    parser.add_argument('--config', '-c', 
                        type=str, 
                        default=None,
                        help='Path to configuration file (default: auto-detect)')
    return parser.parse_args()


def main() -> None:
    global config, config_watcher, previous_fault_tolerance_enabled

    args = parse_arguments()

    if args.config:
        set_config_path(args.config)
        logger.info("Using configuration file: %s", args.config)
    else:
        logger.info("Using auto-detected configuration file")

    config_path = args.config if args.config else None
    try:
        if config_path:
            config = ControllerConfig.from_json(config_path)
        else:
            # Find config file automatically
            config = ControllerConfig.from_json(find_config_file())
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}, using default configuration")
        config = ControllerConfig()

    # Initialize previous fault tolerance state
    previous_fault_tolerance_enabled = config.fault_tolerance_config.enable_fault_tolerance

    # Start configuration file watcher if config file exists
    if config.config_path and os.path.exists(config.config_path):
        config_watcher = ConfigWatcher(
            config_path=config.config_path,
            reload_callback=config.reload,
            config_update_callback=on_config_updated
        )
        config_watcher.start()
        logger.info("Configuration file watcher started")

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start master/standby management if enabled
    if config.standby_config.enable_master_standby:
        # Initialize ControllerAPI first (it should always run)
        init_all_modules()
        # Start only ControllerAPI, other modules will be started when becoming master
        exclude_modules = {"InstanceManager", "InstanceAssembler", "EventPusher"}
        if config.fault_tolerance_config.enable_fault_tolerance:
            exclude_modules.add("FaultManager")
        start_all_modules(exclude_modules=exclude_modules)

        # Get singleton instance and initialize/start it
        standby_manager = StandbyManager(config)
        standby_manager.start(
            on_become_master=on_become_master,
            on_become_standby=on_become_standby
        )
        logger.info("Controller started in standby mode, waiting to become master...")
    else:
        logger.info("Master/standby feature is disabled, running in standalone mode")
        # Initialize and start all modules for standalone mode
        logger.info("Initializing all modules...")
        init_all_modules()
        logger.info("Starting all modules...")
        start_all_modules()

    logger.info("Press Ctrl+C or type 'stop' to exit.")
    try:
        while not stop_event.is_set():
            try:
                user_input = input().strip().lower()
                if user_input == 'stop':
                    stop_event.set()
                    break
                elif user_input:
                    logger.error("Unknown command: %s", user_input)
            except EOFError:
                # In non-interactive environment, keep program running
                time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()

    # Cleanup
    stop_all_modules()

    if config.standby_config.enable_master_standby:
        # Stop standby manager singleton if it was started
        StandbyManager().stop()

    # Stop config watcher
    if config_watcher:
        config_watcher.stop()
        logger.info("Configuration file watcher stopped")

    logger.info("Controller shutdown complete")


if __name__ == '__main__':
    main()