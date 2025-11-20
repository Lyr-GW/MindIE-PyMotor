#!/usr/bin/env python3
# coding=utf-8

from unittest.mock import patch


TEST_ENV_VARS = {
    'JOB_NAME': 'test_job',
    'CONFIG_PATH': './',
    'HCCL_PATH': './tests/jsons/hccl.json'
}

def setup_test_environment():
    return patch.dict('os.environ', TEST_ENV_VARS)

_env_patcher = setup_test_environment()
_env_patcher.start()

def teardown_test_environment():
    _env_patcher.stop()
