#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

# Import necessary libraries and modules
import pytest
import sys
import json
import argparse
from unittest.mock import patch, MagicMock, Mock, mock_open
from dataclasses import dataclass, field


@pytest.fixture(autouse=True, scope="module")
def mock_vllm_module():
    """Mock vllm module and its submodules completely to intercept all vllm-related imports during import phase"""
    # First check and save original modules (if they exist)
    original_modules = {}
    vllm_related_modules = [
        'vllm',
        'vllm.utils',
        'vllm.entrypoints',
        'vllm.entrypoints.openai',
        'vllm.entrypoints.openai.cli_args'
    ]

    # Save other modules that might be mocked
    other_modules = [
        'motor.engine_server.utils.logger',
        'motor.engine_server.utils.ranktable'
    ]

    for module_name in vllm_related_modules + other_modules:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]

    # Create mock module structure
    mock_vllm = Mock()
    mock_vllm.utils = Mock()
    mock_vllm.utils.FlexibleArgumentParser = MagicMock(return_value=argparse.ArgumentParser())
    mock_vllm.entrypoints = Mock()
    mock_vllm.entrypoints.openai = Mock()
    mock_vllm.entrypoints.openai.cli_args = Mock()
    mock_vllm.entrypoints.openai.cli_args.make_arg_parser = MagicMock(return_value=argparse.ArgumentParser())
    mock_vllm.entrypoints.openai.cli_args.validate_parsed_serve_args = MagicMock()

    # Mock logger.run_log
    mock_logger = Mock()
    mock_logger.run_log = MagicMock()

    # Mock ranktable.get_data_parallel_address
    mock_ranktable = Mock()
    mock_ranktable.get_data_parallel_address = MagicMock(return_value="127.0.0.1")

    # Replace modules in sys.modules
    sys.modules['vllm'] = mock_vllm
    sys.modules['vllm.utils'] = mock_vllm.utils
    sys.modules['vllm.entrypoints'] = mock_vllm.entrypoints
    sys.modules['vllm.entrypoints.openai'] = mock_vllm.entrypoints.openai
    sys.modules['vllm.entrypoints.openai.cli_args'] = mock_vllm.entrypoints.openai.cli_args
    sys.modules['motor.engine_server.utils.logger'] = mock_logger
    sys.modules['motor.engine_server.utils.ranktable'] = mock_ranktable

    # Build dictionary of mock objects to return
    mock_objects = {
        'vllm_module': mock_vllm,
        'flexible_parser': mock_vllm.utils.FlexibleArgumentParser,
        'make_arg_parser': mock_vllm.entrypoints.openai.cli_args.make_arg_parser,
        'validate_args': mock_vllm.entrypoints.openai.cli_args.validate_parsed_serve_args,
        'run_log': mock_logger.run_log,
        'get_data_parallel_address': mock_ranktable.get_data_parallel_address
    }

    # Provide mock objects to tests
    yield mock_objects

    # Cleanup: restore original modules or remove mock modules
    for module_name in vllm_related_modules + other_modules:
        if module_name in original_modules:
            sys.modules[module_name] = original_modules[module_name]
        elif module_name in sys.modules:
            del sys.modules[module_name]


@pytest.fixture
def imports():
    # Direct import without using mock_modules fixture
    from motor.engine_server.config.base import ServerConfig, BaseConfig
    from motor.engine_server.config.vllm import VLLMConfig, _add_argument_to_list
    return {
        'ServerConfig': ServerConfig,
        'BaseConfig': BaseConfig,
        'VLLMConfig': VLLMConfig,
        '_add_argument_to_list': _add_argument_to_list
    }


@dataclass
class MockParallelConfig:
    dp_size: int = 1
    dp_rpc_port: int = 8000
    tp_size: int = 1


@dataclass
class MockModelConfig:
    model_path: str = "test-model"
    npu_mem_utils: float = 0.9
    dp_rank: int = 0
    dp_size: int = 1
    tp_size: int = 1
    enable_ep: bool = False


@dataclass
class MockEngineConfig:
    configs: dict = field(default_factory=lambda: {
        "max-model-len": 4096,
        "tensor-parallel-size": 1
    })

    def get(self, key, default=None):
        # Mock dictionary's get method
        return self.configs.get(key, default)


@dataclass
class MockDeployConfig:
    model_config: MockModelConfig = field(default_factory=MockModelConfig)
    engine_config: MockEngineConfig = field(default_factory=MockEngineConfig)

    def get_parallel_config(self, role):
        return MockParallelConfig()


@pytest.fixture
def server_config():
    from dataclasses import field
    from motor.engine_server.config.base import ServerConfig
    config = ServerConfig(
        server_host="localhost",
        server_port=9001,
        engine_type="vllm",
        config_path=None,
        dp_rank=0
    )
    config.deploy_config = MockDeployConfig()
    config.role = "union"
    config.engine_port = 8000
    config.instance_id = "test-instance"
    return config


@pytest.fixture
def prefill_server_config(server_config):
    # Create new ServerConfig instance instead of using copy method
    from motor.engine_server.config.base import ServerConfig
    config = ServerConfig(
        server_host=server_config.server_host,
        server_port=server_config.server_port,
        engine_type=server_config.engine_type,
        config_path=server_config.config_path,
        dp_rank=server_config.dp_rank
    )
    config.deploy_config = server_config.deploy_config
    config.role = "prefill"
    config.engine_port = server_config.engine_port
    config.instance_id = server_config.instance_id
    return config


@pytest.fixture
def decode_server_config(server_config):
    # Create new ServerConfig instance instead of using copy method
    from motor.engine_server.config.base import ServerConfig
    config = ServerConfig(
        server_host=server_config.server_host,
        server_port=server_config.server_port,
        engine_type=server_config.engine_type,
        config_path=server_config.config_path,
        dp_rank=server_config.dp_rank
    )
    config.deploy_config = server_config.deploy_config
    config.role = "decode"
    config.engine_port = server_config.engine_port
    config.instance_id = server_config.instance_id
    return config


class TestAddArgumentToList:
    def test_add_argument_to_list_bool_true(self, imports):
        _add_argument_to_list = imports['_add_argument_to_list']
        arg_list = []
        _add_argument_to_list(arg_list, "test-key", True)
        assert arg_list == ["--test-key"]

    def test_add_argument_to_list_bool_false(self, imports):
        _add_argument_to_list = imports['_add_argument_to_list']
        arg_list = []
        _add_argument_to_list(arg_list, "test-key", False)
        assert arg_list == []

    def test_add_argument_to_list_string(self, imports):
        _add_argument_to_list = imports['_add_argument_to_list']
        arg_list = []
        _add_argument_to_list(arg_list, "test-key", "test-value")
        assert arg_list == ["--test-key", "test-value"]

    def test_add_argument_to_list_number(self, imports):
        _add_argument_to_list = imports['_add_argument_to_list']
        arg_list = []
        _add_argument_to_list(arg_list, "test-key", 42)
        assert arg_list == ["--test-key", "42"]

    def test_add_argument_to_list_list(self, imports):
        _add_argument_to_list = imports['_add_argument_to_list']
        arg_list = []
        _add_argument_to_list(arg_list, "test-key", [1, 2, 3])
        assert arg_list == ["--test-key", "1", "2", "3"]

    def test_add_argument_to_list_empty_list(self, imports):
        _add_argument_to_list = imports['_add_argument_to_list']
        arg_list = []
        _add_argument_to_list(arg_list, "test-key", [])
        assert arg_list == []


class TestVLLMConfig:
    def test_initialization_default(self, imports, server_config):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)

        assert vllm_config.args is None
        assert vllm_config.data_parallel_address is None
        assert vllm_config.data_parallel_rpc_port is None
        assert vllm_config.kv_transfer_config is None
        assert 'model_path' in vllm_config.mapping
        assert vllm_config.mapping['model_path'] == 'model'

    def test_initialize_no_data_parallel(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)
        mock_get_data_parallel_address = mock_vllm_module['get_data_parallel_address']
        mock_get_data_parallel_address.return_value = None

        with patch.object(vllm_config, 'server_config') as mock_server_config:
            mock_deploy_config = MagicMock()
            mock_parallel_config = MagicMock()
            mock_parallel_config.dp_size = 1
            mock_deploy_config.get_parallel_config.return_value = mock_parallel_config
            mock_server_config.deploy_config = mock_deploy_config
            mock_server_config.role = "union"

            vllm_config.initialize()

            assert vllm_config.data_parallel_address is None
            assert vllm_config.data_parallel_rpc_port is None

    def test_initialize_with_data_parallel(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)
        mock_get_data_parallel_address = mock_vllm_module['get_data_parallel_address']
        mock_get_data_parallel_address.return_value = "192.168.1.100"

        # For prefill role, we need to mock _process_kv_transfer_config method
        with patch.object(vllm_config, '_process_kv_transfer_config'):
            with patch.object(vllm_config, 'server_config') as mock_server_config:
                mock_deploy_config = MagicMock()
                mock_parallel_config = MagicMock()
                mock_parallel_config.dp_size = 2
                mock_parallel_config.dp_rpc_port = 9999
                mock_deploy_config.get_parallel_config.return_value = mock_parallel_config
                mock_server_config.deploy_config = mock_deploy_config
                mock_server_config.role = "prefill"

                vllm_config.initialize()

                assert vllm_config.data_parallel_address == "192.168.1.100"
                assert vllm_config.data_parallel_rpc_port == 9999

    @patch('motor.engine_server.config.vllm.BaseConfig.validate')
    def test_validate_with_args(self, mock_base_validate, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        mock_validate_args = mock_vllm_module['validate_args']

        vllm_config = VLLMConfig(server_config=server_config)
        vllm_config.args = MagicMock()

        vllm_config.validate()

        mock_base_validate.assert_called_once()
        mock_validate_args.assert_called_once_with(vllm_config.args)

    @patch('motor.engine_server.config.vllm.BaseConfig.validate')
    def test_validate_without_args(self, mock_base_validate, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        mock_validate_args = mock_vllm_module['validate_args']

        # Reset mock object
        mock_validate_args.reset_mock()

        vllm_config = VLLMConfig(server_config=server_config)
        vllm_config.args = None

        vllm_config.validate()

        mock_base_validate.assert_called_once()
        mock_validate_args.assert_not_called()

    @patch('motor.engine_server.config.vllm.BaseConfig.convert')
    def test_convert(self, mock_base_convert, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        mock_make_arg_parser = mock_vllm_module['make_arg_parser']
        mock_flexible_parser = mock_vllm_module['flexible_parser']
        mock_run_log = mock_vllm_module['run_log']

        vllm_config = VLLMConfig(server_config=server_config)

        # Mock _get_param_list method
        with patch.object(vllm_config, '_get_param_list', return_value=["--model", "test-model"]):
            with patch('sys.argv', ["serve"]):
                # Mock parser
                mock_parser = MagicMock()
                mock_parser.parse_args.return_value = argparse.Namespace(model="test-model")
                mock_make_arg_parser.return_value = mock_parser
                mock_flexible_parser.return_value = mock_parser

                vllm_config.convert()

                mock_base_convert.assert_called_once()
                mock_run_log.info.assert_called_once()
                mock_make_arg_parser.assert_called_once()
                mock_parser.parse_args.assert_called_once()
                assert vllm_config.args.model == "test-model"

    def test_get_args(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)
        test_args = argparse.Namespace(model="test-model")
        vllm_config.args = test_args

        assert vllm_config.get_args() == test_args

    def test_get_server_config(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)

        assert vllm_config.get_server_config() == server_config

    def test_flatten_config_basic(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)

        flattened = vllm_config._flatten_config()

        assert "host" in flattened
        assert flattened["host"] == "localhost"
        assert "port" in flattened
        assert flattened["port"] == 8000
        assert "max-model-len" in flattened
        assert flattened["max-model-len"] == 4096

    def test_flatten_config_with_data_parallel(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)
        vllm_config.data_parallel_address = "192.168.1.100"
        vllm_config.data_parallel_rpc_port = 9999
        vllm_config.server_config.dp_rank = 0

        flattened = vllm_config._flatten_config()

        assert "data_parallel_address" in flattened
        assert flattened["data_parallel_address"] == "192.168.1.100"
        assert "data_parallel_rpc_port" in flattened
        assert flattened["data_parallel_rpc_port"] == 9999
        assert "data_parallel_rank" in flattened
        assert flattened["data_parallel_rank"] == 0

    def test_flatten_config_with_kv_transfer(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)
        vllm_config.kv_transfer_config = json.dumps({"test": "config"})

        flattened = vllm_config._flatten_config()

        assert "kv_transfer_config" in flattened
        assert flattened["kv_transfer_config"] == json.dumps({"test": "config"})

    def test_get_param_list(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)

        # Mock _flatten_config method
        with patch.object(vllm_config, '_flatten_config', return_value={
            "test_key": "test_value",
            "bool_flag": True,
            "list_values": [1, 2]
        }):
            param_list = vllm_config._get_param_list()

            expected = [
                "--test-key", "test_value",
                "--bool-flag",
                "--list-values", "1", "2"
            ]
            assert param_list == expected

    def test_process_kv_transfer_config_prefill(self, imports, prefill_server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=prefill_server_config)

        # Set kv_transfer_config as JSON object (no longer needs json.dumps)
        kv_config = {
            "kv_connector_extra_config": {
                "prefill": {},
                "decode": {}
            }
        }

        with patch.object(vllm_config.server_config.deploy_config.engine_config, 'get', return_value=kv_config):
            vllm_config._process_kv_transfer_config()

            assert vllm_config.kv_transfer_config is not None
            # Need to parse the JSON string to access the config
            parsed_kv_config = json.loads(vllm_config.kv_transfer_config)
            assert parsed_kv_config["kv_role"] == "kv_producer"
            assert parsed_kv_config["engine_id"] == "test-instance"

    def test_process_kv_transfer_config_decode(self, imports, decode_server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=decode_server_config)

        kv_config = {
            "kv_connector_extra_config": {
                "prefill": {},
                "decode": {}
            }
        }

        with patch.object(vllm_config.server_config.deploy_config.engine_config, 'get', return_value=kv_config):
            vllm_config._process_kv_transfer_config()

            assert vllm_config.kv_transfer_config is not None
            # Need to parse the JSON string to access the config
            parsed_kv_config = json.loads(vllm_config.kv_transfer_config)
            assert parsed_kv_config["kv_role"] == "kv_consumer"
            assert parsed_kv_config["engine_id"] == "test-instance"

    def test_process_kv_transfer_config_union(self, imports, server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=server_config)

        # For union role, kv_transfer_config should not be processed
        vllm_config._process_kv_transfer_config()
        assert vllm_config.kv_transfer_config is None

    def test_process_kv_transfer_config_none(self, imports, prefill_server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=prefill_server_config)

        # Set kv_transfer_config to None
        with patch.object(vllm_config.server_config.deploy_config.engine_config, 'get', return_value=None):
            with pytest.raises(ValueError, match="kv_transfer_config is None in engine_config"):
                vllm_config._process_kv_transfer_config()

    def test_process_kv_transfer_config_invalid_json(self, imports, prefill_server_config, mock_vllm_module):
        VLLMConfig = imports['VLLMConfig']
        vllm_config = VLLMConfig(server_config=prefill_server_config)
        mock_run_log = mock_vllm_module['run_log']

        # Set invalid type (not a dictionary)
        with patch.object(vllm_config.server_config.deploy_config.engine_config, 'get', return_value="invalid-type"):
            with pytest.raises(ValueError, match="Failed to process kv_transfer_config"):
                vllm_config._process_kv_transfer_config()

            mock_run_log.error.assert_called_once()
