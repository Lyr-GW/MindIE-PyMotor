import time
from unittest.mock import patch, MagicMock
import pytest

from motor.controller.core.instance_manager import InstanceManager
from motor.resources.endpoint import Endpoint, EndpointStatus
from motor.resources.http_msg_spec import HeartbeatMsg
from motor.resources.instance import ParallelConfig, Instance, NodeManagerInfo, InsStatus


@pytest.fixture
def test_config():
    """Test configuration fixture"""
    dp = 8
    tp = 2
    p_role = "prefill"
    d_role = "decode"
    pod_ip1 = "127.0.0.1"
    pod_ip2 = "127.0.0.2"
    pod_ip3 = "127.0.0.3"
    pod_ip4 = "127.0.0.4"
    pod_ip5 = "127.0.0.5"
    pod_ip6 = "127.0.0.6"
    pod_ip7 = "127.0.0.7"
    pod_ip8 = "127.0.0.8"

    p_parallel_config = ParallelConfig(dp=dp, tp=tp)
    d_parallel_config = ParallelConfig(dp=dp * 4, tp=tp / 2)

    return {
        'dp': dp,
        'tp': tp,
        'p_role': p_role,
        'd_role': d_role,
        'pod_ip1': pod_ip1,
        'pod_ip2': pod_ip2,
        'pod_ip3': pod_ip3,
        'pod_ip4': pod_ip4,
        'pod_ip5': pod_ip5,
        'pod_ip6': pod_ip6,
        'pod_ip7': pod_ip7,
        'pod_ip8': pod_ip8,
        'p_parallel_config': p_parallel_config,
        'd_parallel_config': d_parallel_config
    }


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Setup and teardown for each test"""
    # Clear singleton instance before each test
    if hasattr(InstanceManager, '_instances') and InstanceManager in InstanceManager._instances:
        try:
            InstanceManager._instances[InstanceManager].stop()
        except:
            pass
        if InstanceManager in InstanceManager._instances:
            del InstanceManager._instances[InstanceManager]


def _cleanup_singleton():
    """Clean up singleton instances"""
    if hasattr(InstanceManager, '_instances') and InstanceManager in InstanceManager._instances:
        try:
            InstanceManager._instances[InstanceManager].stop()
        except:
            pass
        if InstanceManager in InstanceManager._instances:
            del InstanceManager._instances[InstanceManager]


@pytest.fixture
def instance_manager(test_config):
    """Setup mock instance manager"""
    from motor.config.controller import ControllerConfig
    config = ControllerConfig()
    # add instance, 2P1D
    instance_manager = InstanceManager(config)
    # p0
    instance_manager.add_instance(Instance(
        job_name="prefill-0",
        model_name="test_model",
        id=0,
        role=test_config['p_role'],
        parallel_config=test_config['p_parallel_config'],
        node_mgrs=[NodeManagerInfo(pod_ip=test_config['pod_ip1'], host_ip=test_config['pod_ip1'], port="8080"),
                   NodeManagerInfo(pod_ip=test_config['pod_ip2'], host_ip=test_config['pod_ip2'], port="8080")],
        endpoints={test_config['pod_ip1']: {
            0: Endpoint(0, test_config['pod_ip1'], port="9090", status=EndpointStatus.INITIAL, device_infos=list(),
                        hb_timestamp=time.time())},
            test_config['pod_ip2']: {
                0: Endpoint(0, test_config['pod_ip2'], port="9090", status=EndpointStatus.INITIAL, device_infos=list(),
                            hb_timestamp=time.time())}}
    ))
    # p1
    instance_manager.add_instance(Instance(
        job_name="prefill-1",
        model_name="test_model",
        id=1,
        role=test_config['p_role'],
        parallel_config=test_config['p_parallel_config'],
        node_mgrs=[NodeManagerInfo(pod_ip=test_config['pod_ip3'], host_ip=test_config['pod_ip3'], port="8080"),
                   NodeManagerInfo(pod_ip=test_config['pod_ip4'], host_ip=test_config['pod_ip4'], port="8080")],
        endpoints={test_config['pod_ip3']: {
            0: Endpoint(0, test_config['pod_ip3'], port="9090", status=EndpointStatus.INITIAL, device_infos=list(),
                        hb_timestamp=time.time())},
            test_config['pod_ip4']: {
                0: Endpoint(0, test_config['pod_ip4'], port="9090", status=EndpointStatus.INITIAL, device_infos=list(),
                            hb_timestamp=time.time())}}
    ))
    # d0
    d_instance = Instance(
        job_name="decode-0",
        model_name="test_model",
        id=2,
        role=test_config['d_role'],
        parallel_config=test_config['d_parallel_config'],
        node_mgrs=[NodeManagerInfo(pod_ip=test_config['pod_ip5'], host_ip=test_config['pod_ip5'], port="8080"),
                   NodeManagerInfo(pod_ip=test_config['pod_ip6'], host_ip=test_config['pod_ip6'], port="8080"),
                   NodeManagerInfo(pod_ip=test_config['pod_ip7'], host_ip=test_config['pod_ip7'], port="8080"),
                   NodeManagerInfo(pod_ip=test_config['pod_ip8'], host_ip=test_config['pod_ip8'], port="8080"),
                   ],
        endpoints={}
    )
    # construct endpoints
    endpoints = {}
    for pod_ip in [test_config['pod_ip5'], test_config['pod_ip6'], test_config['pod_ip7'], test_config['pod_ip8']]:
        port_temp = 8080
        endpoints[pod_ip] = {}
        for i in range(0, 8):
            endpoints[pod_ip][i] = Endpoint(
                id=i,
                ip=pod_ip,
                port=str(port_temp),
                status=EndpointStatus.INITIAL,
                device_infos=[],
                hb_timestamp=time.time()
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
    # P0 ready
    mock_heartbeat_msg1 = get_mock_heartbeat_msg_for_pinstance_normal(
        "prefill-0",
        0,
        test_config['pod_ip1']
    )
    instance_manager.handle_heartbeat(mock_heartbeat_msg1)
    instance = instance_manager.get_instance(0)
    assert instance.status == InsStatus.INITIAL

    mock_heartbeat_msg2 = get_mock_heartbeat_msg_for_pinstance_normal(
        "prefill-0",
        0,
        test_config['pod_ip2']
    )
    instance_manager.handle_heartbeat(mock_heartbeat_msg2)
    instance = instance_manager.get_instance(0)
    assert instance.status == InsStatus.ACTIVE

    mock_heartbeat_msg3 = get_mock_heartbeat_msg_for_pinstance_normal(
        "prefill-0",
        0,
        test_config['pod_ip2']
    )
    mock_heartbeat_msg3.status[0] = EndpointStatus.ABNORMAL
    instance_manager.handle_heartbeat(mock_heartbeat_msg3)
    instance = instance_manager.get_instance(0)
    assert instance.status == InsStatus.INACTIVE

    mock_heartbeat_msg4 = get_mock_heartbeat_msg_for_pinstance_normal(
        "prefill-1",
        1,
        test_config['pod_ip3']
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