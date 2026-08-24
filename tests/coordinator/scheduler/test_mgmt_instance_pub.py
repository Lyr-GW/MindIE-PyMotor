# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Mgmt in-process refresh publishes instance deltas that Worker cache can apply_add (R2)."""

import pytest

from motor.common.resources.endpoint import Endpoint, EndpointStatus, Workload
from motor.common.resources.http_msg_spec import EventType
from motor.common.resources.instance import Instance, InsStatus, PDRole, ParallelConfig
from motor.config.coordinator import CoordinatorConfig
from motor.coordinator.domain.instance_manager import InstanceManager
from motor.coordinator.scheduler.runtime.scheduler_client import _SchedulerInstanceCache
from motor.coordinator.scheduler.runtime.scheduler_server import (
    AsyncSchedulerServer,
    _SchedulerRequestDispatcher,
    _instance_from_dict,
)
from motor.coordinator.scheduler.runtime.zmq_protocol import SchedulerRequestType
from motor.coordinator.scheduler.scheduler import Scheduler


def test_hot_path_rpcs_removed_from_protocol():
    """P3 gate: ALLOCATE / UPDATE / REFRESH must not exist on the control-plane enum."""
    names = {member.name for member in SchedulerRequestType}
    assert "ALLOCATE_ONLY" not in names
    assert "UPDATE_WORKLOAD" not in names
    assert "REFRESH_INSTANCES" not in names
    assert "GET_AVAILABLE_INSTANCES" in names
    assert "CIRCUIT_BREAKER_REPORT" in names


def _make_instance(instance_id: int = 7) -> Instance:
    inst = Instance(
        job_name="p-7",
        model_name="test_model",
        id=instance_id,
        role=PDRole.ROLE_P,
        status=InsStatus.ACTIVE,
        parallel_config=ParallelConfig(dp_size=1),
    )
    inst.add_endpoints(
        "pod-7",
        {
            0: Endpoint(
                id=70,
                ip="10.0.0.7",
                business_port="8080",
                mgmt_port="9080",
                status=EndpointStatus.NORMAL,
                workload=Workload(),
            )
        },
    )
    return inst


@pytest.mark.asyncio
async def test_mgmt_refresh_delta_applies_to_worker_cache():
    """apply_refresh ADD -> PUB delta payload -> Worker cache.apply_add (no REFRESH_INSTANCES RPC)."""
    config = CoordinatorConfig()
    im = InstanceManager(config)
    scheduler = Scheduler(instance_provider=im, config=config)
    published: list[tuple] = []

    async def on_done(event_type, instances):
        published.append((event_type, instances))

    dispatcher = _SchedulerRequestDispatcher(
        im,
        scheduler,
        config,
        on_instance_refresh_done=on_done,
    )
    inst = _make_instance()
    changed = await dispatcher.apply_refresh(EventType.ADD, [inst])
    assert changed is True
    assert published and published[0][0] == EventType.ADD

    server = AsyncSchedulerServer(config, instance_manager=im)
    delta = server._build_instance_delta(EventType.ADD, published[0][1])
    assert delta is not None
    assert delta["event"] == "add"
    rebuilt = [_instance_from_dict(d) for d in delta["instances"]]
    rebuilt = [x for x in rebuilt if x is not None]
    cache = _SchedulerInstanceCache()
    assert await cache.apply_add(rebuilt) is True
    assert [i.id for i in cache.get_instances(PDRole.ROLE_P)] == [7]
