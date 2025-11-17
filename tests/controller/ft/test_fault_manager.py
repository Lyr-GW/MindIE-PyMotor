import pytest
import threading
import sys
from unittest.mock import Mock, patch, MagicMock

# mock pb
cluster_fault_pb2 = MagicMock()
mock_pb2_grpc = MagicMock()
cluster_fault_pb2.ClientInfo = Mock
cluster_fault_pb2.FaultMsgSignal = Mock
# add cluster pb to system
sys.modules['cluster_fault_pb2'] = cluster_fault_pb2
sys.modules['cluster_fault_pb2_grpc'] = mock_pb2_grpc

from motor.controller.ft.cluster_grpc import cluster_fault_pb2
from motor.controller.core.observer import ObserverEvent
from motor.common.resources.instance import Instance, NodeManagerInfo
from motor.common.utils.singleton import ThreadSafeSingleton

# Import FaultManager and related classes after mocking
from motor.controller.ft.fault_manager import (
    FaultManager,
    ServerMetadata,
    InstanceGroupMetadata,
    InstanceMetadata,
    DeviceFaultInfo,
    Status
)

# Test constants
TEST_IPS = ["192.168.1.1", "192.168.1.2", "192.168.1.99"]
TEST_PORT = "8080"
TEST_NODE_NAMES = ["node_0", "node_1"]
TEST_SERIAL_NUMBERS = ["SN0:06d", "SN1:06d"]
TEST_FAULT_CODES = [0x1234, 0x2000, 0x3000, 0x3001, 0x4000, 0x00f1fef5]


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
    """Create fault manager with proper mocking"""
    # Clear singleton instance before creating new one
    if FaultManager in ThreadSafeSingleton._instances:
        del ThreadSafeSingleton._instances[FaultManager]

    manager, _ , _ = FaultManagerTestHelper.create_mock_fault_manager()
    yield manager
    # cleanup
    if manager is not None and not manager.stop_event.is_set():
        manager.stop()


@pytest.fixture
def fault_manager_with_instances():
    """Create fault manager with test instances and servers"""
    manager, _ , _ = FaultManagerTestHelper.create_fault_manager_with_instances()
    yield manager
    if not manager.stop_event.is_set():
        manager.stop()


@pytest.fixture
def mock_instance():
    """Create mock instance"""
    return FaultManagerTestHelper.create_mock_instance()


@pytest.fixture
def mock_instance_manager(mock_instance):
    """Create mock instance manager"""
    with patch('motor.controller.ft.fault_manager.InstanceManager') as mock_cls:
        instance_manager = Mock()
        mock_cls.return_value = instance_manager
        instance_manager.get_instance_by_podip = Mock(return_value=mock_instance)
        instance_manager.get_instance = Mock(return_value=mock_instance)
        instance_manager.notify = Mock()
        yield instance_manager


class FaultManagerTestHelper:
    """Helper class for common FaultManager test setup"""

    @staticmethod
    def create_mock_instance(instance_id=100, job_name="test_job", group_id=1, role="prefill",
                           pod_ip=TEST_IPS[0], host_ip=TEST_IPS[0], port=TEST_PORT):
        """Create a mock instance with specified parameters"""
        mock_instance = Mock(spec=Instance)
        mock_instance.id = instance_id
        mock_instance.job_name = job_name
        mock_instance.group_id = group_id
        mock_instance.role = role
        mock_instance.update_instance_status = Mock()
        mock_instance.get_node_managers.return_value = [
            NodeManagerInfo(pod_ip=pod_ip, host_ip=host_ip, port=port)
        ]
        mock_instance.get_endpoints.return_value = {}
        return mock_instance

    @staticmethod
    def create_device_fault_info(device_type="npu", rank_id=0, fault_code=TEST_FAULT_CODES[0],
                                fault_level="L3", fault_type="HARDWARE", fault_reason="Memory failure"):
        """Create a DeviceFaultInfo object"""
        return DeviceFaultInfo(
            device_type=device_type,
            rank_id=rank_id,
            fault_code=fault_code,
            fault_level=fault_level,
            fault_type=fault_type,
            fault_reason=fault_reason
        )

    @staticmethod
    def create_server_metadata(pod_ip=TEST_IPS[0], host_ip=TEST_IPS[0], status=Status.HEALTHY,
                              device_fault_infos=None):
        """Create ServerMetadata object"""
        return ServerMetadata(
            pod_ip=pod_ip,
            host_ip=host_ip,
            status=status,
            device_fault_infos=device_fault_infos or []
        )

    @staticmethod
    def create_instance_metadata(instance_id=100, status=Status.HEALTHY, node_managers=None):
        """Create InstanceMetadata object"""
        if node_managers is None:
            node_managers = [NodeManagerInfo(pod_ip=TEST_IPS[0], host_ip=TEST_IPS[0], port=TEST_PORT)]
        return InstanceMetadata(
            instance_id=instance_id,
            status=status,
            node_managers=node_managers
        )

    @staticmethod
    def create_fault_message(signal_type="fault", node_ip=TEST_IPS[0], node_name=TEST_NODE_NAMES[0],
                           node_sn=TEST_SERIAL_NUMBERS[0], fault_level="unhealthy",
                           device_type="SERVER", fault_codes=None, fault_types=None, fault_reasons=None):
        """Create a mock fault message"""
        fault_msg = cluster_fault_pb2.FaultMsgSignal()
        fault_msg.signalType = signal_type

        if signal_type == "fault":
            node_fault_info = fault_msg.nodeFaultInfo.add()
            node_fault_info.nodeName = node_name
            node_fault_info.nodeIP = node_ip
            node_fault_info.nodeSN = node_sn
            node_fault_info.faultLevel = fault_level

            if device_type and fault_codes:
                device_fault = node_fault_info.faultDevice.add()
                device_fault.deviceId = f"device_{node_ip.split('.')[-1]}"
                device_fault.deviceType = device_type
                device_fault.faultCodes.extend(fault_codes or ["ERR001"])
                device_fault.faultLevel = "CRITICAL"
                device_fault.faultType.extend(fault_types or ["HARDWARE"])
                device_fault.faultReason.extend(fault_reasons or ["Memory failure"])

        return fault_msg

    @staticmethod
    def create_mock_fault_manager():
        """Create a mock fault manager with all necessary mocks"""
        with patch('motor.controller.ft.fault_manager.ClusterNodeClient') as mock_client_class:
            with patch('motor.controller.ft.fault_manager.generate_strategy_map') as mock_strategy_map:
                with patch('concurrent.futures.ThreadPoolExecutor') as mockexecutor_class:
                    # Mock cluster client
                    mock_client = Mock()
                    mock_client_class.return_value = mock_client
                    mock_client.register = Mock(return_value=True)
                    mock_client.subscribe_fault_messages = Mock()
                    mock_client.close = Mock()

                    # Mock strategy map
                    def create_mock_strategy_class():
                        mock_strategy = Mock()
                        # make sure the strategy will not finished immediately.
                        mock_strategy.is_finished.return_value = False
                        return mock_strategy

                    mock_strategy_map.return_value = {
                        "L0": Mock(return_value=None),  # Healthy instances
                        "L1": Mock(return_value=None),
                        "L2": Mock(return_value=create_mock_strategy_class),
                        "L3": Mock(return_value=create_mock_strategy_class),
                        "L4": Mock(return_value=create_mock_strategy_class),
                        "L5": Mock(return_value=create_mock_strategy_class),
                        "L6": Mock(return_value=create_mock_strategy_class),
                    }

                    # Mock executor
                    mockexecutor = Mock()
                    mockexecutor_class.return_value = mockexecutor

                    from motor.config.controller import ControllerConfig
                    config = ControllerConfig()
                    manager = FaultManager(config)

                    return manager, mockexecutor, mock_strategy_map

    @staticmethod
    def create_fault_manager_with_instances():
        """Create fault manager with test instances and servers"""
        manager, mockexecutor, mock_strategy_map = FaultManagerTestHelper.create_mock_fault_manager()

        # Create test instances using helper methods
        manager.instances[1] = FaultManagerTestHelper.create_instance_metadata(
            instance_id=1,
            node_managers=[NodeManagerInfo(pod_ip=TEST_IPS[0], host_ip=TEST_IPS[0], port=TEST_PORT)]
        )
        manager.instances[2] = FaultManagerTestHelper.create_instance_metadata(
            instance_id=2,
            node_managers=[NodeManagerInfo(pod_ip=TEST_IPS[1], host_ip=TEST_IPS[1], port=TEST_PORT)]
        )

        # Create test servers using helper methods
        manager.servers[TEST_IPS[0]] = FaultManagerTestHelper.create_server_metadata(
            pod_ip=TEST_IPS[0], host_ip=TEST_IPS[0]
        )
        manager.servers[TEST_IPS[1]] = FaultManagerTestHelper.create_server_metadata(
            pod_ip=TEST_IPS[1], host_ip=TEST_IPS[1]
        )

        return manager, mockexecutor, mock_strategy_map


def test_initialization(fault_manager):
    """Test FaultManager initialization"""
    assert isinstance(fault_manager.stop_event, threading.Event)
    assert isinstance(fault_manager.lock, type(threading.Lock()))
    assert isinstance(fault_manager.servers, dict)
    assert isinstance(fault_manager.instances, dict)
    assert isinstance(fault_manager.groups, dict)

    # Check thread creation (threads are created but not started)
    assert not fault_manager.server_status_subscriber_thread.is_alive()
    assert not fault_manager.ft_strategy_center_thread.is_alive()
    assert fault_manager.server_status_subscriber_thread.daemon is True
    assert fault_manager.ft_strategy_center_thread.daemon is True

@pytest.mark.parametrize("dataclass_name,expected_attrs", [
    ("DeviceFaultInfo", {
        "device_type": "npu",
        "rank_id": 0,
        "fault_code": TEST_FAULT_CODES[0],
        "fault_level": "L3",
        "fault_type": "HARDWARE",
        "fault_reason": "Memory failure"
    }),
    ("ServerMetadata", {
        "pod_ip": TEST_IPS[0],
        "host_ip": TEST_IPS[0],
        "status": Status.HEALTHY,
        "device_fault_infos": []
    }),
    ("InstanceMetadata", {
        "instance_id": 100,
        "status": Status.HEALTHY,
        "node_managers": [NodeManagerInfo(pod_ip=TEST_IPS[0], host_ip=TEST_IPS[0], port=TEST_PORT)],
        "fault_level": "L0",
        "fault_code": 0x0,
        "strategy": None
    }),
    ("InstanceGroupMetadata", {
        "id": 1,
        "p_ids": [100, 101],
        "d_ids": [200, 201]
    })
])
def test_dataclass_creation(dataclass_name, expected_attrs):
    """Test dataclass creation for various metadata classes"""
    if dataclass_name == "DeviceFaultInfo":
        obj = DeviceFaultInfo(**{k: v for k, v in expected_attrs.items()
                                 if k in ["device_type", "rank_id", "fault_code",
                                         "fault_level", "fault_type", "fault_reason"]})
    elif dataclass_name == "ServerMetadata":
        obj = ServerMetadata(**{k: v for k, v in expected_attrs.items()
                                if k in ["pod_ip", "host_ip", "status", "device_fault_infos"]})
    elif dataclass_name == "InstanceMetadata":
        obj = InstanceMetadata(**{k: v for k, v in expected_attrs.items()
                                  if k in ["instance_id", "status", "node_managers"]})
    elif dataclass_name == "InstanceGroupMetadata":
        obj = InstanceGroupMetadata(**{k: v for k, v in expected_attrs.items()
                                       if k in ["id", "p_ids", "d_ids"]})

    for attr, expected_value in expected_attrs.items():
        assert getattr(obj, attr) == expected_value

@pytest.mark.parametrize("signal_type,fault_level,expected_server_status,should_update_instances", [
    ("normal", None, None, False),  # Normal signal should return early
    ("fault", "unhealthy", Status.UNHEALTHY, True),  # Unhealthy fault should update server and instances
    ("fault", "healthy", Status.HEALTHY, True),  # Healthy fault should update server and instances
])
def test_process_cluster_fault_message_basic(
        fault_manager, signal_type, fault_level,
        expected_server_status, should_update_instances):
    """Test basic fault message processing for different signal types and fault levels"""
    # Setup server metadata for fault tests
    if signal_type == "fault":
        initial_status = Status.UNHEALTHY if fault_level == "healthy" else Status.HEALTHY
        fault_manager.servers[TEST_IPS[0]] = FaultManagerTestHelper.create_server_metadata(
            status=initial_status
        )

    # Setup instance metadata to test _update_instances_status call
    if should_update_instances:
        fault_manager.instances[1] = FaultManagerTestHelper.create_instance_metadata(instance_id=1)

    # Create fault message using helper
    fault_msg = FaultManagerTestHelper.create_fault_message(
        signal_type=signal_type,
        fault_level=fault_level,
        fault_codes=["ERR001"] if signal_type == "fault" else None
    )

    # Mock update_instances_status to verify it's called
    with patch.object(fault_manager, '_update_instances_status') as mock_update_status:
        fault_manager._process_cluster_fault_message(fault_msg)

        # Verify _update_instances_status was called for fault messages
        if should_update_instances:
            mock_update_status.assert_called_once()
        else:
            mock_update_status.assert_not_called()

    # Verify server status updated for fault messages
    if expected_server_status:
        assert fault_manager.servers[TEST_IPS[0]].status == expected_server_status
        if fault_level == "unhealthy":
            assert len(fault_manager.servers[TEST_IPS[0]].device_fault_infos) == 1

@pytest.mark.parametrize("test_case,expected_behavior", [
    ("unknown_server", {"creates_server": False, "raises_exception": False}),
    ("none_input", {"raises_exception": False}),
    ("missing_signalType", {"raises_exception": False}),
    ("missing_nodeFaultInfo", {"raises_exception": False}),
])
def test_process_cluster_fault_message_edge_cases(fault_manager, test_case, expected_behavior):
    """Test fault message processing edge cases"""
    if test_case == "unknown_server":
        fault_msg = FaultManagerTestHelper.create_fault_message(
            node_ip=TEST_IPS[2],  # Unknown server IP
            fault_level="healthy"
        )
        fault_manager._process_cluster_fault_message(fault_msg)
        assert TEST_IPS[2] not in fault_manager.servers

    elif test_case == "none_input":
        fault_manager._process_cluster_fault_message(None)

    elif test_case == "missing_signalType":
        fault_msg = cluster_fault_pb2.FaultMsgSignal()
        # Don't set signalType
        fault_manager._process_cluster_fault_message(fault_msg)

    elif test_case == "missing_nodeFaultInfo":
        fault_msg = cluster_fault_pb2.FaultMsgSignal()
        fault_msg.signalType = "fault"
        # Don't set nodeFaultInfo
        fault_manager._process_cluster_fault_message(fault_msg)

def test_process_cluster_fault_message_large_device_faults(fault_manager):
    """Test processing fault message with large number of device faults - should truncate"""
    # Setup server metadata using helper
    fault_manager.servers[TEST_IPS[0]] = FaultManagerTestHelper.create_server_metadata()

    # Create fault message with many device faults
    fault_msg = cluster_fault_pb2.FaultMsgSignal()
    fault_msg.signalType = "fault"

    # Create node fault info with many device faults
    node_fault_info = fault_msg.nodeFaultInfo.add()
    node_fault_info.nodeName = TEST_NODE_NAMES[0]
    node_fault_info.nodeIP = TEST_IPS[0]
    node_fault_info.nodeSN = TEST_SERIAL_NUMBERS[0]
    node_fault_info.faultLevel = "unhealthy"

    # Create many device faults (more than 1000)
    for i in range(1500):
        device_fault = node_fault_info.faultDevice.add()
        device_fault.deviceId = f"device_{i}"
        device_fault.deviceType = "SERVER"
        device_fault.faultCodes.append(f"ERR{i:03d}")
        device_fault.faultLevel = "CRITICAL"
        device_fault.faultType.append("HARDWARE")
        device_fault.faultReason.append(f"Fault reason {i}")

    fault_manager._process_cluster_fault_message(fault_msg)

    # Verify device faults were truncated to 1000
    assert len(fault_manager.servers[TEST_IPS[0]].device_fault_infos) == 1000

def test_process_cluster_fault_message_invalid_nodeinfo(fault_manager):
    """Test processing fault message with invalid node info - should handle gracefully"""
    fault_msg = cluster_fault_pb2.FaultMsgSignal()
    fault_msg.signalType = "fault"

    # Create node info without required fields (nodeIP, faultLevel)
    node_info = fault_msg.nodeFaultInfo.add()
    # Don't set nodeIP or faultLevel to simulate invalid node info

    # Should handle invalid node info gracefully without raising exceptions
    # The method should log warnings and skip processing invalid entries
    # This tests defensive programming - method should be robust against malformed input
    fault_manager._process_cluster_fault_message(fault_msg)  # Should not raise any exception

def test_process_cluster_fault_message_external_call_failure(fault_manager, mock_instance_manager):
    """Test processing fault message when external calls fail - should handle gracefully"""
    # Setup server metadata using helper
    fault_manager.servers[TEST_IPS[0]] = FaultManagerTestHelper.create_server_metadata()

    # Create fault message using helper
    fault_msg = FaultManagerTestHelper.create_fault_message(fault_level="unhealthy")

    # Mock instance manager to raise exception
    mock_instance_manager.get_instance_by_podip.side_effect = Exception("Database connection failed")

    # Should handle external call failure gracefully
    fault_manager._process_cluster_fault_message(fault_msg)

    # Verify server status was still updated despite external call failure
    assert fault_manager.servers[TEST_IPS[0]].status == Status.UNHEALTHY

@pytest.mark.parametrize("server_status,device_faults,expected_result", [
    (Status.HEALTHY, [], None),  # Healthy server returns None
    (Status.UNHEALTHY, [  # Unhealthy server with faults returns highest level fault
        FaultManagerTestHelper.create_device_fault_info(fault_level="L2", fault_code=0x1000),
        FaultManagerTestHelper.create_device_fault_info(fault_level="L4", fault_code=0x2000),
        FaultManagerTestHelper.create_device_fault_info(fault_level="L3", fault_code=0x3000)
    ], ("L4", 0x2000)),
])
def test_eval_server_status(fault_manager, server_status, device_faults, expected_result):
    """Test _eval_server_status with different server states"""
    # Setup server metadata using helper
    fault_manager.servers[TEST_IPS[0]] = FaultManagerTestHelper.create_server_metadata(
        status=server_status,
        device_fault_infos=device_faults
    )

    result = fault_manager._eval_server_status(TEST_IPS[0])

    if expected_result is None:
        assert result is None
    else:
        assert result is not None
        assert result.fault_level == expected_result[0]
        assert result.fault_code == expected_result[1]

def test_eval_server_status_unknown_server(fault_manager):
    """Test _eval_server_status with unknown server"""
    with pytest.raises(ValueError, match=f"Server {TEST_IPS[2]} not found"):
        fault_manager._eval_server_status(TEST_IPS[2])

@pytest.mark.parametrize("test_case,server_configs,expected_fault_level,expected_fault_code", [
    ("healthy_instance", [
        {"ip": TEST_IPS[0], "status": Status.HEALTHY, "faults": []}
    ], "L0", 0x0),
    ("unhealthy_instance", [
        {"ip": TEST_IPS[0], "status": Status.UNHEALTHY, "faults": [
            FaultManagerTestHelper.create_device_fault_info(fault_level="L2", fault_code=0x1000),
            FaultManagerTestHelper.create_device_fault_info(fault_level="L4", fault_code=0x2000),
            FaultManagerTestHelper.create_device_fault_info(fault_level="L3", fault_code=0x3000)
        ]}
    ], "L4", 0x2000),
    ("multiple_servers", [
        {"ip": TEST_IPS[0], "status": Status.UNHEALTHY, "faults": [
            FaultManagerTestHelper.create_device_fault_info(fault_level="L2", fault_code=0x1000)
        ]},
        {"ip": TEST_IPS[1], "status": Status.UNHEALTHY, "faults": [
            FaultManagerTestHelper.create_device_fault_info(fault_level="L5", fault_code=0x3000)
        ]}
    ], "L5", 0x3000),
    ("mixed_servers", [
        {"ip": TEST_IPS[0], "status": Status.HEALTHY, "faults": []},
        {"ip": TEST_IPS[1], "status": Status.UNHEALTHY, "faults": [
            FaultManagerTestHelper.create_device_fault_info(fault_level="L3", fault_code=0x2000)
        ]}
    ], "L3", 0x2000),
])
def test_update_instances_status(fault_manager, test_case, server_configs, expected_fault_level, expected_fault_code):
    """Test _update_instances_status with different server configurations"""
    # Setup servers
    node_managers = []
    for config in server_configs:
        fault_manager.servers[config["ip"]] = FaultManagerTestHelper.create_server_metadata(
            pod_ip=config["ip"], host_ip=config["ip"],
            status=config["status"], device_fault_infos=config["faults"]
        )
        node_managers.append(NodeManagerInfo(pod_ip=config["ip"], host_ip=config["ip"], port=TEST_PORT))

    # Setup instance metadata
    instance_metadata = FaultManagerTestHelper.create_instance_metadata(
        instance_id=1, node_managers=node_managers
    )
    fault_manager.instances[1] = instance_metadata

    fault_manager._update_instances_status()

    # Verify instance metadata updated correctly
    assert instance_metadata.fault_level == expected_fault_level
    assert instance_metadata.fault_code == expected_fault_code

@pytest.mark.parametrize("role,expected_group_ids", [
    ("prefill", {"p_ids": [100], "d_ids": []}),
    ("decode", {"p_ids": [], "d_ids": [200]}),
])
def test_update_instance_added(fault_manager, role, expected_group_ids):
    """Test update method with INSTANCE_ADDED event for different roles"""
    # Create mock instance using helper
    instance_id = 100 if role == "prefill" else 200
    server_ip = TEST_IPS[0] if role == "prefill" else TEST_IPS[1]
    mock_instance = FaultManagerTestHelper.create_mock_instance(
        instance_id=instance_id, role=role, pod_ip=server_ip, host_ip=server_ip
    )

    fault_manager.update(mock_instance, ObserverEvent.INSTANCE_ADDED)

    # Check instance registration
    assert instance_id in fault_manager.instances
    instance_metadata = fault_manager.instances[instance_id]
    assert instance_metadata.instance_id == instance_id
    assert len(instance_metadata.node_managers) == 1

    # Check server metadata creation
    assert server_ip in fault_manager.servers
    server = fault_manager.servers[server_ip]
    assert server.pod_ip == server_ip
    assert server.status == Status.HEALTHY

    # Check group metadata
    assert 1 in fault_manager.groups
    group = fault_manager.groups[1]
    assert group.id == 1
    for id_list, expected_ids in expected_group_ids.items():
        assert getattr(group, id_list) == expected_ids

def test_update_instance_separated(fault_manager, mock_instance):
    """Test update method with INSTANCE_SEPERATED event"""
    # First add the instance
    fault_manager.update(mock_instance, ObserverEvent.INSTANCE_ADDED)

    # Then separate it
    fault_manager.update(mock_instance, ObserverEvent.INSTANCE_SEPERATED)

    # Check that instance is marked as separated but not removed
    assert 100 in fault_manager.instances
    assert fault_manager.instances[100].status == Status.UNHEALTHY
    assert TEST_IPS[0] in fault_manager.servers

    # Check group metadata remains unchanged for separated instance
    group = fault_manager.groups[1]
    assert 100 in group.p_ids  # instance still in group but separated

def test_update_instance_removed(fault_manager, mock_instance):
    """Test update method with INSTANCE_REMOVED event"""
    # First add the instance
    fault_manager.update(mock_instance, ObserverEvent.INSTANCE_ADDED)

    # Then remove it
    fault_manager.update(mock_instance, ObserverEvent.INSTANCE_REMOVED)

    # Check removal
    assert 100 not in fault_manager.instances
    assert TEST_IPS[0] not in fault_manager.servers

    # Check group metadata update - group should be removed when empty
    assert 1 not in fault_manager.groups

def test_update_invalid_event(fault_manager, mock_instance):
    """Test update method with invalid event"""
    with pytest.raises(ValueError, match="Invalid event"):
        fault_manager.update(mock_instance, "INVALID_EVENT")

@pytest.fixture
def fault_manager_with_instances():
    """Create fault manager with test instances and servers"""
    manager, _ , _ = FaultManagerTestHelper.create_fault_manager_with_instances()
    yield manager
    if not manager.stop_event.is_set():
        manager.stop()

@pytest.mark.parametrize("test_case,server_setup,expected_strategy_calls,expected_instance_states", [
    ("healthy_instances", {}, 0, {"strategy": None, "fault_level": "L0", "fault_code": 0x0}),
    ("unhealthy_instances", {
        TEST_IPS[0]: {"status": Status.UNHEALTHY, "faults": [
            FaultManagerTestHelper.create_device_fault_info(fault_level="L3", fault_code=TEST_FAULT_CODES[0])
        ]}
    }, 1, {"strategy": "not_none", "fault_level": "L3", "fault_code": TEST_FAULT_CODES[0]}),
    ("multiple_instances", {
        TEST_IPS[0]: {"status": Status.UNHEALTHY, "faults": [
            FaultManagerTestHelper.create_device_fault_info(fault_level="L3", fault_code=0x3000)
        ]}
    }, 1, {"strategy": "not_none", "fault_level": "L3", "fault_code": 0x3000}),
])
def test_ft_strategy_center_basic(
        fault_manager_with_instances, test_case, server_setup,
        expected_strategy_calls, expected_instance_states):
    """Test ft_strategy_center with different scenarios"""
    manager = fault_manager_with_instances

    # Setup server states
    for ip, config in server_setup.items():
        manager.servers[ip].status = config["status"]
        manager.servers[ip].device_fault_infos = config["faults"]

    # Update instance statuses to reflect server faults
    if server_setup:
        manager._update_instances_status()

    # Mock time.sleep to control the loop execution
    def mock_sleep(seconds):
        raise StopIteration

    with patch('motor.controller.ft.fault_manager.time') as mock_time:
        mock_time.sleep.side_effect = mock_sleep
        try:
            manager._ft_strategy_center()
        except StopIteration:
            pass

    # Verify strategy submission count
    assert manager.executor.submit.call_count == expected_strategy_calls

    # Verify instance states - only check instances that should be affected
    if test_case == "healthy_instances":
        # All instances should be healthy
        for ins_metadata in manager.instances.values():
            assert ins_metadata.strategy is None
            assert ins_metadata.fault_level == "L0"
            assert ins_metadata.fault_code == 0x0
    else:
        # Only instance 1 should be affected in unhealthy cases
        assert manager.instances[1].strategy is not None
        assert manager.instances[1].fault_level == expected_instance_states["fault_level"]
        assert manager.instances[1].fault_code == expected_instance_states["fault_code"]

        # Instance 2 should remain healthy
        assert manager.instances[2].strategy is None
        assert manager.instances[2].fault_level == "L0"
        assert manager.instances[2].fault_code == 0x0

def test_ft_strategy_center_strategy_levels(fault_manager_with_instances):
    """Test different error levels trigger appropriate strategies"""
    manager = fault_manager_with_instances

    # Test L2 level error
    manager.servers[TEST_IPS[0]].status = Status.UNHEALTHY
    manager.servers[TEST_IPS[0]].device_fault_infos = [
        FaultManagerTestHelper.create_device_fault_info(fault_level="L2", fault_code=TEST_FAULT_CODES[4])
    ]

    # First update instance status to reflect the server fault
    manager._update_instances_status()

    # Mock time.sleep to control the loop execution
    def mock_sleep(seconds):
        raise StopIteration

    with patch('motor.controller.ft.fault_manager.time') as mock_time:
        mock_time.sleep.side_effect = mock_sleep
        try:
            manager._ft_strategy_center()
        except StopIteration:
            pass

    # Verify L2 strategy was called
    manager.strategies["L2"].assert_called_once_with(TEST_FAULT_CODES[4], 1)

def test_ft_strategy_center_strategy_finished(fault_manager_with_instances):
    """Test that finished strategies are cleaned up"""
    manager = fault_manager_with_instances

    # Setup instance with finished strategy
    mock_strategy = Mock()
    mock_strategy.is_finished.return_value = True
    manager.instances[1].strategy = mock_strategy

    # Mock time.sleep to control the loop execution
    def mock_sleep(seconds):
        raise StopIteration

    with patch('motor.controller.ft.fault_manager.time') as mock_time:
        mock_time.sleep.side_effect = mock_sleep
        try:
            manager._ft_strategy_center()
        except StopIteration:
            pass

    # Verify strategy was cleaned up
    assert manager.instances[1].strategy is None

@pytest.mark.parametrize("test_case,initial_strategy,new_fault,expected_stop_calls,expected_submit_calls", [
    ("fault_upgrade", {"level": "L2", "code": 0x2000}, {"level": "L4", "code": 0x4000}, 1, 1),
    ("fault_downgrade", {"level": "L4", "code": 0x4000}, {"level": "L2", "code": 0x2000}, 1, 1),
    ("same_level_same_code", {"level": "L3", "code": 0x3000}, {"level": "L3", "code": 0x3000}, 0, 0),
    ("same_level_different_code", {"level": "L3", "code": 0x3000}, {"level": "L3", "code": 0x3001}, 1, 1),
])
def test_ft_strategy_center_fault_transitions(fault_manager_with_instances, test_case, initial_strategy,
                                             new_fault, expected_stop_calls, expected_submit_calls):
    """Test fault level transitions and strategy changes"""
    manager = fault_manager_with_instances

    # Setup initial strategy
    mock_strategy = Mock()
    mock_strategy.is_finished.return_value = False
    mock_strategy.stop = Mock()

    # Set instance with existing strategy
    manager.instances[1].strategy = mock_strategy
    manager.instances[1].fault_level = initial_strategy["level"]
    manager.instances[1].fault_code = initial_strategy["code"]

    # Make server unhealthy with new fault level
    manager.servers[TEST_IPS[0]].status = Status.UNHEALTHY
    manager.servers[TEST_IPS[0]].device_fault_infos = [
        FaultManagerTestHelper.create_device_fault_info(
            fault_level=new_fault["level"], fault_code=new_fault["code"]
        )
    ]

    # Update instance status to reflect the server fault
    manager._update_instances_status()

    # For same level same code test, mock strategy factory to return None
    if test_case == "same_level_same_code":
        original_l3_strategy_factory = manager.strategies["L3"]
        def same_strategy_factory(fault_code, instance_id):
            if fault_code == 0x3000:  # Same fault code
                return None  # No new strategy needed
            else:
                return original_l3_strategy_factory(fault_code, instance_id)
        manager.strategies["L3"] = same_strategy_factory

    # Mock time.sleep to control the loop execution
    def mock_sleep(seconds):
        raise StopIteration

    with patch('motor.controller.ft.fault_manager.time') as mock_time:
        mock_time.sleep.side_effect = mock_sleep
        try:
            manager._ft_strategy_center()
        except StopIteration:
            pass

    # Verify strategy stop calls
    assert mock_strategy.stop.call_count == expected_stop_calls

    # Verify strategy submission calls
    assert manager.executor.submit.call_count == expected_submit_calls

    # Verify instance metadata was updated
    ins_metadata = manager.instances[1]
    assert ins_metadata.fault_level == new_fault["level"]
    assert ins_metadata.fault_code == new_fault["code"]

    # For cases where new strategy should be created
    if expected_submit_calls > 0:
        assert ins_metadata.strategy is not None
        # Verify correct strategy was called
        expected_level = new_fault["level"]
        manager.strategies[expected_level].assert_called_once_with(new_fault["code"], 1)
    elif test_case == "same_level_same_code":
        # Strategy should remain the same
        assert ins_metadata.strategy is mock_strategy


def test_multiple_instances_same_group(fault_manager):
    """Test adding multiple instances to the same group"""
    # Add prefill instance using helper
    mock_prefill = FaultManagerTestHelper.create_mock_instance(
        instance_id=100, role="prefill", group_id=1
    )
    fault_manager.update(mock_prefill, ObserverEvent.INSTANCE_ADDED)

    # Add decode instance to same group using helper
    mock_decode = FaultManagerTestHelper.create_mock_instance(
        instance_id=200, role="decode", group_id=1, pod_ip=TEST_IPS[1], host_ip=TEST_IPS[1]
    )
    fault_manager.update(mock_decode, ObserverEvent.INSTANCE_ADDED)

    # Check group contains both instances
    group = fault_manager.groups[1]
    assert 100 in group.p_ids
    assert 200 in group.d_ids
    assert len(group.p_ids) == 1
    assert len(group.d_ids) == 1

def test_concurrent_updates(fault_manager):
    """Test batch updates to FaultManager"""
    # Create multiple mock instances using helper
    instances = []
    for i in range(5):
        mock_instance = FaultManagerTestHelper.create_mock_instance(
            instance_id=i * 100,
            job_name=f"job_{i}",
            group_id=i,
            role="prefill" if i % 2 == 0 else "decode",
            pod_ip=f"192.168.1.{i+1}",
            host_ip=f"192.168.1.{i+1}"
        )
        instances.append(mock_instance)

    # Add all instances
    for instance in instances:
        fault_manager.update(instance, ObserverEvent.INSTANCE_ADDED)

    # Verify all instances are registered
    assert len(fault_manager.instances) == 5
    assert len(fault_manager.groups) == 5

    # Remove all instances
    for instance in instances:
        fault_manager.update(instance, ObserverEvent.INSTANCE_REMOVED)

    # Verify all instances are removed
    assert len(fault_manager.instances) == 0
    assert len(fault_manager.groups) == 0

def test_triggered_update_workflow(fault_manager):
    """Test the complete triggered update workflow"""
    # Setup instance using helper
    mock_instance = FaultManagerTestHelper.create_mock_instance()

    # Add instance
    fault_manager.update(mock_instance, ObserverEvent.INSTANCE_ADDED)

    # Verify initial state
    assert 100 in fault_manager.instances
    assert TEST_IPS[0] in fault_manager.servers
    assert fault_manager.instances[100].fault_level == "L0"
    assert fault_manager.instances[100].fault_code == 0x0

    # Simulate fault message processing with _update_instances_status call
    fault_manager.servers[TEST_IPS[0]].status = Status.UNHEALTHY
    fault_manager.servers[TEST_IPS[0]].device_fault_infos = [
        FaultManagerTestHelper.create_device_fault_info(fault_code=TEST_FAULT_CODES[0], fault_level="L3")
    ]

    # Call _update_instances_status to simulate triggered update
    fault_manager._update_instances_status()

    # Verify instance metadata was updated
    assert fault_manager.instances[100].fault_level == "L3"
    assert fault_manager.instances[100].fault_code == TEST_FAULT_CODES[0]

    # Now test strategy center with updated fault level
    with patch('motor.controller.ft.fault_manager.time') as mock_time:
        def mock_sleep(seconds):
            raise StopIteration

        mock_time.sleep.side_effect = mock_sleep
        try:
            fault_manager._ft_strategy_center()
        except StopIteration:
            pass

    # Verify strategy was submitted for the updated fault level
    fault_manager.executor.submit.assert_called_once()
    call_args = fault_manager.executor.submit.call_args

    # Verify the strategy execution parameters
    execute_method = call_args[0][0]  # First argument is the execute method
    instance_id = call_args[0][1]  # Second argument is the instance id

    assert execute_method is not None
    assert instance_id == 100

    # Verify L3 strategy was called with correct parameters
    fault_manager.strategies["L3"].assert_called_once_with(TEST_FAULT_CODES[0], 100)