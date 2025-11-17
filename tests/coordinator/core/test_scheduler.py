import pytest
from motor.coordinator.scheduler.scheduler import Scheduler, SchedulingPolicyType
from motor.coordinator.core.instance_manager import InstanceManager
from motor.common.resources.instance import Instance, InsStatus, PDRole, ParallelConfig
from motor.common.resources.endpoint import Endpoint, EndpointStatus, Workload, WorkloadAction
from motor.common.resources.http_msg_spec import EventType


@pytest.fixture
def prefill_instances():
    """Create prefill instances for testing."""
    instances = []
    for i in range(3):
        instance = Instance(
            job_name=f"prefill_instance_{i+1}",
            model_name="test_model",
            id=i+1,
            role=PDRole.ROLE_P,
            status=InsStatus.ACTIVE,
            parallel_config=ParallelConfig(dp=2)
        )
        instances.append(instance)
    return instances


@pytest.fixture
def decode_instances():
    """Create decode instances for testing."""
    instances = []
    for i in range(2):
        instance = Instance(
            job_name=f"decode_instance_{i+1}",
            model_name="test_model",
            id=i+4,
            role=PDRole.ROLE_D,
            status=InsStatus.ACTIVE,
            parallel_config=ParallelConfig(dp=2)
        )
        instances.append(instance)
    return instances


@pytest.fixture
def mix_instances():
    """Create mixed role instances for testing."""
    instances = []
    for i in range(2):
        instance = Instance(
            job_name=f"mix_instance_{i+1}",
            model_name="test_model",
            id=i+6,
            role=PDRole.ROLE_U,
            status=InsStatus.ACTIVE,
            parallel_config=ParallelConfig(dp=2)
        )
        instances.append(instance)
    return instances


@pytest.fixture
def scheduler_setup(prefill_instances, decode_instances, mix_instances):
    """Setup scheduler with instances and endpoints."""
    # Clear all existing instances first
    available_pool, unavailable_pool = InstanceManager().get_all_instances()
    all_existing_instances = list(available_pool.values()) + list(unavailable_pool.values())
    if all_existing_instances:
        InstanceManager().refresh_instances(EventType.DEL, all_existing_instances)

    # Add endpoints to all instances
    all_instances = prefill_instances + decode_instances + mix_instances
    InstanceManager().refresh_instances(EventType.DEL, all_instances)
    for instance in all_instances:
        endpoints = {}
        for j in range(2):  # 2 endpoints per instance
            endpoint = Endpoint(
                id=instance.id * 10 + j,
                ip=f"192.168.1.{instance.id}",
                business_port=f"800{j}",
                mgmt_port=f"900{j}",
                status=EndpointStatus.NORMAL,
                workload=Workload(active_tokens=0, active_kv_cache=0)
            )
            endpoints[j] = endpoint
        instance.add_endpoints(f"192.168.1.{instance.id}", endpoints)
        
    InstanceManager().refresh_instances(EventType.ADD, all_instances)
    return all_instances


def test_request_processing_pd_separation_scenario(scheduler_setup):
    """Test PD separation scenario with load balance policy."""
    all_instances = scheduler_setup
    scheduler = Scheduler(SchedulingPolicyType.LOAD_BALANCE)
    load_balance_scheduler = scheduler.get_scheduling_policy()
    request_length = 4
    req_id = "test_request_1"
    
    # 1. select prefill instance and endpoint
    selected_prefill_instance, selected_prefill_endpoint = load_balance_scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
    
    assert selected_prefill_instance.role == PDRole.ROLE_P
    
    # 2. allocate prefill workload
    result = load_balance_scheduler.update_workload(
        selected_prefill_instance, selected_prefill_endpoint, req_id, 
        WorkloadAction.ALLOCATION, request_length
    )
    assert result
    
    assert selected_prefill_endpoint.workload.active_tokens > 0
    assert selected_prefill_endpoint.workload.active_kv_cache > 0
    
    # 3. release active_tokens
    result = load_balance_scheduler.update_workload(
        selected_prefill_instance, selected_prefill_endpoint, req_id,
        WorkloadAction.RELEASE_TOKENS, request_length
    )
    assert result
    
    assert selected_prefill_endpoint.workload.active_tokens == 0
    assert selected_prefill_endpoint.workload.active_kv_cache > 0
    
    # 4. select decode instance and endpoint
    selected_decode_instance, selected_decode_endpoint = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_D)
    
    assert selected_decode_instance.role == PDRole.ROLE_D
    
    # 5. allocate decode workload
    result = load_balance_scheduler.update_workload(
        selected_decode_instance, selected_decode_endpoint, req_id,
        WorkloadAction.ALLOCATION, request_length
    )
    assert result
    
    assert selected_decode_endpoint.workload.active_tokens > 0
    
    # 6. release decode workload
    result = load_balance_scheduler.update_workload(
        selected_decode_instance, selected_decode_endpoint, req_id,
        WorkloadAction.RELEASE_TOKENS, request_length
    )
    assert result
    
    assert selected_decode_endpoint.workload.active_tokens == 0
    
    # 7. release prefill kv_cache
    result = load_balance_scheduler.update_workload(
        selected_prefill_instance, selected_prefill_endpoint, req_id,
        WorkloadAction.RELEASE_KV, request_length
    )
    assert result
    
    assert selected_prefill_endpoint.workload.active_kv_cache == 0


def test_request_processing_mix_scenario(scheduler_setup):
    """Test mixed role scenario with load balance policy."""
    all_instances = scheduler_setup
    scheduler = Scheduler(SchedulingPolicyType.LOAD_BALANCE)
    request_length = 4
    req_id = "test_request_mix_1"
    
    # 1. select mix instance and endpoint
    selected_instance, selected_endpoint = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_U)
    
    assert selected_instance.role == PDRole.ROLE_U
    
    # 2. allocate mix workload
    load_balance_scheduler = scheduler.get_scheduling_policy()
    result = load_balance_scheduler.update_workload(
        selected_instance, selected_endpoint, req_id,
        WorkloadAction.ALLOCATION, request_length
    )
    assert result
    
    assert selected_endpoint.workload.active_tokens > 0
    assert selected_endpoint.workload.active_kv_cache > 0
    
    # 3. release tokens
    result = load_balance_scheduler.update_workload(
        selected_instance, selected_endpoint, req_id,
        WorkloadAction.RELEASE_TOKENS, request_length
    )
    assert result
    
    assert selected_endpoint.workload.active_tokens == 0
    assert selected_endpoint.workload.active_kv_cache > 0
    
    # 4. release kv_cache
    result = load_balance_scheduler.update_workload(
        selected_instance, selected_endpoint, req_id,
        WorkloadAction.RELEASE_KV, request_length
    )
    assert result
    
    assert selected_endpoint.workload.active_tokens == 0
    assert selected_endpoint.workload.active_kv_cache == 0


@pytest.mark.parametrize("request_length", [4, 6, 3, 8, 5])
def test_multiple_requests_load_balancing(scheduler_setup, request_length):
    """Test multiple requests with different lengths."""
    all_instances = scheduler_setup
    scheduler = Scheduler(SchedulingPolicyType.LOAD_BALANCE)
    
    req_id = f"test_request_{request_length}"
    
    selected_instance, selected_endpoint = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
    
    # allocate workload
    load_balance_scheduler = scheduler.get_scheduling_policy()
    result = load_balance_scheduler.update_workload(
        selected_instance, selected_endpoint, req_id,
        WorkloadAction.ALLOCATION, request_length
    )
    assert result
    
    assert selected_endpoint.workload.active_tokens > 0
    assert selected_endpoint.workload.active_kv_cache > 0
    
    # release tokens
    result = load_balance_scheduler.update_workload(
        selected_instance, selected_endpoint, req_id,
        WorkloadAction.RELEASE_TOKENS, request_length
    )
    assert result
    
    assert selected_endpoint.workload.active_tokens == 0
    assert selected_endpoint.workload.active_kv_cache > 0


def test_workload_calculation_accuracy(scheduler_setup):
    """Test workload calculation accuracy."""
    all_instances = scheduler_setup
    scheduler = Scheduler(SchedulingPolicyType.LOAD_BALANCE)
    request_length = 4
    req_id = "test_workload_calc"
    load_balance_scheduler = scheduler.get_scheduling_policy()
    
    # select prefill instance and endpoint
    selected_instance, selected_endpoint = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
    
    # allocate prefill workload
    result = load_balance_scheduler.update_workload(
        selected_instance, selected_endpoint, req_id,
        WorkloadAction.ALLOCATION, request_length
    )
    assert result
    
    # calculate expected workload score
    expected_score = selected_endpoint.workload.active_tokens + selected_endpoint.workload.active_kv_cache * 0.3
    
    # get actual computed score
    actual_score = selected_endpoint.workload.calculate_workload_score(role=selected_instance.role)
    
    # verify that the computed score matches the expected score
    assert actual_score == expected_score
    
    # release tokens
    result = load_balance_scheduler.update_workload(
        selected_instance, selected_endpoint, req_id,
        WorkloadAction.RELEASE_TOKENS, request_length
    )
    assert result
    
    # verify that the score after release matches the expected score
    expected_score_after_release = selected_endpoint.workload.active_tokens + selected_endpoint.workload.active_kv_cache * 0.3
    actual_score_after_release = selected_endpoint.workload.calculate_workload_score(role=selected_instance.role)
    assert actual_score_after_release == expected_score_after_release


def test_load_balance_policy_selection_logic(scheduler_setup):
    """Test load balance policy selection logic."""
    all_instances = scheduler_setup
    scheduler = Scheduler(SchedulingPolicyType.LOAD_BALANCE)
    
    prefill_instance, _ = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
    assert prefill_instance is not None
    assert prefill_instance.role == PDRole.ROLE_P
    
    decode_instance, _ = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_D)
    assert decode_instance is not None
    assert decode_instance.role == PDRole.ROLE_D
    
    mix_instance, _ = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_U)
    assert mix_instance is not None
    assert mix_instance.role == PDRole.ROLE_U
    
    _, endpoint = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
    assert endpoint is not None
    assert endpoint in prefill_instance.get_all_endpoints()


def test_round_robin_instance_selection(scheduler_setup):
    """Test round robin instance selection."""
    all_instances = scheduler_setup
    scheduler = Scheduler(SchedulingPolicyType.ROUND_ROBIN)
    
    selected_instances = []
    # select 6 times, should round robin all 3 prefill instances each 2 times
    for _ in range(6):
        instance, _ = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
        assert instance is not None
        assert instance.role == PDRole.ROLE_P
        selected_instances.append(instance.id)
    
    # verify that the round robin order is correct: 1, 2, 3, 1, 2, 3
    expected_order = [1, 2, 3, 1, 2, 3]
    assert selected_instances == expected_order
    
    # select 4 times, should round robin all 2 decode instances each 2 times
    selected_decode_instances = []
    for _ in range(4):
        instance, _ = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_D)
        assert instance is not None
        assert instance.role == PDRole.ROLE_D
        selected_decode_instances.append(instance.id)
    
    # verify that the round robin order is correct: 4, 5, 4, 5
    expected_decode_order = [4, 5, 4, 5]
    assert selected_decode_instances == expected_decode_order


def test_round_robin_endpoint_selection(scheduler_setup):
    """Test round robin endpoint selection."""
    all_instances = scheduler_setup
    scheduler = Scheduler(SchedulingPolicyType.ROUND_ROBIN)
    
    # select a prefill instance
    instance, endpoint = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
    assert instance is not None
    
    # test that the endpoint selection round robin for the selected prefill instance
    selected_endpoints = []
    for _ in range(4):
        instance, endpoint = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
        assert endpoint is not None
        selected_endpoints.append(endpoint.id)
    
    # verify that the round robin order is correct
    expected_order = [20, 30, 11, 21]
    assert selected_endpoints == expected_order


def test_round_robin_mixed_role_selection(scheduler_setup):
    """Test round robin mixed role selection."""
    all_instances = scheduler_setup
    scheduler = Scheduler(SchedulingPolicyType.ROUND_ROBIN)
    
    # test that the mixed role selection round robin works as expected
    selected_instances = []
    for _ in range(9):  # select 9 times, should round robin all 3 prefill instances, 2 decode instances, 4 mix instances each 2 times
        if len(selected_instances) % 3 == 0:
            instance, _ = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
            expected_role = PDRole.ROLE_P
        elif len(selected_instances) % 3 == 1:
            instance, _ = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_D)
            expected_role = PDRole.ROLE_D
        else:
            instance, _ = scheduler.select_instance_and_endpoint(role=PDRole.ROLE_U)
            expected_role = PDRole.ROLE_U
        
        assert instance is not None
        assert instance.role == expected_role
        selected_instances.append(instance.id)


def test_round_robin_edge_cases():
    """Test round robin edge cases."""
    available_pool, unavailable_pool = InstanceManager().get_all_instances()
    all_instances = list(available_pool.values()) + list(unavailable_pool.values())
    InstanceManager().refresh_instances(EventType.DEL, all_instances)

    empty_scheduler = Scheduler(SchedulingPolicyType.ROUND_ROBIN)
    
    # test that the round robin edge cases work as expected: no instances, no endpoints
    instance, _ = empty_scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
    assert instance is None
    
    instance, _ = empty_scheduler.select_instance_and_endpoint(role=PDRole.ROLE_D)
    assert instance is None
    
    instance, _ = empty_scheduler.select_instance_and_endpoint(role=PDRole.ROLE_U)
    assert instance is None
    
    # test that the round robin edge cases work as expected: no endpoints for selected instance
    _, endpoint = empty_scheduler.select_instance_and_endpoint(role=PDRole.ROLE_P)
    assert endpoint is None
    
    # test that the round robin edge cases work as expected: no endpoints for selected instance
    _, endpoint = empty_scheduler.select_instance_and_endpoint(role=PDRole.ROLE_D)
    assert endpoint is None
