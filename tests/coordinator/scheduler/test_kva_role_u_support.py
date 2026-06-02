# -*- coding: utf-8 -*-
"""Regression tests for ROLE_U support in KVA register/select flows."""

from unittest.mock import Mock, patch

from motor.common.resources.instance import PDRole
from motor.coordinator.api_client.conductor_api_client import ConductorApiClient


def _build_instance(role: PDRole) -> Mock:
    instance = Mock()
    instance.role = role
    endpoint = Mock()
    instance.endpoints = {"pod-0": {0: endpoint}}
    return instance


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
