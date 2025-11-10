import time
import pytest
from unittest.mock import MagicMock, patch

from motor.utils.data_builder import build_pod_ranktable, build_endpoints
from motor.resources.instance import Instance, ParallelConfig
from motor.resources.http_msg_spec import RegisterMsg, ReregisterMsg
from motor.controller.core.observer import ObserverEvent
from motor.controller.core.instance_assembler import InstanceAssembler


@pytest.fixture
def test_config():
    """Test configuration fixture"""
    dp = 4
    tp = 2
    role = "prefill"
    pod_ip1 = "127.0.0.1"
    pod_ip2 = "127.0.0.2"
    parallel_config = ParallelConfig(dp=dp, tp=tp)
    return {
        'dp': dp,
        'tp': tp,
        'role': role,
        'pod_ip1': pod_ip1,
        'pod_ip2': pod_ip2,
        'parallel_config': parallel_config
    }


def _cleanup_singleton():
    """Clean up singleton instances"""
    from motor.utils.singleton import ThreadSafeSingleton
    if InstanceAssembler in ThreadSafeSingleton._instances:
        assembler = ThreadSafeSingleton._instances[InstanceAssembler]
        try:
            assembler.stop()
        except Exception:
            pass
        del ThreadSafeSingleton._instances[InstanceAssembler]
    time.sleep(0.01)


@pytest.fixture
def instance_assembler():
    """Setup mock assembler with optimized threading"""
    from motor.config.controller import ControllerConfig
    config = ControllerConfig()
    _cleanup_singleton()
    with patch('threading.Thread') as mock_thread_class:
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread
        assembler = InstanceAssembler(config)
        yield assembler
        try:
            assembler.stop()
        except Exception:
            pass


@pytest.fixture
def setup_http_server():
    """Mock HTTP server to avoid websockets warnings"""
    with patch('motor.controller.core.instance_assembler.SafeHTTPSClient') as mock_client_class:
        mock_client = MagicMock()
        mock_client.post.return_value = {'result': 'success'}
        mock_client_class.return_value = mock_client
        yield mock_client

def test_register_succeed(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test successful instance registration"""
    job_name = "testRegisterSucceed"

    result = instance_assembler.register(
        msg=RegisterMsg(
            job_name=job_name,
            model_name="test_model",
            role=test_config['role'],
            pod_ip=test_config['pod_ip1'],
            host_ip=test_config['pod_ip1'],
            business_port=["8080", "8084"],
            mgmt_port=["9090", "9094"],
            nm_port="8088",
            parallel_config=test_config['parallel_config'],
            ranktable=build_pod_ranktable(pod_ip=test_config['pod_ip1'], pod_device_num=2*test_config['tp'])
        )
    )
    assert result == 0
    assert len(instance_assembler.instances) == 1

    result = instance_assembler.register(
        msg=RegisterMsg(
            job_name=job_name,
            model_name="test_model",
            role=test_config['role'],
            pod_ip=test_config['pod_ip2'],
            host_ip=test_config['pod_ip2'],
            business_port=["8080", "8084"],
            mgmt_port=["9090", "9094"],
            nm_port="8088",
            parallel_config=test_config['parallel_config'],
            ranktable=build_pod_ranktable(
                pod_ip=test_config['pod_ip2'],
                pod_device_num=2 * test_config['tp'],
                rank_offset=2 * test_config['tp'],
            )
        )
    )
    assert result == 0

    instance = instance_assembler.instances[job_name]
    instance_assembler._assemble_instance(instance)

    assert len(instance_assembler.starting_instances) == 1
    assert len(instance_assembler.instances) == 0

def test_register_timeout(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test instance registration timeout"""
    instance_assembler.config.instance_assemble_timeout = 0.05

    job_name = "testRegisterTimeout"

    result = instance_assembler.register(
        msg=RegisterMsg(
            job_name=job_name,
            model_name="test_model",
            role=test_config['role'],
            pod_ip=test_config['pod_ip1'],
            host_ip=test_config['pod_ip1'],
            business_port=["8080"],
            mgmt_port=["9090"],
            nm_port="8088",
            parallel_config=test_config['parallel_config'],
            ranktable=build_pod_ranktable(pod_ip=test_config['pod_ip1'], pod_device_num=2*test_config['tp'])
        )
    )
    assert result == 0
    assert len(instance_assembler.instances) == 1

    time.sleep(0.06)

    if job_name in instance_assembler.instances:
        instance_assembler._assemble_instance(instance_assembler.instances[job_name])

    assert len(instance_assembler.instances) == 0

def test_reregister_succeed(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test successful instance re-registration"""
    job_name = "testReregister"

    ep1 = build_endpoints(
        msg=RegisterMsg(
            job_name=job_name,
            model_name="test_model",
            role=test_config['role'],
            pod_ip=test_config['pod_ip1'],
            host_ip=test_config['pod_ip1'],
            business_port=["8080", "8084"],
            mgmt_port=["9090", "9094"],
            nm_port="8088",
            parallel_config=test_config['parallel_config'],
            ranktable=build_pod_ranktable(pod_ip=test_config['pod_ip1'], pod_device_num=2*test_config['tp'])
        ),
    )
    ep2 = build_endpoints(
        msg=RegisterMsg(
            job_name=job_name,
            model_name="test_model",
            role=test_config['role'],
            pod_ip=test_config['pod_ip2'],
            host_ip=test_config['pod_ip2'],
            business_port=["8080", "8084"],
            mgmt_port=["9090", "9094"],
            nm_port="8088",
            parallel_config=test_config['parallel_config'],
            ranktable=build_pod_ranktable(
                pod_ip=test_config['pod_ip2'],
                pod_device_num=2 * test_config['tp'],
                rank_offset=2 * test_config['tp'],
            )
        ),
        id_offset=test_config['tp']
    )

    result = instance_assembler.reregister(
        msg=ReregisterMsg(
            job_name=job_name,
            model_name="test_model",
            instance_id=0,
            role=test_config['role'],
            pod_ip=test_config['pod_ip1'],
            host_ip=test_config['pod_ip1'],
            nm_port="8088",
            parallel_config=test_config['parallel_config'],
            endpoints=[endpoint for endpoint in ep1.values()]
        )
    )
    assert result == 0
    assert len(instance_assembler.instances) == 1

    result = instance_assembler.reregister(
        msg=ReregisterMsg(
            job_name=job_name,
            model_name="test_model",
            instance_id=0,
            role=test_config['role'],
            pod_ip=test_config['pod_ip2'],
            host_ip=test_config['pod_ip2'],
            nm_port="8088",
            parallel_config=test_config['parallel_config'],
            endpoints=[endpoint for endpoint in ep2.values()]
        )
    )

    assert result == 0
    assert instance_assembler.ins_id_cnt == 1

    instance_assembler._assemble_instance(instance_assembler.instances[job_name])
    assert len(instance_assembler.instances) == 0

def test_send_start_cmd(instance_assembler: InstanceAssembler, test_config, setup_http_server) -> None:
    """Test start command sending"""
    job_name = "testSendStartCommand"

    result = instance_assembler.register(
        msg=RegisterMsg(
            job_name=job_name,
            model_name="test_model",
            role=test_config['role'],
            pod_ip=test_config['pod_ip1'],
            host_ip=test_config['pod_ip1'],
            business_port=["8080", "8084"],
            mgmt_port=["9090", "9094"],
            nm_port="8088",
            parallel_config=test_config['parallel_config'],
            ranktable=build_pod_ranktable(pod_ip=test_config['pod_ip1'], pod_device_num=2*test_config['tp'])
        )
    )
    assert result == 0

    instance = instance_assembler.instances[job_name]
    instance_assembler.starting_instances.add(job_name)

    success = instance_assembler._send_start_command(instance)
    assert success == True

def test_send_start_cmd_fail_retry(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test start command failure retry"""
    job_name = "testSendStartCommandFailRetry"

    result = instance_assembler.register(
        msg=RegisterMsg(
            job_name=job_name,
            model_name="test_model",
            role=test_config['role'],
            pod_ip=test_config['pod_ip1'],
            host_ip=test_config['pod_ip1'],
            business_port=["8080", "8084"],
            mgmt_port=["9091", "9095"],
            nm_port="8089",
            parallel_config=test_config['parallel_config'],
            ranktable=build_pod_ranktable(pod_ip=test_config['pod_ip1'], pod_device_num=2*test_config['tp'])
        )
    )
    assert result == 0

    instance_assembler.assembled_instances.put((instance_assembler.instances[job_name], 0))
    instance_assembler.assembled_instances.put(None)
    assert instance_assembler.assembled_instances.qsize() == 2

    def mock_stop_sleep(seconds):
        if instance_assembler.assembled_instances.qsize() > 0:
            raise StopIteration

    with patch('motor.controller.core.instance_assembler.time') as mock_time:
        mock_time.sleep.side_effect = mock_stop_sleep
        try:
            instance_assembler._start_commmand_sender()
        except StopIteration:
            pass

        assert instance_assembler.assembled_instances.qsize() == 2

def test_send_start_cmd_fail_abort(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test start command failure abort"""
    instance_assembler.config.send_cmd_retry_times = 1
    job_name = "testSendStartCommandFailAbort"

    result = instance_assembler.register(
        msg=RegisterMsg(
            job_name=job_name,
            model_name="test_model",
            role=test_config['role'],
            pod_ip=test_config['pod_ip1'],
            host_ip=test_config['pod_ip1'],
            business_port=["8080", "8084"],
            mgmt_port=["9091", "9095"],
            nm_port="8089",
            parallel_config=test_config['parallel_config'],
            ranktable=build_pod_ranktable(pod_ip=test_config['pod_ip1'], pod_device_num=2*test_config['tp'])
        )
    )
    assert result == 0

    instance_assembler.assembled_instances.put((instance_assembler.instances[job_name], 0))
    instance_assembler.assembled_instances.put(None)
    assert instance_assembler.assembled_instances.qsize() == 2

    def mock_stop_sleep(seconds):
        if instance_assembler.assembled_instances.qsize() > 0:
            raise StopIteration

    with patch('motor.controller.core.instance_assembler.time') as mock_time:
        mock_time.sleep.side_effect = mock_stop_sleep
        try:
            instance_assembler._start_commmand_sender()
        except StopIteration:
            pass

        assert instance_assembler.assembled_instances.qsize() == 1

def test_alloc_ins_group_success(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test successful instance group allocation"""
    instance_assembler.config.max_link_number = 8

    instance1 = Instance(
        job_name="testAllocInsGroup1",
        model_name="test_model",
        id=1,
        role=test_config['role'],
        parallel_config=test_config['parallel_config']
    )

    instance2 = Instance(
        job_name="testAllocInsGroup2",
        model_name="test_model",
        id=2,
        role=test_config['role'],
        parallel_config=ParallelConfig(dp=test_config['dp'], tp=test_config['tp'] / 2)
    )
    instance3 = Instance(
        job_name="testAllocInsGroup3",
        model_name="test_model",
        id=3,
        role=test_config['role'],
        parallel_config=ParallelConfig(dp=test_config['dp'], tp=test_config['tp'] / 2)
    )

    instance_assembler._assign_ins_group(instance1)
    instance_assembler._assign_ins_group(instance1)

    instance_assembler._assign_ins_group(instance2)
    instance_assembler._assign_ins_group(instance3)

    group_info = instance_assembler.instances_group

    assert len(group_info) == 2
    assert group_info[0].current_group_member == test_config['dp'] * test_config['tp']
    assert group_info[1].current_group_member == test_config['dp'] * test_config['tp']

def test_alloc_ins_group_fail(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test failed instance group allocation"""
    max_link_number = 2
    instance_assembler.config.max_link_number = max_link_number

    instance = Instance(
        job_name="testAllocInsGroupFail",
        model_name="test_model",
        id=1,
        role=test_config['role'],
        parallel_config=test_config['parallel_config']
    )

    try:
        instance_assembler._assign_ins_group(instance)
    except Exception as e:
        error_msg = (
            f"Instance {instance.job_name}(id:{instance.id}) allocate ins group failed, "
            f"max link number is {max_link_number}, but need {instance.parallel_config.world_size}."
        )
        assert str(e) == error_msg
        return

    assert False, "Expected exception was not raised."

def test_ins_group_metadata_update(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test instance group metadata update"""
    instance_assembler.config.max_link_number = 8

    instance1 = Instance(
        job_name="testAllocInsGroup1",
        model_name="test_model",
        id=1,
        role="prefill",
        parallel_config=ParallelConfig(dp=test_config['dp'], tp=test_config['tp'] / 2)
    )
    instance2 = Instance(
        job_name="testInsGroupMetadataUpdate",
        model_name="test_model",
        id=2,
        role="decode",
        parallel_config=ParallelConfig(dp=test_config['dp'], tp=test_config['tp'] / 2)
    )

    instance_assembler._assign_ins_group(instance1)
    instance_assembler._assign_ins_group(instance2)

    assert len(instance_assembler.instances_group) == 1
    assert instance_assembler.instances_group[0].current_group_member == test_config['dp'] * test_config['tp']
    assert instance1.group_id == 0 and instance2.group_id == 0

    instance_assembler.update(instance1, ObserverEvent.INSTANCE_REMOVED)
    instance_assembler.update(instance2, ObserverEvent.INSTANCE_REMOVED)
    assert instance_assembler.instances_group[0].current_group_member == 0


def test_exception_handle(instance_assembler: InstanceAssembler):
    """Test exception handling"""
    try:
        instance_assembler.register({})
    except Exception as e:
        error_msg = (f"Invalid msg provided to register. "
                     f"expect RegisterMsg, got {type({})}")
        assert str(e) == error_msg
        return
    try:
        instance_assembler.reregister({})
    except Exception as e:
        error_msg = (f"Invalid msg provided to reregister. "
                     f"expect ReregisterMsg, got {type({})}")
        assert str(e) == error_msg
        return

    try:
        instance_assembler._assemble_instance({})
    except Exception as e:
        error_msg = (f"Invalid instance provided to assemble. "
                     f"expect Instance, got {type({})}")
        assert str(e) == error_msg
        return

    assert False, "Expected exception was not raised."

def test_stop() -> None:
    """Test stop method"""
    from motor.config.controller import ControllerConfig
    config = ControllerConfig()

    instance_assembler = InstanceAssembler(config)
    instance_assembler.stop()

    assert instance_assembler.stop_event.is_set() == True

def test_performance(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test performance under load"""

    num_instances = 10
    start_time = time.time()

    for i in range(num_instances):
        result = instance_assembler.register(
            RegisterMsg(
                job_name=f"perf_test_{i}",
                model_name="test_model",
                role=test_config['role'],
                pod_ip=f"127.0.0.{i % 5}",
                host_ip=f"127.0.0.{i % 5}",
                business_port=["8080", "8084"],
                mgmt_port=["9090", "9094"],
                nm_port="8088",
                parallel_config=test_config['parallel_config'],
                ranktable=build_pod_ranktable(
                    pod_ip=f"127.0.0.{i % 5}",
                    pod_device_num=2*test_config['tp']
                )
            )
        )
        assert result == 0

    end_time = time.time()
    registration_time = end_time - start_time

    assert len(instance_assembler.instances) == num_instances
    assert registration_time < 5.0

def test_concurrent_registration(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test concurrent registration"""
    job_name = "testConcurrentRegistration"
    num_instances = 3

    results = []
    for i in range(num_instances):
        result = instance_assembler.register(
            RegisterMsg(
                job_name=f"{job_name}_{i}",
                model_name="test_model",
                role=test_config['role'],
                pod_ip=f"127.0.0.{i}",
                host_ip=f"127.0.0.{i}",
                business_port=["8080", "8084"],
                mgmt_port=["9090", "9094"],
                nm_port="8088",
                parallel_config=test_config['parallel_config'],
                ranktable=build_pod_ranktable(
                    pod_ip=f"127.0.0.{i}",
                    pod_device_num=2*test_config['tp']
                )
            )
        )
        results.append(result)

    assert all(result == 0 for result in results)
    assert len(instance_assembler.instances) == num_instances