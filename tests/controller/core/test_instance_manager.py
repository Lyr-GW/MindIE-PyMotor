import time
import pytest

from motor.controller.core.instance_manager import InstanceManager
from motor.common.resources.endpoint import Endpoint, EndpointStatus
from motor.common.resources.http_msg_spec import HeartbeatMsg
from motor.common.resources.instance import ParallelConfig, Instance, NodeManagerInfo, InsStatus
from motor.common.utils.singleton import ThreadSafeSingleton


def create_test_instance(
    instance_id: int,
    job_name: str,
    pod_ips: list[str],
    role: str = "prefill"
) -> Instance:
    """Helper function to create test instances with endpoints"""
    endpoints = {}
    for i, pod_ip in enumerate(pod_ips):
        endpoints[pod_ip] = {
            0: Endpoint(
                id=0,
                ip=pod_ip,
                business_port=f"80{0}{i}",
                mgmt_port=f"80{1}{i}",
                status=EndpointStatus.NORMAL,
                hb_timestamp=time.time()
            )
        }

    return Instance(
        id=instance_id,
        job_name=job_name,
        model_name="test_model",
        role=role,
        group_id=1,
        endpoints=endpoints
    )


@pytest.fixture
def test_config():
    """Test configuration fixture"""
    dp = 8
    tp = 2
    p_role = "prefill"
    d_role = "decode"

    # Generate pod IPs using list comprehension
    pod_ips = [f"127.0.0.{i}" for i in range(1, 9)]

    p_parallel_config = ParallelConfig(dp=dp, tp=tp)
    d_parallel_config = ParallelConfig(dp=dp * 4, tp=tp / 2)

    return {
        'dp': dp,
        'tp': tp,
        'p_role': p_role,
        'd_role': d_role,
        'pod_ips': pod_ips,
        'p_parallel_config': p_parallel_config,
        'd_parallel_config': d_parallel_config
    }


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Setup and teardown for each test"""
    # Clear singleton instance before each test
    if hasattr(ThreadSafeSingleton, '_instances') and InstanceManager in ThreadSafeSingleton._instances:
        try:
            ThreadSafeSingleton._instances[InstanceManager].stop()
        except:
            pass
        del ThreadSafeSingleton._instances[InstanceManager]


def _cleanup_singleton():
    """Clean up singleton instances"""
    if hasattr(ThreadSafeSingleton, '_instances') and InstanceManager in ThreadSafeSingleton._instances:
        try:
            ThreadSafeSingleton._instances[InstanceManager].stop()
        except:
            pass
        del ThreadSafeSingleton._instances[InstanceManager]


def _create_endpoint(id: int, ip: str, business_port: str = "9090", mgmt_port: str = "8080") -> Endpoint:
    """Helper function to create an Endpoint with default values"""
    return Endpoint(
        id=id,
        ip=ip,
        business_port=business_port,
        mgmt_port=mgmt_port,
        status=EndpointStatus.INITIAL,
        device_infos=[],
        hb_timestamp=time.time()
    )


@pytest.fixture
def instance_manager(test_config):
    """Setup mock instance manager"""
    from motor.config.controller import ControllerConfig
    config = ControllerConfig()
    # add instance, 2P1D
    instance_manager = InstanceManager(config)

    # Extract pod_ips for cleaner code
    pod_ips = test_config['pod_ips']
    # p0
    instance_manager.add_instance(
        Instance(
            job_name="prefill-0",
            model_name="test_model",
            id=0,
            role=test_config['p_role'],
            parallel_config=test_config['p_parallel_config'],
            node_mgrs=[NodeManagerInfo(pod_ip=pod_ips[0], host_ip=pod_ips[0], port="8080"),
                       NodeManagerInfo(pod_ip=pod_ips[1], host_ip=pod_ips[1], port="8080")],
            endpoints={
                pod_ips[0]: {0: _create_endpoint(0, pod_ips[0])},
                pod_ips[1]: {0: _create_endpoint(0, pod_ips[1])},
            },
        )
    )
    # p1
    instance_manager.add_instance(Instance(
        job_name="prefill-1",
        model_name="test_model",
        id=1,
        role=test_config['p_role'],
        parallel_config=test_config['p_parallel_config'],
        node_mgrs=[NodeManagerInfo(pod_ip=pod_ips[2], host_ip=pod_ips[2], port="8080"),
                   NodeManagerInfo(pod_ip=pod_ips[3], host_ip=pod_ips[3], port="8080")],
            endpoints={
                pod_ips[2]: {0: _create_endpoint(0, pod_ips[2])},
                pod_ips[3]: {0: _create_endpoint(0, pod_ips[3])}
            }
        ))
    # d0
    d_instance = Instance(
        job_name="decode-0",
        model_name="test_model",
        id=2,
        role=test_config['d_role'],
        parallel_config=test_config['d_parallel_config'],
        node_mgrs=[NodeManagerInfo(pod_ip=pod_ips[4], host_ip=pod_ips[4], port="8080"),
                   NodeManagerInfo(pod_ip=pod_ips[5], host_ip=pod_ips[5], port="8080"),
                   NodeManagerInfo(pod_ip=pod_ips[6], host_ip=pod_ips[6], port="8080"),
                   NodeManagerInfo(pod_ip=pod_ips[7], host_ip=pod_ips[7], port="8080"),
                   ],
        endpoints={}
    )
    # construct endpoints
    endpoints = {}
    for pod_ip in pod_ips[4:8]:
        port_temp = 8080
        endpoints[pod_ip] = {}
        for i in range(0, 8):
            endpoints[pod_ip][i] = _create_endpoint(
                id=i,
                ip=pod_ip,
                business_port=str(port_temp),
                mgmt_port=str(port_temp + 1000)
            )
            port_temp += 1

        d_instance.add_endpoints(pod_ip, endpoints[pod_ip])

    instance_manager.add_instance(d_instance)
    return instance_manager


def get_mock_heartbeat_msg_for_pinstance_normal(job_name: str, ins_id: int, ip: str) -> HeartbeatMsg:
    """Generate a mock heartbeat message"""
    status = {}
    for i in range(1):
        status[i] = EndpointStatus.NORMAL
    return HeartbeatMsg(
        job_name=job_name,
        ins_id=ins_id,
        ip=ip,
        status=status
    )


def test_add_instance(instance_manager, test_config) -> None:
    """Test adding an instance"""
    cur_instance_num = instance_manager.get_instance_num()
    # Abnormal situation
    instance_manager.add_instance(test_config['p_parallel_config'])
    actual_instance_num = instance_manager.get_instance_num()
    assert actual_instance_num == cur_instance_num

    instance_manager.add_instance(Instance(
        job_name="testAllocInsGroup2",
        model_name="test_model",
        id=100,
        role=test_config['p_role'],
        parallel_config=ParallelConfig(dp=test_config['dp'], tp=test_config['tp'] / 2)
    ))
    actual_instance_num = instance_manager.get_instance_num()
    assert actual_instance_num == cur_instance_num + 1


def test_del_instance(instance_manager) -> None:
    """Test deleting an instance"""
    cur_instance_num = instance_manager.get_instance_num()

    instance_manager.del_instance(0)
    actual_instance_num = instance_manager.get_instance_num()
    assert actual_instance_num == cur_instance_num - 1


def test_get_active_instances(instance_manager) -> None:
    """Test getting active instances"""
    instance = instance_manager.get_instance(0)
    instance.status = InsStatus.ACTIVE
    active_instances = instance_manager.get_active_instances()
    assert len(active_instances) == 1


def test_get_inactive_instance(instance_manager) -> None:
    """Test getting inactive instances"""
    instance = instance_manager.get_instance(0)
    instance.status = InsStatus.INACTIVE
    inactive_instances = instance_manager.get_inactive_instances()
    assert len(inactive_instances) == 1


def test_get_initial_instances(instance_manager) -> None:
    """Test getting initial instance status"""
    inactive_instances = instance_manager.get_initial_instances()
    assert len(inactive_instances) == 3


def test_handle_heartbeat(instance_manager, test_config) -> None:
    """Test handling heartbeat"""
    pod_ips = test_config['pod_ips']
    # P0 ready
    mock_heartbeat_msg1 = get_mock_heartbeat_msg_for_pinstance_normal(
        "prefill-0",
        0,
        pod_ips[0]
    )
    instance_manager.handle_heartbeat(mock_heartbeat_msg1)
    instance = instance_manager.get_instance(0)
    assert instance.status == InsStatus.INITIAL

    mock_heartbeat_msg2 = get_mock_heartbeat_msg_for_pinstance_normal(
        "prefill-0",
        0,
        pod_ips[1]
    )
    instance_manager.handle_heartbeat(mock_heartbeat_msg2)
    instance = instance_manager.get_instance(0)
    assert instance.status == InsStatus.ACTIVE

    mock_heartbeat_msg3 = get_mock_heartbeat_msg_for_pinstance_normal(
        "prefill-0",
        0,
        pod_ips[1]
    )
    mock_heartbeat_msg3.status[0] = EndpointStatus.ABNORMAL
    instance_manager.handle_heartbeat(mock_heartbeat_msg3)
    instance = instance_manager.get_instance(0)
    assert instance.status == InsStatus.INACTIVE

    mock_heartbeat_msg4 = get_mock_heartbeat_msg_for_pinstance_normal(
        "prefill-1",
        1,
        pod_ips[2]
    )
    mock_heartbeat_msg4.status[0] = EndpointStatus.ABNORMAL
    instance_manager.handle_heartbeat(mock_heartbeat_msg4)
    instance = instance_manager.get_instance(1)
    assert instance is None


def test_find_instance_with_matching_ip(instance_manager):
    """test finding an instance with matching ip"""
    pod_ip = "127.0.0.1"
    result = instance_manager.get_instance_by_podip(pod_ip)

    assert result is not None


def test_no_instance_contains_ip(instance_manager):
    """test finding an instance with no matching ip"""
    pod_ip = "192.168.1.100"
    result = instance_manager.get_instance_by_podip(pod_ip)

    assert result is None


def test_empty_string_pod_ip(instance_manager):
    """test empty string pod ip"""
    pod_ip = ""
    result = instance_manager.get_instance_by_podip(pod_ip)

    assert result is None


def test_separate_instance_by_id(instance_manager, test_config):
    """Test separating instance by ID"""
    # Create instances with multiple endpoints
    instance1 = create_test_instance(100, "test_job_1", ["192.168.1.1", "192.168.1.2"])
    instance2 = create_test_instance(101, "test_job_2", ["192.168.1.3"], role="decode")

    # Add instances
    instance_manager.add_instance(instance1)
    instance_manager.add_instance(instance2)

    # Set instances to ACTIVE state
    instance1.update_instance_status(InsStatus.ACTIVE)
    instance2.update_instance_status(InsStatus.ACTIVE)

    # Separate instances by ID
    instance_manager.separate_instance(instance1.id)
    instance_manager.separate_instance(instance2.id)

    # Verify instances are separated
    assert instance1.status == InsStatus.INACTIVE
    assert instance2.status == InsStatus.INACTIVE
    assert instance1.id in instance_manager.forced_separated_instances
    assert instance2.id in instance_manager.forced_separated_instances


def test_recover_instance_by_id(instance_manager, test_config):
    """Test recovering instance by ID"""
    # Create instance with forced separation
    instance = create_test_instance(102, "test_job_recovery", ["192.168.1.4"])

    # Add instance and force separate it
    instance_manager.add_instance(instance)
    instance.update_instance_status(InsStatus.ACTIVE)
    instance_manager.separate_instance(instance.id)

    # Verify it's separated
    assert instance.status == InsStatus.INACTIVE
    assert instance.id in instance_manager.forced_separated_instances

    # Recover instance by ID
    instance_manager.recover_instance(instance.id)

    # Verify it's recovered
    assert instance.id not in instance_manager.forced_separated_instances


def test_inactive_to_initial_state_transition(instance_manager, test_config):
    """Test transition from INACTIVE to INITIAL state"""
    # Create instance
    instance = create_test_instance(103, "test_job_transition", ["192.168.1.5"])

    # Add instance and set to INACTIVE
    instance_manager.add_instance(instance)
    instance.update_instance_status(InsStatus.INACTIVE)

    # Force separate it
    instance_manager.separate_instance(instance.id)
    assert instance.id in instance_manager.forced_separated_instances

    # Trigger state transition with INSTANCE_INIT event
    instance_manager._handle_state_transition(instance)

    # Manually set the event to INSTANCE_INIT and call handle_initial
    from motor.common.resources.instance import InsConditionEvent
    instance_manager._handle_initial(InsStatus.INACTIVE, InsConditionEvent.INSTANCE_INIT, instance)

    # Verify instance is removed from forced separated set
    assert instance.id not in instance_manager.forced_separated_instances


def test_forced_separated_instances_cleanup(instance_manager):
    """Test that forced_separated_instances is cleaned up when instance is deleted"""
    # Create instance
    instance = create_test_instance(104, "test_job_cleanup", ["192.168.1.6"])

    # Add instance and force separate it
    instance_manager.add_instance(instance)
    instance_manager.separate_instance(instance.id)

    # Verify it's in forced separated set
    assert instance.id in instance_manager.forced_separated_instances

    # Delete instance
    instance_manager.del_instance(instance.id)

    # Verify it's removed from forced separated set
    assert instance.id not in instance_manager.forced_separated_instances