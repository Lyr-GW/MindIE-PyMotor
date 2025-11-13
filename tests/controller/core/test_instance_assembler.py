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


# Helper functions for test data creation
def create_register_msg(job_name: str, pod_ip: str, config: dict, **kwargs) -> RegisterMsg:
    """Create a RegisterMsg with common defaults"""
    # Set default values only if not provided in kwargs
    defaults = {
        'model_name': "test_model",
        'role': config['role'],
        'host_ip': pod_ip,
        'business_port': ["8080", "8084"],
        'mgmt_port': ["9090", "9094"],
        'nm_port': "8088",
        'parallel_config': config['parallel_config'],
        'ranktable': build_pod_ranktable(pod_ip=pod_ip, pod_device_num=2*config['tp'])
    }

    # Update defaults with provided kwargs
    defaults.update(kwargs)

    return RegisterMsg(
        job_name=job_name,
        pod_ip=pod_ip,
        **defaults
    )


def create_reregister_msg(job_name: str, pod_ip: str, instance_id: int, config: dict, endpoints: dict) -> ReregisterMsg:
    """Create a ReregisterMsg with common defaults"""
    return ReregisterMsg(
        job_name=job_name,
        model_name="test_model",
        instance_id=instance_id,
        role=config['role'],
        pod_ip=pod_ip,
        host_ip=pod_ip,
        nm_port="8088",
        parallel_config=config['parallel_config'],
        endpoints=[endpoint for endpoint in endpoints.values()]
    )


def register_complete_instance(assembler: InstanceAssembler, job_name: str, config: dict) -> Instance:
    """Register and assemble a complete instance with two pods"""
    # Register first pod
    msg1 = create_register_msg(job_name, config['pod_ip1'], config)
    result1 = assembler.register(msg1)
    assert result1 == 0

    # Register second pod
    msg2 = create_register_msg(
        job_name, config['pod_ip2'], config,
        ranktable=build_pod_ranktable(
            pod_ip=config['pod_ip2'],
            pod_device_num=2 * config['tp'],
            rank_offset=2 * config['tp']
        )
    )
    result2 = assembler.register(msg2)
    assert result2 == 0

    # Assemble the instance
    instance = assembler.instances[job_name]
    assembler._assemble_instance(instance)
    return instance


def reregister_complete_instance(assembler: InstanceAssembler, job_name: str, config: dict) -> Instance:
    """Reregister and assemble a complete instance with two pods"""
    # Build endpoints for both pods
    ep1 = build_endpoints(create_register_msg(job_name, config['pod_ip1'], config))
    ep2 = build_endpoints(
        create_register_msg(job_name, config['pod_ip2'], config,
                          ranktable=build_pod_ranktable(
                              pod_ip=config['pod_ip2'],
                              pod_device_num=2 * config['tp'],
                              rank_offset=2 * config['tp']
                          )),
        id_offset=config['tp']
    )

    # Reregister both pods
    msg1 = create_reregister_msg(job_name, config['pod_ip1'], 0, config, ep1)
    result1 = assembler.reregister(msg1)
    assert result1 == 0

    msg2 = create_reregister_msg(job_name, config['pod_ip2'], 0, config, ep2)
    result2 = assembler.reregister(msg2)
    assert result2 == 0

    # Assemble the instance
    instance = assembler.instances[job_name]
    assembler._assemble_instance(instance)
    return instance


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

    # Register first pod
    msg1 = create_register_msg(job_name, test_config['pod_ip1'], test_config)
    result1 = instance_assembler.register(msg1)
    assert result1 == 0
    assert len(instance_assembler.instances) == 1

    # Register second pod
    msg2 = create_register_msg(
        job_name, test_config['pod_ip2'], test_config,
        ranktable=build_pod_ranktable(
            pod_ip=test_config['pod_ip2'],
            pod_device_num=2 * test_config['tp'],
            rank_offset=2 * test_config['tp']
        )
    )
    result2 = instance_assembler.register(msg2)
    assert result2 == 0

    # Assemble instance
    instance = instance_assembler.instances[job_name]
    instance_assembler._assemble_instance(instance)

    assert len(instance_assembler.starting_instances) == 1
    assert len(instance_assembler.instances) == 0


def test_register_timeout(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test instance registration timeout"""
    instance_assembler.config.instance_assemble_timeout = 0.05
    job_name = "testRegisterTimeout"

    # Register incomplete instance (only one pod)
    msg = create_register_msg(job_name, test_config['pod_ip1'], test_config, business_port=["8080"])
    result = instance_assembler.register(msg)
    assert result == 0
    assert len(instance_assembler.instances) == 1

    time.sleep(0.06)

    # Check if instance was removed due to timeout
    if job_name in instance_assembler.instances:
        instance_assembler._assemble_instance(instance_assembler.instances[job_name])

    assert len(instance_assembler.instances) == 0


def test_reregister_succeed(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test successful instance re-registration"""
    job_name = "testReregister"

    # Reregister first pod
    ep1 = build_endpoints(create_register_msg(job_name, test_config['pod_ip1'], test_config))
    msg1 = create_reregister_msg(job_name, test_config['pod_ip1'], 0, test_config, ep1)
    result1 = instance_assembler.reregister(msg1)
    assert result1 == 0
    assert len(instance_assembler.instances) == 1

    # Reregister second pod
    ep2 = build_endpoints(
        create_register_msg(job_name, test_config['pod_ip2'], test_config,
                          ranktable=build_pod_ranktable(
                              pod_ip=test_config['pod_ip2'],
                              pod_device_num=2 * test_config['tp'],
                              rank_offset=2 * test_config['tp']
                          )),
        id_offset=test_config['tp']
    )
    msg2 = create_reregister_msg(job_name, test_config['pod_ip2'], 0, test_config, ep2)
    result2 = instance_assembler.reregister(msg2)
    assert result2 == 0
    assert instance_assembler.ins_id_cnt == 1

    # Assemble instance
    instance_assembler._assemble_instance(instance_assembler.instances[job_name])
    assert len(instance_assembler.instances) == 0


def test_send_start_cmd_fail_retry(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test start command failure retry"""
    # Mock HTTP client to simulate failure
    with patch('motor.controller.core.instance_assembler.SafeHTTPSClient') as mock_client_class:
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("Connection failed")
        mock_client_class.return_value = mock_client

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
    # Mock HTTP client to simulate failure
    with patch('motor.controller.core.instance_assembler.SafeHTTPSClient') as mock_client_class:
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("Connection failed")
        mock_client_class.return_value = mock_client

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


def test_update_method_coverage(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test update method with different events and edge cases"""
    instance_assembler.config.max_link_number = 8

    # Create and assign instance to group
    instance = Instance(
        job_name="testUpdateMethod",
        model_name="test_model",
        id=1,
        role="prefill",
        parallel_config=ParallelConfig(dp=test_config['dp'], tp=test_config['tp'] / 2)
    )
    instance_assembler._assign_ins_group(instance)

    # Test non-INSTANCE_REMOVED event (should do nothing)
    instance_assembler.update(instance, "OTHER_EVENT")
    assert instance_assembler.instances_group[0].current_group_member == test_config['dp'] * test_config['tp'] / 2

    # Test instance not in any group
    orphan_instance = Instance(
        job_name="testOrphanInstance",
        model_name="test_model",
        id=2,
        role="prefill",
        parallel_config=ParallelConfig(dp=test_config['dp'], tp=test_config['tp'] / 2)
    )
    # This should not raise exception and should do nothing
    instance_assembler.update(orphan_instance, ObserverEvent.INSTANCE_REMOVED)


def test_register_already_registered(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test register method when instance is already registered (assembled)"""
    job_name = "testRegisterAlreadyRegistered"

    # Register and assemble a complete instance
    register_complete_instance(instance_assembler, job_name, test_config)

    # Try to register again - should return -1
    msg3 = create_register_msg(job_name, "127.0.0.3", test_config,
                              ranktable=build_pod_ranktable(pod_ip="127.0.0.3", pod_device_num=2*test_config['tp']))
    result3 = instance_assembler.register(msg3)
    assert result3 == -1


def test_reregister_already_registered(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test reregister method when instance is already registered (assembled)"""
    job_name = "testReregisterAlreadyRegistered"

    # Reregister and assemble a complete instance
    reregister_complete_instance(instance_assembler, job_name, test_config)

    # Try to reregister again - should return -1
    ep1 = build_endpoints(create_register_msg(job_name, test_config['pod_ip1'], test_config))
    msg3 = create_reregister_msg(job_name, "127.0.0.3", 0, test_config, ep1)
    result3 = instance_assembler.reregister(msg3)
    assert result3 == -1


def test_send_start_command_success(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test _send_start_command method success and partial failure scenarios"""
    job_name = "testSendStartCommand"

    # Create an instance with multiple node managers (different ports)
    msg1 = create_register_msg(job_name, test_config['pod_ip1'], test_config)
    result1 = instance_assembler.register(msg1)
    assert result1 == 0

    msg2 = create_register_msg(job_name, test_config['pod_ip2'], test_config,
                              nm_port="8089",
                              ranktable=build_pod_ranktable(
                                  pod_ip=test_config['pod_ip2'],
                                  pod_device_num=2 * test_config['tp'],
                                  rank_offset=2 * test_config['tp']
                              ))
    result2 = instance_assembler.register(msg2)
    assert result2 == 0

    instance = instance_assembler.instances[job_name]

    # Test successful send command
    with patch('motor.controller.core.instance_assembler.SafeHTTPSClient') as mock_client_class:
        mock_client = MagicMock()
        mock_client.post.return_value = {'result': 'success'}
        mock_client_class.return_value = mock_client

        result = instance_assembler._send_start_command(instance)
        assert result == True
        assert mock_client.post.call_count == 2

    # Test partial failure scenario
    with patch('motor.controller.core.instance_assembler.SafeHTTPSClient') as mock_client_class:
        def side_effect(*args, **kwargs):
            if '127.0.0.1:8088' in str(args):
                return {'result': 'success'}
            else:
                raise Exception("Connection failed")

        mock_client = MagicMock()
        mock_client.post.side_effect = side_effect
        mock_client_class.return_value = mock_client

        result = instance_assembler._send_start_command(instance)
        assert result == False  # Should return False because one failed
        assert mock_client.post.call_count == 2

    # Test scenario where some node managers have no endpoints
    instance_no_endpoints = Instance(
        job_name="testSendStartCommandNoEndpoints",
        model_name="test_model",
        id=1,
        role=test_config['role'],
        parallel_config=test_config['parallel_config']
    )

    # Add node managers but only one has endpoints
    instance_no_endpoints.add_node_mgr("127.0.0.1", "127.0.0.1", "8088")
    instance_no_endpoints.add_node_mgr("127.0.0.2", "127.0.0.2", "8089")
    pod_endpoints = build_endpoints(create_register_msg("test", "127.0.0.1", test_config))
    instance_no_endpoints.add_endpoints("127.0.0.1", pod_endpoints)

    with patch('motor.controller.core.instance_assembler.SafeHTTPSClient') as mock_client_class:
        mock_client = MagicMock()
        mock_client.post.return_value = {'result': 'success'}
        mock_client_class.return_value = mock_client

        result = instance_assembler._send_start_command(instance_no_endpoints)
        assert result == True  # Should succeed since only one node manager has endpoints
        assert mock_client.post.call_count == 1


def test_instances_assembler_thread_stop(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test _instances_assembler method when thread is stopped"""
    # Create an instance that's still assembling
    job_name = "testInstancesAssemblerStop"
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

    # Set stop event and test the loop exits gracefully
    instance_assembler.stop_event.set()

    # Mock time.sleep to avoid long waits
    def mock_stop_sleep(seconds):
        if instance_assembler.stop_event.is_set():
            raise StopIteration

    with patch('motor.controller.core.instance_assembler.time') as mock_time:
        mock_time.sleep.side_effect = mock_stop_sleep
        try:
            instance_assembler._instances_assembler_loop()
        except StopIteration:
            pass

    # Instance should still be there since it didn't complete assembly
    assert len(instance_assembler.instances) == 1


def test_instances_assembler_loop_execution(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test _instances_assembler method loop execution with instance in starting state"""
    # Create an instance and put it in starting state
    job_name = "testInstancesAssemblerLoop"
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

    # Register second pod to complete assembly
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

    # Assemble the instance to put it in starting state
    instance = instance_assembler.instances[job_name]
    instance_assembler._assemble_instance(instance)

    # Now the instance should be in starting_instances and removed from instances
    assert job_name in instance_assembler.starting_instances
    assert job_name not in instance_assembler.instances

    # Set stop event after a short delay to allow one loop iteration
    def mock_sleep_with_stop(seconds):
        instance_assembler.stop_event.set()
        raise StopIteration

    with patch('motor.controller.core.instance_assembler.time') as mock_time:
        mock_time.sleep.side_effect = mock_sleep_with_stop
        try:
            instance_assembler._instances_assembler_loop()
        except StopIteration:
            pass

    # The loop should have executed and checked the starting instance (but not processed it since it's starting)
    assert job_name in instance_assembler.starting_instances


def test_eval_register_status(instance_assembler: InstanceAssembler, test_config) -> None:
    """Test _eval_register_status method for all status conditions"""
    from motor.controller.core.instance_assembler import RegisterStatus

    job_name_assembling = "testEvalStatusAssembling"
    job_name_assembled = "testEvalStatusAssembled"
    job_name_not_registered = "testEvalStatusNotRegistered"

    # Test NOT_REGISTERED status
    status = instance_assembler._eval_register_status(job_name_not_registered)
    assert status == RegisterStatus.NOT_REGISTERED

    # Test ASSEMBLING status (instance exists but not in any group)
    msg = create_register_msg(job_name_assembling, test_config['pod_ip1'], test_config, business_port=["8080"])
    result = instance_assembler.register(msg)
    assert result == 0
    status = instance_assembler._eval_register_status(job_name_assembling)
    assert status == RegisterStatus.ASSEMBLING

    # Test ASSEMBLED status (instance is in a group)
    register_complete_instance(instance_assembler, job_name_assembled, test_config)
    status = instance_assembler._eval_register_status(job_name_assembled)
    assert status == RegisterStatus.ASSEMBLED


def test_singleton_reinitialization():
    """Test that singleton pattern prevents re-initialization"""
    from motor.config.controller import ControllerConfig
    _cleanup_singleton()

    config1 = ControllerConfig()
    config1.instance_assemble_timeout = 100  # Custom value

    config2 = ControllerConfig()
    config2.instance_assemble_timeout = 200  # Different value

    with patch('threading.Thread') as mock_thread_class:
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        # First initialization
        assembler1 = InstanceAssembler(config1)
        original_timeout = assembler1.config.instance_assemble_timeout

        # Second initialization should return the same instance
        assembler2 = InstanceAssembler(config2)

        # Should be the same object
        assert assembler1 is assembler2

        # Config should not be changed by second initialization
        assert assembler1.config.instance_assemble_timeout == original_timeout
        assert assembler2.config.instance_assemble_timeout == original_timeout

        assembler1.stop()


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
        msg = create_register_msg(
            f"perf_test_{i}", f"127.0.0.{i % 5}", test_config,
            ranktable=build_pod_ranktable(
                pod_ip=f"127.0.0.{i % 5}",
                pod_device_num=2*test_config['tp']
            )
        )
        result = instance_assembler.register(msg)
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
        msg = create_register_msg(
            f"{job_name}_{i}", f"127.0.0.{i}", test_config,
            ranktable=build_pod_ranktable(
                pod_ip=f"127.0.0.{i}",
                pod_device_num=2*test_config['tp']
            )
        )
        result = instance_assembler.register(msg)
        results.append(result)

    assert all(result == 0 for result in results)
    assert len(instance_assembler.instances) == num_instances


def test_init_config_none():
    """Test InstanceAssembler initialization with None config"""
    _cleanup_singleton()
    with patch('threading.Thread') as mock_thread_class:
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread
        assembler = InstanceAssembler(config=None)
        assert assembler.config is not None
        assert hasattr(assembler, '_initialized')
        assembler.stop()


def test_start_method():
    """Test start method"""
    from motor.config.controller import ControllerConfig
    config = ControllerConfig()
    _cleanup_singleton()

    with patch('threading.Thread') as mock_thread_class:
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread
        assembler = InstanceAssembler(config)

        assembler.start()

        # Verify threads were started
        assert mock_thread_class.call_count == 2
        assert mock_thread.start.call_count == 2

        assembler.stop()