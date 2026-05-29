# -*- coding: utf-8 -*-
"""Regression tests for ROLE_U support in KVA register/select flows."""

from unittest.mock import Mock, patch

from motor.common.resources.instance import PDRole
from motor.coordinator.api_client.conductor_api_client import ConductorApiClient
from motor.coordinator.scheduler.runtime.scheduler_client import (
    AsyncSchedulerClient,
    SchedulerClientConfig,
)


def _build_instance(role: PDRole) -> Mock:
    instance = Mock()
    instance.role = role
    endpoint = Mock()
    instance.endpoints = {"pod-0": {0: endpoint}}
    return instance


def _build_kv_client() -> AsyncSchedulerClient:
    return AsyncSchedulerClient(
        SchedulerClientConfig(
            scheduler_type="kv_cache_affinity",
        )
    )


def test_register_kv_instance_supports_role_u() -> None:
    instances = [
        _build_instance(PDRole.ROLE_P),
        _build_instance(PDRole.ROLE_U),
        _build_instance(PDRole.ROLE_D),
    ]
    with patch.object(ConductorApiClient, "register_post") as mock_register_post:
        ConductorApiClient.register_kv_instance(instances)

    assert mock_register_post.call_count == 2
    called_roles = {call.args[0].role for call in mock_register_post.call_args_list}
    assert called_roles == {PDRole.ROLE_P, PDRole.ROLE_U}


def test_unregister_kv_instance_supports_role_u() -> None:
    instances = [
        _build_instance(PDRole.ROLE_P),
        _build_instance(PDRole.ROLE_U),
        _build_instance(PDRole.ROLE_D),
    ]
    with patch.object(ConductorApiClient, "unregister_post") as mock_unregister_post:
        ConductorApiClient.unregister_kv_instance(instances)

    assert mock_unregister_post.call_count == 2
    called_roles = {call.args[0].role for call in mock_unregister_post.call_args_list}
    assert called_roles == {PDRole.ROLE_P, PDRole.ROLE_U}


def test_kv_cache_affinity_uses_kva_for_role_u() -> None:
    client = _build_kv_client()
    instance = Mock()
    endpoint = Mock()
    req_info = Mock()

    with patch(
        "motor.coordinator.scheduler.runtime.scheduler_client."
        "KvCacheAffinityPolicy.select_endpoint_from_list",
        return_value=(instance, endpoint),
    ) as mock_kva, patch.object(
        client,
        "_select_instance_and_endpoint_by_load_balance",
    ) as mock_load_balance:
        result = client._select_instance_and_endpoint_from_list(
            [instance], PDRole.ROLE_U, req_info
        )

    assert result == (instance, endpoint)
    mock_kva.assert_called_once_with([instance], req_info)
    mock_load_balance.assert_not_called()


def test_kv_cache_affinity_falls_back_to_load_balance_for_role_u() -> None:
    client = _build_kv_client()
    instance = Mock()
    endpoint = Mock()
    req_info = Mock()
    lb_instance = Mock()

    with patch(
        "motor.coordinator.scheduler.runtime.scheduler_client."
        "KvCacheAffinityPolicy.select_endpoint_from_list",
        return_value=None,
    ) as mock_kva, patch.object(
        client,
        "_select_instance_and_endpoint_by_load_balance",
        return_value=lb_instance,
    ) as mock_load_balance, patch.object(
        client,
        "_select_endpoint_for_instance",
        return_value=(lb_instance, endpoint),
    ) as mock_select_endpoint:
        result = client._select_instance_and_endpoint_from_list(
            [instance], PDRole.ROLE_U, req_info
        )

    assert result == (lb_instance, endpoint)
    mock_kva.assert_called_once_with([instance], req_info)
    mock_load_balance.assert_called_once_with([instance], PDRole.ROLE_U)
    mock_select_endpoint.assert_called_once_with(lb_instance)


def test_kv_cache_affinity_skips_kva_for_non_kva_roles() -> None:
    client = _build_kv_client()
    instance = Mock()
    endpoint = Mock()
    req_info = Mock()
    lb_instance = Mock()

    with patch(
        "motor.coordinator.scheduler.runtime.scheduler_client."
        "KvCacheAffinityPolicy.select_endpoint_from_list"
    ) as mock_kva, patch.object(
        client,
        "_select_instance_and_endpoint_by_load_balance",
        return_value=lb_instance,
    ) as mock_load_balance, patch.object(
        client,
        "_select_endpoint_for_instance",
        return_value=(lb_instance, endpoint),
    ) as mock_select_endpoint:
        result = client._select_instance_and_endpoint_from_list(
            [instance], PDRole.ROLE_D, req_info
        )

    assert result == (lb_instance, endpoint)
    mock_kva.assert_not_called()
    mock_load_balance.assert_called_once_with([instance], PDRole.ROLE_D)
    mock_select_endpoint.assert_called_once_with(lb_instance)
