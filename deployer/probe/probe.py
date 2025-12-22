#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright Huawei Technologies Co., Ltd. 2025. All rights reserved.

import os
import json
import logging
import sys
import requests

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Hard-coded URLs for all probe types
PROBE_URLS = {
    'startup': '/startup',
    'readiness': '/readiness',
    'liveness': '/liveness'
}

# Hard-coded default ports
DEFAULT_PORTS = {
    'controller': 1026,
    'coordinator': 1026,
}

# HTTP request timeout
TIMEOUT = 600


def get_port_from_json(json_file_path, key_path):
    """
    Get port from JSON config file.

    Args:
        json_file_path: Path to JSON config file
        key_path: Key path in JSON (e.g., "api_config.controller_api_port")

    Returns:
        Port number, or -1 if not found or invalid
    """
    if not os.path.exists(json_file_path):
        logger.info(f"Config file does not exist: {json_file_path}")
        return -1

    try:
        with open(json_file_path, 'r', encoding='utf-8') as file:
            config = json.load(file)
    except Exception as e:
        logger.error(f"Failed to load JSON config {json_file_path}: {e}")
        return -1

    # Check if config is empty
    if not config:
        logger.info(f"Config file is empty: {json_file_path}")
        return -1

    keys = key_path.split('.')
    config_element = config
    for key in keys:
        if key not in config_element:
            logger.info(f"Key '{key}' not found in config: {key_path}")
            return -1
        config_element = config_element[key]

    port = config_element
    if not isinstance(port, int) or port < 1 or port > 65535:
        logger.error(f"Invalid port value: {port}")
        return -1

    return port


def get_builtin_default_port(role):
    """
    Get built-in default port when JSON config is not available.

    Args:
        role: 'controller' or 'coordinator'

    Returns:
        Built-in default port number, or -1 if not found
    """
    port = DEFAULT_PORTS.get(role)
    if port is not None:
        logger.info(f"Using hard-coded default port: {port}")
        return port
    else:
        logger.error(f"Unknown role: {role}")
        return -1


def get_port(role):
    """
    Get port for the given role, trying JSON config first, then falling back to built-in defaults.

    Args:
        role: 'controller' or 'coordinator'

    Returns:
        Port number, or -1 if not found
    """
    # Determine config file and key path based on role
    config_path = os.environ.get('CONFIG_PATH')
    if not config_path:
        logger.error("CONFIG_PATH environment variable not set")
        return -1

    if role == 'controller':
        config_file = os.path.join(config_path, 'controller_config.json')
        key_path = 'api_config.controller_api_port'
    elif role == 'coordinator':
        config_file = os.path.join(config_path, 'coordinator_config.json')
        key_path = 'http_config.coordinator_api_mgmt_port'
    else:
        logger.error(f"Invalid role: {role}")
        return -1

    # Try to get port from JSON config first
    port = get_port_from_json(config_file, key_path)
    if port != -1:
        return port

    # JSON config failed, use built-in defaults
    logger.info("JSON config not available or invalid, falling back to built-in defaults")
    return get_builtin_default_port(role)


def send_http_request(ip, port, url_path):
    """
    Send HTTP request to the probe endpoint.

    Args:
        ip: IP address
        port: Port number
        url_path: URL path (e.g., '/startup')

    Returns:
        True if successful, False otherwise
    """
    url = f"http://{ip}:{port}{url_path}"
    headers = {
        'User-Agent': 'sh-probe',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=TIMEOUT
        )

        if response.status_code == 200:
            return True
        else:
            logger.error(f"HTTP request failed with status code: {response.status_code}")

    except requests.exceptions.Timeout:
        logger.error(f"HTTP request timed out after {TIMEOUT} seconds")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

    return False


def main():
    """
    Main probe function.
    Usage: python probe.py <role> <probe_type>
    Where:
        role: 'controller' or 'coordinator'
        probe_type: 'startup', 'readiness', or 'liveness'
    """
    if len(sys.argv) != 3:
        logger.error("Usage: python probe.py <role> <probe_type>")
        logger.error("  role: 'controller' or 'coordinator'")
        logger.error("  probe_type: 'startup', 'readiness', or 'liveness'")
        sys.exit(1)

    role = sys.argv[1]
    probe_type = sys.argv[2]

    # Validate role
    if role not in ['controller', 'coordinator']:
        logger.error(f"Invalid role: {role}. Must be 'controller' or 'coordinator'")
        sys.exit(1)

    # Validate probe_type
    if probe_type not in PROBE_URLS:
        logger.error(f"Invalid probe type: {probe_type}. Must be one of {list(PROBE_URLS.keys())}")
        sys.exit(1)

    # Get pod IP from environment
    pod_ip = os.environ.get('POD_IP')
    if not pod_ip:
        logger.error("POD_IP environment variable not set")
        sys.exit(1)

    # Get port
    port = get_port(role)
    if port == -1:
        logger.error("Failed to get port")
        sys.exit(1)

    # Get URL path
    url_path = PROBE_URLS[probe_type]

    logger.info(f"Executing {probe_type} probe for {role} at {pod_ip}:{port}{url_path}")

    # Send HTTP request
    success = send_http_request(pod_ip, port, url_path)

    if success:
        logger.info(f"Service is {probe_type}")
        sys.exit(0)  # success
    else:
        logger.error(f"Service is not {probe_type}")
        sys.exit(1)  # failure


if __name__ == "__main__":
    main()