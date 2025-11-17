#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import pytest
from unittest import mock
import sys


@pytest.fixture(scope="module")
def mock_dependencies():
    """Mock all dependencies needed for testing ServerCoreFactory."""
    # Store original modules to restore later
    original_modules = {}
    modules_to_mock = [
        'motor.engine_server.utils.logger',
        'motor.engine_server.core.data_controller',
        'motor.engine_server.core.endpoint',
        'motor.engine_server.core.service',
        'vllm',
        'motor.engine_server.core.vllm.vllm_engine_proc_mgr',
        'motor.engine_server.core.vllm.vllm_core'
    ]

    # Save original modules if they exist
    for module_name in modules_to_mock:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]

    # Create mock objects
    mock_logger = mock.MagicMock()
    mock_logger.get_logger = mock.MagicMock(return_value=mock.MagicMock())
    mock_data_controller_class = mock.MagicMock()
    mock_endpoint_class = mock.MagicMock()
    mock_metrics_service_class = mock.MagicMock()
    mock_health_service_class = mock.MagicMock()
    mock_vllm = mock.MagicMock()
    mock_proc_manager_class = mock.MagicMock()
    mock_vllm_core_class = mock.MagicMock()

    # Set up the mock module structure
    mock_data_controller_module = mock.MagicMock()
    mock_data_controller_module.DataController = mock_data_controller_class

    mock_endpoint_module = mock.MagicMock()
    mock_endpoint_module.Endpoint = mock_endpoint_class

    mock_service_module = mock.MagicMock()
    mock_service_module.MetricsService = mock_metrics_service_class
    mock_service_module.HealthService = mock_health_service_class

    mock_vllm_engine_proc_mgr_module = mock.MagicMock()
    mock_vllm_engine_proc_mgr_module.ProcManager = mock_proc_manager_class

    mock_vllm_core_module = mock.MagicMock()
    mock_vllm_core_module.VLLMServerCore = mock_vllm_core_class

    # Replace modules in sys.modules
    sys.modules['motor.engine_server.utils.logger'] = mock_logger
    sys.modules['motor.engine_server.core.data_controller'] = mock_data_controller_module
    sys.modules['motor.engine_server.core.endpoint'] = mock_endpoint_module
    sys.modules['motor.engine_server.core.service'] = mock_service_module
    sys.modules['vllm'] = mock_vllm
    sys.modules['motor.engine_server.core.vllm.vllm_engine_proc_mgr'] = mock_vllm_engine_proc_mgr_module
    sys.modules['motor.engine_server.core.vllm.vllm_core'] = mock_vllm_core_module

    # Yield the mock objects for use in tests
    yield {
        'mock_logger': mock_logger,
        'mock_data_controller_class': mock_data_controller_class,
        'mock_endpoint_class': mock_endpoint_class,
        'mock_metrics_service_class': mock_metrics_service_class,
        'mock_health_service_class': mock_health_service_class,
        'mock_vllm': mock_vllm,
        'mock_proc_manager_class': mock_proc_manager_class,
        'mock_vllm_core_class': mock_vllm_core_class
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
    from motor.engine_server.factory.core_factory import ServerCoreFactory
    from motor.engine_server.config.base import IConfig, ServerConfig
    from motor.engine_server.core.base_core import IServerCore
    return ServerCoreFactory, IConfig, ServerConfig, IServerCore


class TestServerCoreFactory:
    def setup_method(self, mock_dependencies):
        # Get required classes
        ServerCoreFactory, _, _, _ = get_classes()
        # Create factory instance
        self.factory = ServerCoreFactory()

    def test_initialization(self, mock_dependencies):
        # Verify core_map is properly initialized
        assert isinstance(self.factory._core_map, dict)
        assert "vllm" in self.factory._core_map

    def test_create_server_core_with_valid_engine_type(self, mock_dependencies):
        # Get required classes
        _, IConfig, ServerConfig, IServerCore = get_classes()

        # Create mock ServerConfig
        mock_server_config = mock.MagicMock(spec=ServerConfig)
        mock_server_config.engine_type = "vllm"

        # Create mock IConfig
        mock_config = mock.MagicMock(spec=IConfig)
        mock_config.get_server_config.return_value = mock_server_config

        # Create mock return value
        expected_core = mock.MagicMock(spec=IServerCore)

        # Replace VLLMServerCore in factory
        original_vllm_core = self.factory._core_map["vllm"]
        mock_vllm_core_class = mock.MagicMock()
        mock_vllm_core_class.return_value = expected_core
        self.factory._core_map["vllm"] = mock_vllm_core_class

        try:
            # Call method
            result = self.factory.create_server_core(mock_config)

            # Verify result
            assert result == expected_core
            mock_vllm_core_class.assert_called_once_with(mock_config)
            mock_config.get_server_config.assert_called_once()
        finally:
            # Restore original VLLMServerCore
            self.factory._core_map["vllm"] = original_vllm_core

    def test_create_server_core_with_unsupported_engine_type(self, mock_dependencies):
        # Get required classes
        _, IConfig, ServerConfig, _ = get_classes()

        # Create mock ServerConfig with unsupported engine_type
        mock_server_config = mock.MagicMock(spec=ServerConfig)
        mock_server_config.engine_type = "unsupported_engine"

        # Create mock IConfig
        mock_config = mock.MagicMock(spec=IConfig)
        mock_config.get_server_config.return_value = mock_server_config

        # Verify ValueError is raised
        with pytest.raises(ValueError, match="unsupported engine type unsupported_engine"):
            self.factory.create_server_core(mock_config)

        # Verify calls
        mock_config.get_server_config.assert_called_once()

    def test_create_server_core_case_sensitive(self, mock_dependencies):
        # Get required classes
        _, IConfig, ServerConfig, _ = get_classes()

        # Create mock ServerConfig with uppercase engine_type
        mock_server_config = mock.MagicMock(spec=ServerConfig)
        mock_server_config.engine_type = "VLLM"

        # Create mock IConfig
        mock_config = mock.MagicMock(spec=IConfig)
        mock_config.get_server_config.return_value = mock_server_config

        # Verify ValueError is raised (case sensitive matching)
        with pytest.raises(ValueError, match="unsupported engine type VLLM"):
            self.factory.create_server_core(mock_config)

    def test_core_map_immutability(self, mock_dependencies):
        # Get required classes
        ServerCoreFactory, _, _, _ = get_classes()

        # Verify core_map is instance variable not class variable
        factory1 = ServerCoreFactory()
        factory2 = ServerCoreFactory()

        # Modify core_map in factory1
        factory1._core_map["test"] = mock.MagicMock()

        # Verify factory2's core_map is not affected
        assert "test" not in factory2._core_map
