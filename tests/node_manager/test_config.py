#!/usr/bin/env python3
# coding=utf-8

import json
import os
import sys
import pytest
from unittest.mock import patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from motor.config.node_manager import NodeManagerConfig
from motor.common.resources.instance import ParallelConfig, PDRole


@pytest.fixture
def config_data():
    return {
        "parallel_config": {"tp_size": 2, "pp_size": 1},
        "role": "both",
        "controller_api_dns": "localhost", 
        "controller_api_port": 8080,
        "node_manager_port": 8080,
        "model_name": "vllm"
    }


@pytest.fixture
def hccl_data():
    return {
        "status": "completed",
        "server_count": "1",
        "version": "1.2",
        "server_list": [{
            "server_id": "90.90.97.30",
            "container_ip": "127.0.0.1",  # Used by NodeManagerConfig, not Ranktable
            "hardware_type": "Ascend910",  # Used by NodeManagerConfig, not Ranktable
            "device": [
                {"device_id": str(i), "device_ip": f"192.168.1.{i+1}", "super_device_id": f"12645532{i}", "rank_id": str(i)}
                for i in range(8)  # 8 devices for TYPE_800I_A2
            ]
        }]
    }


def create_config_mock(config_data, hccl_data):
    def mock_side_effect(file_path, mode):
        if "node_manager_config.json" in file_path:
            return mock_open(read_data=json.dumps(config_data)).return_value
        elif "hccl.json" in file_path:
            return mock_open(read_data=json.dumps(hccl_data)).return_value
        return mock_open().return_value
    return mock_side_effect


def clear_node_manager_config():
    """Clear singleton instance and reset class variables"""
    # Clear singleton instance
    if hasattr(NodeManagerConfig, '_instances'):
        if NodeManagerConfig in NodeManagerConfig._instances:
            del NodeManagerConfig._instances[NodeManagerConfig]
    
    # Reset class variables to initial state
    # Important: clear lists before reassigning to ensure no reference issues
    NodeManagerConfig.device_info.clear()
    NodeManagerConfig.mgmt_ports.clear()
    NodeManagerConfig.service_ports.clear()
    
    NodeManagerConfig.pod_ip = None
    NodeManagerConfig.host_ip = None
    NodeManagerConfig.parallel_config = None
    NodeManagerConfig.endpoint_num = 0
    NodeManagerConfig.role = None
    NodeManagerConfig.model_name = None
    NodeManagerConfig.hardware_type = None
    NodeManagerConfig.controller_api_dns = None
    NodeManagerConfig.controller_api_port = None
    NodeManagerConfig.ranktable = None


class TestNodeManagerConfig:
    
    @patch.dict('os.environ', {'ROLE': 'both'})  
    @patch('motor.config.node_manager.safe_open')
    def test_init_success(self, mock_safe_open, config_data, hccl_data):
        clear_node_manager_config()
        mock_safe_open.side_effect = create_config_mock(config_data, hccl_data)
        
        config = NodeManagerConfig()
        
        assert config.job_name == "test_job"
        assert isinstance(config.parallel_config, ParallelConfig)
        assert config.role == PDRole.ROLE_U
        assert len(config.device_info) == 8  # Matches hccl_data fixture (8 devices for TYPE_800I_A2)
        assert config.pod_ip == "127.0.0.1"
        assert config.host_ip == "90.90.97.30"
        assert config.ranktable is not None
        assert config.ranktable.status == "completed"
        assert config.ranktable.version == "1.2"
    
    @pytest.mark.parametrize("invalid_config,expected_error,role_env", [
        ({"role": "both"}, "Invalid config json", "both"),  
        ({"parallel_config": {"tp_size": 1, "pp_size": 1}, "role": "invalid", "controller_api_dns": "localhost", "controller_api_port": 8080, "node_manager_port": 8080, "model_name": "vllm"}, "Invalid role value", "invalid"),  # 无效role
    ])
    @patch.dict('os.environ')
    @patch('motor.config.node_manager.safe_open')
    def test_config_validation_errors(self, mock_safe_open, invalid_config, expected_error, role_env):
        clear_node_manager_config()
        
        # Only update if parallel_config is missing (first test case)
        if "parallel_config" not in invalid_config:
            invalid_config.update({
                "controller_api_dns": "localhost", 
                "controller_api_port": 8080,
                "node_manager_port": 8080,
                "model_name": "vllm"
            })
        
        # Set ROLE environment variable
        import os
        os.environ['ROLE'] = role_env
        
        mock_safe_open.side_effect = create_config_mock(
            invalid_config, 
            {"status": "completed", "server_list": []}
        )
        
        with pytest.raises(ValueError, match=expected_error):
            NodeManagerConfig()

    @pytest.mark.parametrize("invalid_hccl,expected_error", [
        # Invalid Ranktable structure (missing required fields)
        ({}, "Invalid HCCL json"),
        ({"status": "pending"}, "Invalid HCCL json"),  # Missing required Ranktable fields
        # Empty server_list will fail device count validation (needs 8 or 16 devices)
        ({"status": "completed", "server_count": "0", "version": "1.0", "server_list": []}, "Invalid device count"),
        # Empty device list will fail device count validation (needs 8 or 16 devices)
        ({"status": "completed", "server_count": "1", "version": "1.0",
          "server_list": [{"server_id": "1", "container_ip": "127.0.0.1", "device": []}]}, "Invalid device count"),
    ])
    @patch.dict('os.environ', {'ROLE': 'both'})
    @patch('motor.config.node_manager.safe_open')
    def test_hccl_validation_errors(self, mock_safe_open, invalid_hccl, expected_error, config_data):
        clear_node_manager_config()
        mock_safe_open.side_effect = create_config_mock(config_data, invalid_hccl)
        
        # All cases should raise ValueError due to device count validation
        with pytest.raises(ValueError, match=expected_error):
            NodeManagerConfig()
    
    @patch.dict('os.environ', {'ROLE': 'both'})
    @patch('motor.config.node_manager.safe_open')
    def test_generate_endpoint_ports(self, mock_safe_open, config_data, hccl_data):
        clear_node_manager_config()
        # Update config_data to have dp_size=2 to get 2 endpoints
        config_data_with_dp = config_data.copy()
        config_data_with_dp["parallel_config"] = {"tp_size": 2, "pp_size": 1, "dp_size": 2}
        mock_safe_open.side_effect = create_config_mock(config_data_with_dp, hccl_data)
        config = NodeManagerConfig()

        assert config.endpoint_num == config.parallel_config.dp_size
        assert len(config.mgmt_ports) == config.endpoint_num
        assert len(config.service_ports) == config.endpoint_num
        assert config.mgmt_ports[0] == "10001"
        assert config.service_ports[0] == "10000"
        assert config.mgmt_ports[1] == "10003"
        assert config.service_ports[1] == "10002"
    
    @patch.dict('os.environ', {'ROLE': 'both'})
    @patch('motor.config.node_manager.safe_open')
    def test_singleton_behavior(self, mock_safe_open, config_data, hccl_data):
        clear_node_manager_config()
        mock_safe_open.side_effect = create_config_mock(config_data, hccl_data)
        config1 = NodeManagerConfig()
        config2 = NodeManagerConfig()
        assert config1 is config2
    
    def test_real_hccl_files_exist(self):
        current_dir = os.path.dirname(__file__)
        project_root = os.path.join(current_dir, '..', '..')
        
        hccl_files = [
            os.path.join(project_root, "tests", "jsons", "hccl_a2.json"),
            os.path.join(project_root, "tests", "jsons", "hccl_a3.json")
        ]
        
        for file_path in hccl_files:
            assert os.path.exists(file_path), f"测试文件不存在: {file_path}"
            
            with open(file_path, 'r') as f:
                data = json.load(f)
                assert data["status"] == "completed"
    
    @patch.dict('os.environ', {'ROLE': 'both'})
    @patch('motor.config.node_manager.safe_open')
    def test_hccl_ranktable_creation(self, mock_safe_open, config_data, hccl_data):
        """Test that ranktable is properly created from HCCL data"""
        clear_node_manager_config()
        mock_safe_open.side_effect = create_config_mock(config_data, hccl_data)
        config = NodeManagerConfig()
        
        # Verify ranktable was created
        assert config.ranktable is not None
        assert config.ranktable.status == "completed"
        assert config.ranktable.version == "1.2"
        assert config.ranktable.server_count == "1"
        assert len(config.ranktable.server_list) == 1
        assert config.ranktable.server_list[0].server_id == "90.90.97.30"
        assert config.ranktable.server_list[0].container_ip == "127.0.0.1"
    
    @patch.dict('os.environ', {'ROLE': 'both'})
    @patch('motor.config.node_manager.safe_open')
    def test_hccl_with_super_device_id(self, mock_safe_open, config_data):
        """Test parsing HCCL with super_device_id"""
        clear_node_manager_config()
        
        # Need 8 devices for TYPE_800I_A2 hardware type
        hccl_with_super = {
            "status": "completed",
            "server_count": "1",
            "version": "1.0",
            "server_list": [{
                "server_id": "1",
                "container_ip": "192.168.1.100",
                "device": [
                    {"device_id": str(i), "device_ip": f"192.168.1.{i+1}", "rank_id": str(i), "super_device_id": f"12345{i}"}
                    for i in range(8)  # 8 devices for TYPE_800I_A2
                ]
            }]
        }
        
        mock_safe_open.side_effect = create_config_mock(config_data, hccl_with_super)
        config = NodeManagerConfig()
        
        assert len(config.device_info) == 8
        assert config.device_info[0].super_device_id == "123450"
        assert config.device_info[1].super_device_id == "123451"
    
    @patch.dict('os.environ', {'ROLE': 'both'})
    @patch('motor.config.node_manager.safe_open')
    def test_hccl_empty_server_list(self, mock_safe_open, config_data):
        """Test parsing HCCL with empty server_list (should fail device count validation)"""
        clear_node_manager_config()
        
        hccl_empty = {
            "status": "completed",
            "server_count": "0",
            "version": "1.0",
            "server_list": []
        }
        
        mock_safe_open.side_effect = create_config_mock(config_data, hccl_empty)
        
        # Should raise ValueError due to device count validation (needs 8 or 16 devices)
        with pytest.raises(ValueError, match="Invalid device count"):
            NodeManagerConfig()
    
    @patch.dict('os.environ', {'ROLE': 'both'})
    @patch('motor.config.node_manager.safe_open')
    def test_hccl_empty_device_list(self, mock_safe_open, config_data):
        """Test parsing HCCL with empty device list (should fail device count validation)"""
        clear_node_manager_config()
        
        hccl_no_devices = {
            "status": "completed",
            "server_count": "1",
            "version": "1.0",
            "server_list": [{
                "server_id": "1",
                "host_ip": "192.168.1.100",
                "container_ip": "192.168.1.100",
                "device": []
            }]
        }
        
        mock_safe_open.side_effect = create_config_mock(config_data, hccl_no_devices)
        
        # Should raise ValueError due to device count validation (needs 8 or 16 devices)
        with pytest.raises(ValueError, match="Invalid device count"):
            NodeManagerConfig()
