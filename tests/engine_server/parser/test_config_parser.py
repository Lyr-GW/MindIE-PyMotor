#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import pytest
from unittest import mock
import sys


@pytest.fixture(scope="module")
def mock_dependencies():
    """Mock all dependencies needed for testing ConfigParser."""
    # Store original modules to restore later
    original_modules = {}
    modules_to_mock = [
        'motor.engine_server.utils.logger',
        'motor.engine_server.config.vllm'
    ]

    # Save original modules if they exist
    for module_name in modules_to_mock:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]

    # Create mock objects
    mock_logger = mock.MagicMock()
    mock_logger.get_logger = mock.MagicMock(return_value=mock.MagicMock())
    mock_vllm_config_class = mock.MagicMock()

    # Set up the mock module structure
    mock_vllm_module = mock.MagicMock()
    mock_vllm_module.VLLMConfig = mock_vllm_config_class

    # Replace modules in sys.modules
    sys.modules['motor.engine_server.utils.logger'] = mock_logger
    sys.modules['motor.engine_server.config.vllm'] = mock_vllm_module

    # Yield the mock objects for use in tests
    yield {
        'mock_logger': mock_logger,
        'mock_vllm_config_class': mock_vllm_config_class
    }

    # Restore original modules
    for module_name in modules_to_mock:
        if module_name in original_modules:
            sys.modules[module_name] = original_modules[module_name]
        elif module_name in sys.modules:
            del sys.modules[module_name]


# Import classes inside a function to be called after mocks are set up
def get_classes():
    """Import the classes needed for testing."""
    from motor.engine_server.parser.config_parser import ConfigParser
    from motor.engine_server.config.base import IConfig, ServerConfig
    return ConfigParser, IConfig, ServerConfig


class TestConfigParser:
    def setup_method(self, mock_dependencies):
        # Get required classes
        ConfigParser, _, ServerConfig = get_classes()

        # Create mock ServerConfig
        self.mock_server_config = mock.MagicMock(spec=ServerConfig)

        # Create parser instance
        self.parser = ConfigParser(server_config=self.mock_server_config)

    def test_initialization(self, mock_dependencies):
        # Verify initialization sets up properties correctly
        assert self.parser.server_config == self.mock_server_config
        assert isinstance(self.parser._config_class_map, dict)
        assert "vllm" in self.parser._config_class_map

    def test_parse_with_valid_engine_type(self, mock_dependencies):
        # Get required classes
        _, IConfig, _ = get_classes()

        # Set up mock server_config with valid engine_type
        self.mock_server_config.engine_type = "vllm"

        # Create mock config instance
        mock_config_instance = mock.MagicMock(spec=IConfig)

        # Replace the config class in parser
        original_config_class = self.parser._config_class_map["vllm"]
        mock_config_class = mock.MagicMock()
        mock_config_class.return_value = mock_config_instance
        self.parser._config_class_map["vllm"] = mock_config_class

        try:
            # Call parse method
            result = self.parser.parse()

            # Verify results
            assert result == mock_config_instance
            mock_config_class.assert_called_once_with(server_config=self.mock_server_config)
            mock_config_instance.initialize.assert_called_once()
            mock_config_instance.convert.assert_called_once()
            mock_config_instance.validate.assert_called_once()
        finally:
            # Restore original config class
            self.parser._config_class_map["vllm"] = original_config_class

    def test_parse_with_unsupported_engine_type(self, mock_dependencies):
        # Set up mock server_config with unsupported engine_type
        self.mock_server_config.engine_type = "unsupported_engine"

        # Verify ValueError is raised
        with pytest.raises(ValueError) as excinfo:
            self.parser.parse()

        # Check error message contains expected parts
        error_message = str(excinfo.value)
        assert "Unsupported engine type: unsupported_engine" in error_message
        assert "vllm" in error_message

    def test_parse_case_sensitive(self, mock_dependencies):
        # Set up mock server_config with uppercase engine_type
        self.mock_server_config.engine_type = "VLLM"

        # Verify ValueError is raised (case sensitive matching)
        with pytest.raises(ValueError) as excinfo:
            self.parser.parse()

        # Check error message contains expected parts
        error_message = str(excinfo.value)
        assert "Unsupported engine type: VLLM" in error_message
        assert "vllm" in error_message

    def test_config_class_map_immutability(self, mock_dependencies):
        # Get required classes
        ConfigParser, _, ServerConfig = get_classes()

        # Create two parser instances
        mock_server_config1 = mock.MagicMock(spec=ServerConfig)
        mock_server_config2 = mock.MagicMock(spec=ServerConfig)

        parser1 = ConfigParser(server_config=mock_server_config1)
        parser2 = ConfigParser(server_config=mock_server_config2)

        # Modify config_class_map in parser1
        parser1._config_class_map["test"] = mock.MagicMock()

        # Verify parser2's config_class_map is not affected
        assert "test" not in parser2._config_class_map
