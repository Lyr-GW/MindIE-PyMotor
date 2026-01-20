#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright Huawei Technologies Co., Ltd. 2025. All rights reserved.

import json
import logging
import os
import sys

import httpx

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


def get_val_by_key_path(config, key_path):
    keys = key_path.split('.')
    config_element = config
    for key in keys:
        if key not in config_element:
            logger.info(f"Key '{key}' not found in config: {key_path}")
            return -1
        config_element = config_element[key]
    return config_element


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


def get_config(role):
    config_path = os.environ.get('CONFIG_PATH')
    if not config_path:
        logger.error("CONFIG_PATH environment variable not set")
        return -1

    config_file = os.path.join(config_path, f'{role}_config.json')

    if not os.path.exists(config_file):
        logger.info(f"Config file does not exist: {config_file}")
        return -1

    try:
        with open(config_file, 'r', encoding='utf-8') as file:
            config = json.load(file)
    except Exception as e:
        logger.error(f"Failed to load JSON config {config_file}: {e}")
        return -1
    return config


def send_http_request(ip, port, url_path, config):
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

    enable_tls = get_val_by_key_path(config, f'mgmt_tls_config.tls_enable')
    try:
        if enable_tls:
            url = f"https://{ip}:{port}{url_path}"

            cert_file = get_val_by_key_path(config, f'mgmt_tls_config.cert_file')
            key_file = get_val_by_key_path(config, f'mgmt_tls_config.key_file')
            ca_file = get_val_by_key_path(config, f'mgmt_tls_config.ca_file')
            password = get_val_by_key_path(config, f'mgmt_tls_config.passwd_file')

            client = httpx.Client(
                headers=headers,
                timeout=TIMEOUT,
                cert=(cert_file, key_file, password if password else None),
                verify=ca_file
            )
        else:
            client = httpx.Client(headers=headers, timeout=TIMEOUT)
        response = client.get(url)
        if response.status_code == 200:
            return True
        else:
            logger.error(f"HTTP request failed with status code: {response.status_code}")
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

    config = get_config(role)
    logger.info(f"config: {config}")
    if config == -1:
        logger.error("Failed to get config")
        sys.exit(1)

    port = get_val_by_key_path(config, f'api_config.{role}_api_port')
    if not isinstance(port, int) or port < 1024 or port > 65535:
        logger.warning(f"Invalid port in config: {port}, using built-in default port")
        port = get_builtin_default_port(role)
        if port == -1:
            logger.error("Failed to get port")
            sys.exit(1)

    # Get URL path
    url_path = PROBE_URLS[probe_type]

    logger.info(f"Executing {probe_type} probe for {role} at {pod_ip}:{port}{url_path}")

    # Send HTTP request
    success = send_http_request(pod_ip, port, url_path, config)

    if success:
        logger.info(f"Service is {probe_type}")
        sys.exit(0)  # success
    else:
        logger.error(f"Service is not {probe_type}")
        sys.exit(1)  # failure


if __name__ == "__main__":
    main()
