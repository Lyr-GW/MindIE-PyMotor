#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright Huawei Technologies Co., Ltd. 2025. All rights reserved.
import os
import json
import logging
import sys
import ast

logger = logging.getLogger('my_logger')
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


def __get_port(json_file_path, key_path):
    if not os.path.exists(json_file_path):
        return -1

    try:
        with open(json_file_path, 'r', encoding='utf-8') as file:
            config = json.load(file)
    except Exception as e:
        logger.error(f"Failed to load JSON config, {e}")
        return -1

    keys = key_path.split('.')
    config_element = config
    for key in keys:
        if key not in config_element:
            logger.error(f"Key not found in config: {key}")
            return -1
        config_element = config_element[key]
    port = config_element
    if port < 1 or port > 65535:
        return -1
    return port


if __name__ == "__main__":
    json_file_path = sys.argv[1]
    key_path = sys.argv[2]

    return_value = __get_port(json_file_path, key_path)
    logger.info(return_value)