# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""
FaultManager test cases.

Test cases are organized according to the following 5 logical blocks:
1. Initialization
2. Persistence and Recovery
3. Start and Update Methods
4. Dynamic Configuration Update
6. Instance and Node status Updating
7. Strategy Center Processing
"""
import pytest
from unittest.mock import Mock, patch, MagicMock

from motor.common.resources.instance import Instance, NodeManagerInfo
from motor.config.controller import ControllerConfig

# Import FaultManager and related classes after mocking
from motor.controller.fault_tolerance.fault_manager import (
    FaultManager,
    NodeMetadata,
    InstanceMetadata
)
from motor.controller.core import ObserverEvent
from motor.controller.fault_tolerance.k8s.cluster_fault_codes import (
    NodeStatus,
    FaultLevel,
    FaultType,
    FaultInfo,
    SpecialFaultCode,
)

# Test constants
TEST_IPS = ["192.168.1.1", "192.168.1.2", "192.168.1.99"]
TEST_PORT = "8080"
TEST_NODE_NAMES = ["node_0", "node_1"]
TEST_FAULT_CODES = [0x1234, 0x2000, 0x3000, 0x3001, 0x4000, 0x00f1fef5]


def FI(*, fault_type, npu_name, fault_code, fault_level):
    """Short constructor for reusable FaultInfo constants in tests."""
    return FaultInfo(
        fault_type=fault_type,
        npu_name=npu_name,
        fault_code=fault_code,
        fault_level=fault_level,
    )


FAULT_DEVICE_L1_0x1000 = FI(
    fault_type=FaultType.CARD_UNHEALTHY, npu_name="npu0", fault_code=0x1000, fault_level=FaultLevel.L1
)
FAULT_DEVICE_L2_0x1000 = FI(
    fault_type=FaultType.CARD_UNHEALTHY, npu_name="npu0", fault_code=0x1000, fault_level=FaultLevel.L2
)
FAULT_DEVICE_L2 = FI(
    fault_type=FaultType.CARD_UNHEALTHY, npu_name="npu0", fault_code=0x2000, fault_level=FaultLevel.L2
)
FAULT_DEVICE_L3 = FI(
    fault_type=FaultType.CARD_UNHEALTHY, npu_name="npu0", fault_code=0x2000, fault_level=FaultLevel.L3
)
FAULT_SWITCH_L2 = FI(
    fault_type=FaultType.CARD_NETWORK_UNHEALTHY, npu_name="switch0", fault_code=0x2000, fault_level=FaultLevel.L2
)
FAULT_NODE_L3 = FI(
    fault_type=FaultType.NODE_UNHEALTHY, npu_name="", fault_code=0x3000, fault_level=FaultLevel.L3
)
FAULT_CM_DEVICE_L3_0x1234 = FI(
    fault_type=FaultType.CARD_UNHEALTHY, npu_name="npu0", fault_code=0x1234, fault_level=FaultLevel.L3
)
FAULT_CM_SWITCH_L2_0x5678 = FI(
    fault_type=FaultType.CARD_NETWORK_UNHEALTHY, npu_name="switch0", fault_code=0x5678, fault_level=FaultLevel.L2
)


def _assert_instance_fault(instance, *, fault_level, fault_code):
    assert instance.fault_level == fault_level
    assert instance.fault_code == fault_code


def _assert_fault_info(fault, *, fault_level, fault_code, fault_type):
    assert fault is not None
    assert fault.fault_level == fault_level
    assert fault.fault_code == fault_code
    assert fault.fault_type == fault_type


def _etcd_node_entry(*, pod_ip, host_ip, instance_id, node_status, fault_infos):
    return {
        "pod_ip": pod_ip,
        "host_ip": host_ip,
        "instance_id": instance_id,
        "node_status": node_status.value,
        "fault_infos": fault_infos,
    }


def _etcd_instance_entry(*, instance_id, fault_level, fault_code):
    return {"instance_id": instance_id, "fault_level": fault_level.value, "fault_code": fault_code}


@pytest.fixture(autouse=True)
def mock_etcd_client():
    """Mock EtcdClient to avoid real ETCD operations in tests"""
    with patch('motor.controller.fault_tolerance.fault_manager.EtcdClient') as mock_etcd_class:
        mock_client = MagicMock()
        mock_client.persist_data.return_value = True
        mock_client.restore_data.return_value = None
        mock_etcd_class.return_value = mock_client
        yield mock_client


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Setup and teardown for each test"""
    from motor.common.utils.singleton import ThreadSafeSingleton
    # Clear singleton instances before each test
    if FaultManager in ThreadSafeSingleton._instances:
        fault_manager = ThreadSafeSingleton._instances[FaultManager]
        fault_manager.stop()
        del ThreadSafeSingleton._instances[FaultManager]


@pytest.fixture
def fault_manager():
    """Create a basic FaultManager instance for testing"""
    config = ControllerConfig()
    return FaultManager(config)


@pytest.fixture
def fault_manager_with_instances():
    """Create a FaultManager instance with pre-configured instances and nodes"""
    with patch('motor.controller.fault_tolerance.fault_manager.EtcdClient') as mock_etcd_class:
        mock_client = MagicMock()
        mock_client.persist_data.return_value = True
        mock_client.restore_data.return_value = None
        mock_etcd_class.return_value = mock_client

        config = ControllerConfig()
        manager = FaultManager(config)

        ins_metadata1 = InstanceMetadata(instance_id=1)
        manager.instances[1] = ins_metadata1
        manager.nodes["10.0.0.1"] = NodeMetadata(
            pod_ip="192.168.1.1", host_ip="10.0.0.1", instance_id=1
        )
        manager.nodes["10.0.0.2"] = NodeMetadata(
            pod_ip="192.168.1.2", host_ip="10.0.0.2", instance_id=1
        )

        ins_metadata2 = InstanceMetadata(instance_id=2)
        manager.instances[2] = ins_metadata2
        manager.nodes["10.0.0.3"] = NodeMetadata(
            pod_ip="192.168.1.3", host_ip="10.0.0.3", instance_id=2
        )

        yield manager


@pytest.fixture
def mock_instance():
    """Create a mock instance for testing"""
    instance = Mock(spec=Instance)
    instance.id = 1
    instance.job_name = "test_job"
    instance.get_node_managers.return_value = [
        NodeManagerInfo(pod_ip="192.168.1.1", host_ip="10.0.0.1", port="8080")
    ]
    return instance


@pytest.fixture
def mock_instance_manager(mock_instance):
    """Create mock instance manager"""
    with patch('motor.controller.fault_tolerance.fault_manager.InstanceManager') as mock_cls:
        instance_manager = Mock()
        mock_cls.return_value = instance_manager
        instance_manager.get_instance_by_podip = Mock(return_value=mock_instance)
        instance_manager.get_instance = Mock(return_value=mock_instance)
        instance_manager.notify = Mock()
        instance_manager.separate_instance = Mock()
        instance_manager.recover_instance = Mock()
        yield instance_manager


@pytest.fixture
def mock_instance_manager(mock_instance):
    """Create mock instance manager"""
    with patch('motor.controller.fault_tolerance.fault_manager.InstanceManager') as mock_cls:
        instance_manager = Mock()
        mock_cls.return_value = instance_manager
        instance_manager.get_instance_by_podip = Mock(return_value=mock_instance)
        instance_manager.get_instance = Mock(return_value=mock_instance)
        instance_manager.notify = Mock()
        instance_manager.separate_instance = Mock()
        instance_manager.recover_instance = Mock()
        yield instance_manager


# =============================================================================
# 1. Initialization
# =============================================================================

def test_fault_manager_initialization(fault_manager):
    """Test FaultManager initialization with default config"""
    assert fault_manager.config is not None
    assert len(fault_manager.nodes) == 0
    assert len(fault_manager.instances) == 0
    assert fault_manager.etcd_client is not None


def test_fault_manager_initialization_with_custom_config():
    """Test FaultManager initialization with custom configuration"""
    config = ControllerConfig()
    config.etcd_config.etcd_host = "custom-etcd-host"
    config.etcd_config.etcd_port = 1234

    with patch('motor.controller.fault_tolerance.fault_manager.EtcdClient') as mock_etcd_class:
        mock_client = MagicMock()
        mock_etcd_class.return_value = mock_client

        manager = FaultManager(config)

        # Verify EtcdClient was called with custom config
        mock_etcd_class.assert_called_once_with(etcd_config=config.etcd_config, tls_config=config.etcd_tls_config)
        assert manager.config is config


def test_fault_manager_singleton_behavior():
    """Test that FaultManager behaves as a singleton"""
    config1 = ControllerConfig()
    config2 = ControllerConfig()

    with patch('motor.controller.fault_tolerance.fault_manager.EtcdClient'):
        manager1 = FaultManager(config1)
        manager2 = FaultManager(config2)

        # They should be the same instance (singleton behavior)
        assert manager1 is manager2


# =============================================================================
# 2. Persistence and Recovery
# =============================================================================

def test_persist_data_success(fault_manager_with_instances):
    """Test successful data persistence to ETCD"""
    manager = fault_manager_with_instances

    with patch.object(manager.etcd_client, 'persist_data', return_value=True) as mock_persist:
        # Call persist_data
        result = manager.persist_data()

        assert result is True

        # Verify persist_data was called once (for combined data)
        assert mock_persist.call_count == 1

        call = mock_persist.call_args
        assert call[0][0] == "/controller/fault_manager"

        stored_data = call[0][1]
        assert 'state' in stored_data

        persistent_state_data = stored_data['state']
        assert 'data' in persistent_state_data
        assert 'version' in persistent_state_data
        assert 'timestamp' in persistent_state_data
        assert 'checksum' in persistent_state_data

        fault_data = persistent_state_data['data']
        assert 'nodes' in fault_data
        assert 'instances' in fault_data
        nodes_data = fault_data['nodes']
        assert isinstance(nodes_data, dict)
        assert len(nodes_data) == 3  # Three nodes in test setup (instance 1: 2 nodes, instance 2: 1 node)

        # Verify node data structure
        node_data = nodes_data["10.0.0.1"]  # Use host_ip as key
        assert node_data['pod_ip'] == TEST_IPS[0]
        assert node_data['host_ip'] == "10.0.0.1"
        assert node_data['node_status'] == NodeStatus.READY.value
        assert 'fault_infos' in node_data

        instances_data = fault_data['instances']
        assert isinstance(instances_data, dict)
        assert len(instances_data) == 2  # Two instances in test setup

        # Verify instance data structure
        instance_data = instances_data["1"]  # instance_id 1 (using str key)
        assert instance_data['instance_id'] == 1
        assert 'fault_level' in instance_data
        assert 'fault_code' in instance_data


def test_persist_data_etcd_failure(fault_manager_with_instances):
    """Test data persistence when ETCD operations fail"""
    manager = fault_manager_with_instances

    with patch.object(manager.etcd_client, 'persist_data', return_value=False) as mock_persist:
        result = manager.persist_data()

        assert result is False # verify persist_data failed


def test_persist_data_exception_handling(fault_manager_with_instances):
    """Test data persistence exception handling"""
    manager = fault_manager_with_instances

    with patch.object(manager.etcd_client, 'persist_data',
                      side_effect=Exception("ETCD connection error")) as mock_persist:
        result = manager.persist_data()

        assert result is False # verify persist_data failed


def test_persist_data_empty_data(fault_manager):
    """Test data persistence with empty data"""
    manager = fault_manager

    # Ensure no data exists
    manager.nodes.clear()
    manager.instances.clear()

    with patch.object(manager.etcd_client, 'persist_data', return_value=True) as mock_persist:
        # Call persist_data
        result = manager.persist_data()

        assert result is True # verify persist_data succeeded

        call = mock_persist.call_args
        stored_data = call[0][1]
        assert 'state' in stored_data

        persistent_state_data = stored_data['state']
        assert 'data' in persistent_state_data

        fault_data = persistent_state_data['data']
        assert 'nodes' in fault_data
        assert 'instances' in fault_data

        nodes_data = fault_data['nodes']
        instances_data = fault_data['instances']
        assert nodes_data == {}
        assert instances_data == {}


def test_restore_data_success(fault_manager):
    """Test successful data restoration from ETCD"""
    from motor.common.etcd.persistent_state import PersistentState
    manager = fault_manager

    fault_data = {
        'nodes': {
            TEST_IPS[0]: _etcd_node_entry(
                pod_ip=TEST_IPS[0],
                host_ip=TEST_IPS[0],
                instance_id=1,
                node_status=NodeStatus.READY,
                fault_infos={
                    TEST_FAULT_CODES[0]: {
                        "fault_type": FaultType.CARD_UNHEALTHY.value,
                        "npu_name": "npu0",
                        "fault_code": TEST_FAULT_CODES[0],
                        "fault_level": FaultLevel.L3.value,
                    }
                },
            )
        },
        'instances': {
            "1": _etcd_instance_entry(instance_id=1, fault_level=FaultLevel.HEALTHY, fault_code=0x0)
        }
    }

    # Create persistent state
    persistent_state = PersistentState(
        data=fault_data,
        version=1,
        timestamp=1234567890.0,
        checksum=""
    )
    persistent_state.checksum = persistent_state.calculate_checksum()

    with patch.object(manager.etcd_client, 'restore_data', return_value={"state": persistent_state}) as mock_restore:
        # Call restore_data
        result = manager.restore_data()

        # Verify success
        assert result is True

        # Verify data was restored
        assert len(manager.nodes) == 1
        assert TEST_IPS[0] in manager.nodes

        node = manager.nodes[TEST_IPS[0]]
        assert node.pod_ip == TEST_IPS[0]
        assert node.host_ip == TEST_IPS[0]
        assert node.node_status == NodeStatus.READY
        assert len(node.fault_infos) == 1
        fault_info = next(iter(node.fault_infos.values()))
        assert fault_info.fault_level == FaultLevel.L3
        assert fault_info.fault_code == TEST_FAULT_CODES[0]

        assert len(manager.instances) == 1
        assert 1 in manager.instances

    instance = manager.instances[1]
    assert instance.instance_id == 1
    _assert_instance_fault(instance, fault_level=FaultLevel.HEALTHY, fault_code=0x0)


def test_restore_data_none_data(fault_manager):
    """Test data restoration when ETCD returns None (no data)"""
    manager = fault_manager

    with patch.object(manager.etcd_client, 'restore_data', return_value=None) as mock_restore:
        result = manager.restore_data()

        assert result is True # verify restore_data succeeded
        assert len(manager.nodes) == 0
        assert len(manager.instances) == 0


def test_restore_data_etcd_failure(fault_manager):
    """Test data restoration when ETCD operations fail"""
    manager = fault_manager

    with patch.object(manager.etcd_client, 'restore_data',
                      side_effect=Exception("ETCD connection error")) as mock_restore:
        result = manager.restore_data()

        assert result is False # verify restore_data failed


def test_restore_data_corrupted_data(fault_manager):
    """Test data restoration with corrupted PersistentState data"""
    from motor.common.etcd.persistent_state import PersistentState
    manager = fault_manager

    # Create corrupted PersistentState with invalid checksum
    corrupted_fault_data = {
        'nodes': {
            TEST_IPS[0]: _etcd_node_entry(
                pod_ip=TEST_IPS[0],
                host_ip=TEST_IPS[0],
                instance_id=1,
                node_status=NodeStatus.READY,
                fault_infos={},
            )
        },
        'instances': {
            "1": _etcd_instance_entry(instance_id=1, fault_level=FaultLevel.HEALTHY, fault_code=0x0)
        }
    }

    corrupted_state = PersistentState(
        data=corrupted_fault_data,
        version=1,
        timestamp=1234567890.0,
        checksum="invalid_checksum"  # Invalid checksum
    )

    with patch.object(manager.etcd_client, 'restore_data', return_value={"state": corrupted_state}) as mock_restore:
        # Call restore_data - should fail due to checksum validation
        result = manager.restore_data()

        assert result is False # verify restore_data failed


# =============================================================================
# 3. Start and Update Methods
# =============================================================================

def test_fault_manager_start_with_persistence_enabled(fault_manager):
    """Test starting FaultManager with persistence enabled"""
    fault_manager.etcd_config.enable_etcd_persistence = True

    with patch.object(fault_manager, 'restore_data', return_value=True) as mock_restore:
        with patch('threading.Thread') as mock_thread:
            fault_manager.start()
            mock_thread.assert_called_once_with(
                target=fault_manager._ft_strategy_center,
                daemon=True,
                name="FaultToleranceStrategyCenter"
            )
            mock_restore.assert_called_once()
            mock_thread.return_value.start.assert_called_once()


def test_fault_manager_start_with_persistence_disabled(fault_manager):
    """Test starting FaultManager with persistence disabled"""
    fault_manager.etcd_config.enable_etcd_persistence = False

    with patch.object(fault_manager, 'restore_data') as mock_restore:
        with patch('threading.Thread') as mock_thread:
            fault_manager.start()
            mock_thread.assert_called_once_with(
                target=fault_manager._ft_strategy_center,
                daemon=True,
                name="FaultToleranceStrategyCenter"
            )
            mock_restore.assert_not_called()
            mock_thread.return_value.start.assert_called_once()


def test_fault_manager_start_restore_data_failed(fault_manager):
    """Test starting FaultManager when restore_data fails"""
    fault_manager.etcd_config.enable_etcd_persistence = True

    with patch.object(fault_manager, 'restore_data', return_value=False) as mock_restore:
        with patch('threading.Thread') as mock_thread:
            with patch('motor.controller.fault_tolerance.fault_manager.logger') as mock_logger:
                fault_manager.start()
                mock_thread.assert_called_once_with(
                    target=fault_manager._ft_strategy_center,
                    daemon=True,
                    name="FaultToleranceStrategyCenter"
                )
                mock_restore.assert_called_once()
                mock_logger.warning.assert_called_once_with(
                    "Failed to restore fault manager's data from ETCD, start with empty state"
                )
                mock_thread.return_value.start.assert_called_once()


def test_fault_manager_start_with_stop_event_reset(fault_manager):
    """Test starting FaultManager when stop_event was previously set"""
    # Set stop_event initially
    fault_manager.stop_event.set()

    with patch.object(fault_manager, 'restore_data', return_value=True):
        with patch('threading.Thread'):
            fault_manager.start()

            assert not fault_manager.stop_event.is_set()


def test_update_instance_initial(fault_manager, mock_instance):
    """Test update method with INSTANCE_INITIAL event"""
    with patch.object(fault_manager, '_handle_instance_initial') as mock_handler:
        fault_manager.update(mock_instance, ObserverEvent.INSTANCE_INITIAL)

        mock_handler.assert_called_once_with(mock_instance)


def test_update_instance_removed(fault_manager, mock_instance):
    """Test update method with INSTANCE_REMOVED event"""
    with patch.object(fault_manager, '_handle_instance_removed') as mock_handler:
        fault_manager.update(mock_instance, ObserverEvent.INSTANCE_REMOVED)

        mock_handler.assert_called_once_with(mock_instance)


def test_handle_instance_initial_preserves_fault_info(fault_manager):
    """Test _handle_instance_initial preserves existing node fault information"""
    # Create a mock instance
    instance = Mock()
    instance.id = 1
    instance.job_name = "test_job"

    # Create mock node managers
    node_mgr1 = Mock()
    node_mgr1.host_ip = "10.0.0.1"
    node_mgr1.pod_ip = "192.168.1.1"

    instance.get_node_managers.return_value = [node_mgr1]

    # First, manually add a node with fault info to simulate existing state
    existing_node = NodeMetadata(
        pod_ip="192.168.1.100",  # Different pod_ip to test update
        host_ip="10.0.0.1",
        instance_id=999,  # Different instance_id to test update
        node_status=NodeStatus.READY,
        fault_infos={FAULT_DEVICE_L2_0x1000.fault_code: FAULT_DEVICE_L2_0x1000}  # This should be preserved
    )

    with fault_manager.lock:
        fault_manager.nodes["10.0.0.1"] = existing_node

    # Call _handle_instance_initial
    fault_manager._handle_instance_initial(instance)

    # Verify the node still exists and fault info is preserved
    assert "10.0.0.1" in fault_manager.nodes
    updated_node = fault_manager.nodes["10.0.0.1"]

    # Verify pod_ip and instance_id were updated
    assert updated_node.pod_ip == "192.168.1.1"
    assert updated_node.instance_id == 1

    # Verify fault info was preserved
    assert len(updated_node.fault_infos) == 1
    fault_info = next(iter(updated_node.fault_infos.values()))
    assert fault_info.fault_type == FaultType.CARD_UNHEALTHY
    assert fault_info.npu_name == "npu0"
    assert fault_info.fault_code == 0x1000
    assert fault_info.fault_level == FaultLevel.L2

    # Verify instance was created
    assert 1 in fault_manager.instances


# =============================================================================
# 4. Dynamic Configuration Update
# =============================================================================

def test_update_config():
    """Test update_config method updates configuration and recreates ETCD client"""
    # Create FaultManager with mocked dependencies
    with patch('motor.controller.fault_tolerance.fault_manager.EtcdClient') as mock_etcd_class:
        mock_client = MagicMock()
        mock_client.persist_data.return_value = True
        mock_client.restore_data.return_value = None
        mock_etcd_class.return_value = mock_client

        # Create FaultManager instance
        config = ControllerConfig()
        manager = FaultManager(config)

        # Create new config with different ETCD settings
        new_config = ControllerConfig()
        new_config.etcd_config.etcd_host = "new-etcd-host"
        new_config.etcd_config.etcd_port = 2380
        new_config.etcd_config.etcd_timeout = 30.0
        new_config.etcd_config.enable_etcd_persistence = True

        mock_etcd_class.reset_mock()

        manager.update_config(new_config)

        assert manager.config is new_config
        assert manager.config.etcd_config.etcd_host == "new-etcd-host"
        assert manager.config.etcd_config.etcd_port == 2380
        assert manager.config.etcd_config.etcd_timeout == 30.0

        # Verify ETCD client constructor was called with new config
        mock_etcd_class.assert_called_once_with(etcd_config=new_config.etcd_config,
                                                tls_config=config.etcd_tls_config)


@pytest.mark.parametrize("fault", [FAULT_CM_DEVICE_L3_0x1234, FAULT_CM_SWITCH_L2_0x5678,],)
def test_handle_configmap_update_with_faults_parametrized(fault_manager, fault):
    """Test handling ConfigMap update with device/switch faults (parametrized)."""
    host_ip = "10.0.0.1"
    fault_manager.nodes[host_ip] = NodeMetadata(pod_ip="192.168.1.1", host_ip=host_ip, instance_id=1)

    fault_manager._handle_fault_info_update([fault], host_ip)
    node = fault_manager.nodes[host_ip]
    assert len(node.fault_infos) == 1
    _assert_fault_info(
        next(iter(node.fault_infos.values())),
        fault_level=fault.fault_level,
        fault_code=fault.fault_code,
        fault_type=fault.fault_type,
    )


# =============================================================================
# 6. Instance and Server status Updating
# =============================================================================

def test_handle_node_status_update_adds_node_reboot_fault_with_L6(fault_manager):
    """Test that node NOT_READY adds a NODE_REBOOT fault with level L6"""
    host_ip = "10.0.0.1"
    fault_manager.nodes[host_ip] = NodeMetadata(
        pod_ip="192.168.1.1", host_ip=host_ip, instance_id=1
    )

    # Trigger NOT_READY status to add node reboot fault
    fault_manager._handle_node_status_update(NodeStatus.NOT_READY, host_ip)

    # Verify NODE_REBOOT fault exists and has level L6
    node = fault_manager.nodes[host_ip]
    assert SpecialFaultCode.NODE_REBOOT in node.fault_infos
    reboot_fault = node.fault_infos[SpecialFaultCode.NODE_REBOOT]
    assert reboot_fault.fault_level == FaultLevel.L6


def test_refresh_instance_fault_level_instance_not_found(fault_manager):
    """Test _refresh_instance_fault_level when instance is not found"""
    with patch('motor.controller.fault_tolerance.fault_manager.logger') as mock_logger:
        fault_manager._refresh_instance_fault_level(999)

        mock_logger.warning.assert_called_once_with(
            "Instance %d not found, skipping fault level refresh", 999
        )


def test_refresh_instance_fault_level_instance_not_found(fault_manager_with_instances):
    """Test _refresh_instance_fault_level when instance is not found"""
    manager = fault_manager_with_instances

    with patch('motor.controller.fault_tolerance.fault_manager.logger') as mock_logger:
        manager._refresh_instance_fault_level(999)

        mock_logger.warning.assert_called_once_with(
            "Instance %d not found, skipping fault level refresh", 999
        )


def test_refresh_instance_fault_level_no_device_faults(fault_manager_with_instances):
    """Test _refresh_instance_fault_level when instance has no device faults"""
    manager = fault_manager_with_instances
    instance = manager.instances[1]
    instance.fault_level = FaultLevel.L3  # Set to unhealthy initially

    with patch('motor.controller.fault_tolerance.fault_manager.InstanceManager') as mock_im_class, \
         patch('motor.controller.fault_tolerance.fault_manager.logger') as mock_logger:
        mock_im = MagicMock()
        mock_im_class.return_value = mock_im

        manager._refresh_instance_fault_level(1)

        # Should reset to healthy state
        assert instance.fault_level == FaultLevel.HEALTHY
        assert instance.fault_code == 0x0
        mock_logger.info.assert_called_once_with("Instance %d reset to healthy state", 1)

        # Should recover instance from forced separation
        mock_im.recover_instance.assert_called_once_with(1)


def test_refresh_instance_fault_level_with_device_faults(fault_manager_with_instances):
    """Test _refresh_instance_fault_level when instance has device faults"""
    manager = fault_manager_with_instances

    node = manager.nodes["10.0.0.1"]
    node.fault_infos = {FAULT_DEVICE_L3.fault_code: FAULT_DEVICE_L3}

    instance = manager.instances[1]
    instance.fault_level = FaultLevel.HEALTHY  # Initially healthy

    with patch.object(manager, '_eval_node_status', return_value=next(iter(node.fault_infos.values()))) as mock_eval:
        with patch('motor.controller.fault_tolerance.fault_manager.InstanceManager') as mock_im_class:
            mock_im = MagicMock()
            mock_im_class.return_value = mock_im

            with patch('motor.controller.fault_tolerance.fault_manager.logger') as mock_logger:
                manager._refresh_instance_fault_level(1)

                # Should update instance fault level
                _assert_instance_fault(instance, fault_level=FaultLevel.L3, fault_code=0x2000)

                # Should separate instance
                mock_im.separate_instance.assert_called_once_with(1)
                mock_logger.info.assert_called_once_with(
                    "Updated instance %d fault level to %s with code %s",
                    1, FaultLevel.L3, hex(0x2000)
                )


@pytest.mark.parametrize("is_separated,expect_recover", [
    (True, True),   # Instance is separated, should call recover_instance
    (False, False)  # Instance is not separated, should not call recover_instance
])
def test_refresh_instance_fault_level_with_l2_faults(fault_manager_with_instances, is_separated, expect_recover):
    """Test _refresh_instance_fault_level when instance has L2 level faults"""
    manager = fault_manager_with_instances

    # Set up node with L2 fault
    node = manager.nodes["10.0.0.1"]
    node.fault_infos = {FAULT_DEVICE_L2.fault_code: FAULT_DEVICE_L2}

    instance = manager.instances[1]
    instance.fault_level = FaultLevel.HEALTHY  # Initially healthy

    with patch.object(manager, '_eval_node_status', return_value=next(iter(node.fault_infos.values()))) as mock_eval:
        with patch('motor.controller.fault_tolerance.fault_manager.InstanceManager') as mock_im_class:
            mock_im = MagicMock()
            mock_im_class.return_value = mock_im
            # Mock instance separation status
            mock_im.is_instance_separated.return_value = is_separated

            with patch('motor.controller.fault_tolerance.fault_manager.logger') as mock_logger:
                manager._refresh_instance_fault_level(1)

                # Should update instance fault level
                _assert_instance_fault(instance, fault_level=FaultLevel.L2, fault_code=0x2000)

                # Should always check if instance is separated
                mock_im.is_instance_separated.assert_called_once_with(1)

                # Should never separate instance for L2 faults
                mock_im.separate_instance.assert_not_called()

                # Recovery behavior depends on separation status
                if expect_recover:
                    mock_im.recover_instance.assert_called_once_with(1)
                else:
                    mock_im.recover_instance.assert_not_called()
                mock_logger.info.assert_called_once_with(
                    "Updated instance %d fault level to %s with code %s",
                    1, FaultLevel.L2, hex(0x2000)
                )


def test_refresh_instance_fault_level_multiple_nodes(fault_manager_with_instances):
    """Test _refresh_instance_fault_level with multiple nodes having different fault levels"""
    manager = fault_manager_with_instances

    # Set up node 1 with L2 fault
    node1 = manager.nodes["10.0.0.1"]
    node1.fault_infos = {FAULT_DEVICE_L2.fault_code: FAULT_DEVICE_L2}

    # Set up node 2 with L3 fault (higher level)
    node2 = manager.nodes["10.0.0.2"]
    node2.fault_infos = {FAULT_NODE_L3.fault_code: FAULT_NODE_L3}

    instance = manager.instances[1]

    def mock_eval_node_status(host_ip):
        if host_ip == "10.0.0.1":
            return next(iter(node1.fault_infos.values()))
        elif host_ip == "10.0.0.2":
            return next(iter(node2.fault_infos.values()))
        return None

    with patch.object(manager, '_eval_node_status', side_effect=mock_eval_node_status):
        with patch('motor.controller.fault_tolerance.fault_manager.InstanceManager') as mock_im_class:
            mock_im = MagicMock()
            mock_im_class.return_value = mock_im

            with patch('motor.controller.fault_tolerance.fault_manager.logger') as mock_logger:
                manager._refresh_instance_fault_level(1)
                # Should use the highest fault level (L3)
                _assert_instance_fault(instance, fault_level=FaultLevel.L3, fault_code=0x3000)
                mock_im.separate_instance.assert_called_once_with(1)


def test_eval_node_status_node_not_found(fault_manager):
    """Test _eval_node_status when node is not found"""
    result = fault_manager._eval_node_status("nonexistent_host_ip")
    assert result is None


def test_eval_node_status_healthy_node(fault_manager_with_instances):
    """Test _eval_node_status for a healthy node"""
    manager = fault_manager_with_instances
    node = manager.nodes["10.0.0.1"]
    node.node_status = NodeStatus.READY

    result = manager._eval_node_status("10.0.0.1")
    assert result is None


def test_eval_node_status_unhealthy_node_no_device_faults(fault_manager_with_instances):
    """Test _eval_node_status for unhealthy node with no device faults"""
    manager = fault_manager_with_instances
    node = manager.nodes["10.0.0.1"]
    node.node_status = NodeStatus.READY  # Node is ready, but has no device faults
    node.fault_infos = {}

    result = manager._eval_node_status("10.0.0.1")
    assert result is None


def test_eval_node_status_unhealthy_node_with_device_faults(fault_manager_with_instances):
    """Test _eval_node_status for unhealthy node with device faults"""
    manager = fault_manager_with_instances
    node = manager.nodes["10.0.0.1"]
    node.node_status = NodeStatus.READY  # Node is ready, evaluate device faults
    fault_infos = [
        FAULT_DEVICE_L1_0x1000,
        FAULT_NODE_L3,
        FAULT_SWITCH_L2,
    ]
    node.fault_infos = {fault.fault_code: fault for fault in fault_infos}

    result = manager._eval_node_status("10.0.0.1")

    # Should return the highest fault level (L3)
    _assert_fault_info(result, fault_level=FaultLevel.L3, fault_code=0x3000, fault_type=FaultType.NODE_UNHEALTHY)


def test_eval_node_status_unhealthy_node_single_device_fault(fault_manager_with_instances):
    """Test _eval_node_status for unhealthy node with single device fault"""
    manager = fault_manager_with_instances
    node = manager.nodes["10.0.0.1"]
    node.node_status = NodeStatus.READY  # Node is ready, evaluate device fault
    node.fault_infos = {FAULT_DEVICE_L2.fault_code: FAULT_DEVICE_L2}

    result = manager._eval_node_status("10.0.0.1")

    _assert_fault_info(result, fault_level=FaultLevel.L2, fault_code=0x2000, fault_type=FaultType.CARD_UNHEALTHY)


# =============================================================================
# 7. Strategy Center Processing
# =============================================================================

def test_ft_strategy_center_initialization(fault_manager):
    """Test fault tolerance strategy center initialization"""
    # The strategy center thread should be initialized
    assert hasattr(fault_manager, 'ft_strategy_center_thread')
    assert fault_manager.ft_strategy_center_thread is None  # Initially None, started later


def test_process_instance_strategy_with_healthy_instance(fault_manager_with_instances):
    """Test processing strategy for a healthy instance"""
    manager = fault_manager_with_instances

    # Set instance 1 to healthy state
    manager.instances[1].fault_level = FaultLevel.HEALTHY

    with patch('motor.controller.fault_tolerance.fault_manager.InstanceManager') as mock_im_class:
        mock_im = MagicMock()
        mock_im_class.return_value = mock_im

        manager._process_instance_strategy(1)

        # For healthy instances, no recovery action should be taken
        mock_im.recover_instance.assert_not_called()
        mock_im.separate_instance.assert_not_called()


def test_process_instance_strategy_with_unhealthy_instance(fault_manager_with_instances):
    """Test processing strategy for an unhealthy instance"""
    manager = fault_manager_with_instances

    # Set instance 1 to unhealthy state with L4 fault level
    manager.instances[1].fault_level = FaultLevel.L4

    # Mock InstanceManager to return a decode instance for L4 strategy lookup
    with patch('motor.controller.core.instance_manager.InstanceManager') as mock_im_class:
        mock_im = MagicMock()
        mock_im_class.return_value = mock_im
        mock_instance = MagicMock()
        mock_instance.role = "decode"
        mock_im.get_instance.return_value = mock_instance

        # Enable scale P2D in config
        manager.config.fault_tolerance_config.enable_scale_p2d = True

        # Process instance strategy - this should set up a strategy for L4 faults
        manager._process_instance_strategy(1)

        # Check that a strategy was set for the instance (L4 decode instance should get ScaleP2DStrategy)
        assert manager.instances[1].strategy is not None
        assert manager.instances[1].fault_level == FaultLevel.L4


def test_ft_strategy_center_processing(fault_manager_with_instances):
    """Test _ft_strategy_center processes instances correctly"""
    manager = fault_manager_with_instances

    # Mock the time.sleep to avoid actual sleeping
    with patch('time.sleep') as mock_sleep:
        # Mock _process_instance_strategy to track calls
        with patch.object(manager, '_process_instance_strategy') as mock_process:
            # Simulate the loop by raising KeyboardInterrupt after first iteration
            mock_sleep.side_effect = KeyboardInterrupt()

            with pytest.raises(KeyboardInterrupt):
                manager._ft_strategy_center()

            # Verify instances were processed
            assert mock_process.call_count == 2  # Two instances in the fixture
            mock_process.assert_any_call(1)
            mock_process.assert_any_call(2)

            # Verify sleep was called with check interval
            mock_sleep.assert_called_once_with(manager.strategy_center_check_interval)


def test_ft_strategy_center_with_empty_instances(fault_manager):
    """Test _ft_strategy_center with no instances"""
    # Mock the time.sleep to avoid actual sleeping and interrupt the loop
    with patch('time.sleep', side_effect=KeyboardInterrupt()):
        with patch.object(fault_manager, '_process_instance_strategy') as mock_process:
            with pytest.raises(KeyboardInterrupt):
                fault_manager._ft_strategy_center()

            # No instances to process
            mock_process.assert_not_called()


def test_ft_strategy_center_stop_event_handling(fault_manager_with_instances):
    """Test _ft_strategy_center respects stop event"""
    manager = fault_manager_with_instances

    # Set stop event before starting
    manager.stop_event.set()

    with patch('time.sleep') as mock_sleep:
        with patch.object(manager, '_process_instance_strategy') as mock_process:
            # Should exit immediately due to stop_event being set
            manager._ft_strategy_center()

            # Should not process any instances or sleep
            mock_process.assert_not_called()
            mock_sleep.assert_not_called()