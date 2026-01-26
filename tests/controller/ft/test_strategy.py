#!/usr/bin/env python3
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

import pytest
from unittest.mock import Mock, patch

from motor.controller.ft.strategy.strategy import (
    StrategyBase,
    general_level0_strategy,
    specific_level2_strategy,
    general_level3_to_level6_strategy,
    generate_strategy_map,
)
from motor.controller.ft.strategy.lingqu_network_recover import (
    LingquNetworkRecoverStrategy,
)
from motor.controller.ft.strategy.scale_p2d import ScaleP2DStrategy
from motor.config.controller import ControllerConfig


# Fixtures
@pytest.fixture
def mock_config():
    """Fixture for creating a mock config with strategies enabled"""
    config = ControllerConfig()
    config.fault_tolerance_config.enable_scale_p2d = True
    config.fault_tolerance_config.enable_lingqu_network_recover = True
    return config


@pytest.fixture
def mock_config_scale_p2d_disabled():
    """Fixture for creating a mock config with scale_p2d disabled"""
    config = ControllerConfig()
    config.fault_tolerance_config.enable_scale_p2d = False
    config.fault_tolerance_config.enable_lingqu_network_recover = True
    return config


@pytest.fixture
def mock_config_lingqu_disabled():
    """Fixture for creating a mock config with lingqu network recover disabled"""
    config = ControllerConfig()
    config.fault_tolerance_config.enable_scale_p2d = True
    config.fault_tolerance_config.enable_lingqu_network_recover = False
    return config


@pytest.fixture
def mock_instance_manager():
    """Fixture for mocking InstanceManager"""
    with patch('motor.controller.core.instance_manager.InstanceManager') as mock:
        yield mock


@pytest.fixture
def decode_instance():
    """Fixture for creating a decode role instance"""
    instance = Mock()
    instance.role = "decode"
    return instance


@pytest.fixture
def encode_instance():
    """Fixture for creating an encode role instance"""
    instance = Mock()
    instance.role = "encode"
    return instance


# StrategyBase Tests
def test_strategy_base_execute_raises_not_implemented_error():
    """StrategyBase.execute should raise NotImplementedError when not implemented"""

    class ConcreteStrategy(StrategyBase):
        def execute(self, instance_id):
            raise NotImplementedError("execute method not implemented")

        def stop(self):
            raise NotImplementedError("stop method not implemented")

    strategy = ConcreteStrategy()

    with pytest.raises(NotImplementedError, match="execute method not implemented"):
        strategy.execute(instance_id=None)  # type: ignore[arg-type]


# L0 Strategy Tests
@pytest.mark.parametrize("fault_code", [0x0000, 0x00f1fef5, 0x08520003, 0x12345678])
def test_general_l0_strategy_returns_none_for_any_fault_code(fault_code, mock_config):
    """L0 strategy should always return None since it represents healthy state"""
    assert general_level0_strategy(fault_code, 1, mock_config) is None


# L2 Strategy Tests
@pytest.mark.parametrize("fault_code,expected", [
    (0x00f1fef5, LingquNetworkRecoverStrategy),
    (0x08520003, LingquNetworkRecoverStrategy),
    (0, None),
    (0x0000, None),
])
def test_specific_l2_strategy_returns_correct_class(fault_code, expected, mock_config):
    """L2 strategy should return LingquNetworkRecoverStrategy for known codes, None otherwise"""
    assert specific_level2_strategy(fault_code, 1, mock_config) is expected


# L3-L6 Strategy Tests
def test_general_l3_to_l6_strategy_returns_scale_p2d_for_decode_role(
    mock_instance_manager, decode_instance, mock_config
):
    """When instance role is decode, L3-L6 strategy should return ScaleP2DStrategy"""
    mock_instance_manager.return_value.get_instance.return_value = decode_instance

    result = general_level3_to_level6_strategy(0x0000, 1, mock_config)

    assert result is ScaleP2DStrategy


def test_general_l3_to_l6_strategy_returns_none_for_non_decode_role(
    mock_instance_manager, encode_instance, mock_config
):
    """When instance role is not decode, L3-L6 strategy should return None"""
    mock_instance_manager.return_value.get_instance.return_value = encode_instance

    result = general_level3_to_level6_strategy(0x0000, 1, mock_config)

    assert result is None


def test_general_l3_to_l6_strategy_returns_none_when_instance_is_none(mock_instance_manager, mock_config):
    """When instance is None, L3-L6 strategy should return None"""
    mock_instance_manager.return_value.get_instance.return_value = None

    result = general_level3_to_level6_strategy(0x0000, 1, mock_config)

    assert result is None


# Strategy Map Generation Tests
def test_generate_strategy_map_contains_expected_levels():
    """Strategy map should contain all expected fault levels"""
    strategies = generate_strategy_map()

    assert set(strategies.keys()) == {"L0", "L1", "L2", "L3", "L4", "L5", "L6"}


@pytest.mark.parametrize("level", ["L0", "L1"])
def test_strategy_map_level_returns_none_for_l0_and_l1(level, mock_config):
    """L0 and L1 strategies should always return None"""
    strategies = generate_strategy_map()
    strategy_func = strategies[level]

    assert callable(strategy_func)
    assert strategy_func(0x0000, 1, mock_config) is None


def test_strategy_map_l2_returns_lingqu_network_recover_for_known_codes(mock_config):
    """L2 strategy should return LingquNetworkRecoverStrategy for known error codes"""
    strategies = generate_strategy_map()
    l2_func = strategies["L2"]

    assert callable(l2_func)
    assert l2_func(0x00f1fef5, 1, mock_config) is LingquNetworkRecoverStrategy
    assert l2_func(0x08520003, 1, mock_config) is LingquNetworkRecoverStrategy
    assert l2_func(0, 1, mock_config) is None


@pytest.mark.parametrize("level", ["L3", "L4", "L5", "L6"])
def test_strategy_map_l3_to_l6_returns_scale_p2d_for_decode_role(
    level, mock_instance_manager, decode_instance, mock_config
):
    """L3-L6 strategies should return ScaleP2DStrategy when instance role is decode"""
    mock_instance_manager.return_value.get_instance.return_value = decode_instance

    strategies = generate_strategy_map()
    strategy_func = strategies[level]

    assert callable(strategy_func)
    assert strategy_func(0x0000, 1, mock_config) is ScaleP2DStrategy


def test_specific_l2_strategy_respects_config_switch(mock_config_lingqu_disabled):
    """L2 strategy should return None when lingqu network recover is disabled in config"""
    result = specific_level2_strategy(0x00f1fef5, 1, mock_config_lingqu_disabled)
    assert result is None

    result = specific_level2_strategy(0x08520003, 1, mock_config_lingqu_disabled)
    assert result is None


def test_general_l3_to_l6_strategy_respects_config_switch(
    mock_instance_manager, decode_instance, mock_config_scale_p2d_disabled
):
    """L3-L6 strategy should return None when scale_p2d is disabled in config"""
    mock_instance_manager.return_value.get_instance.return_value = decode_instance

    result = general_level3_to_level6_strategy(0x0000, 1, mock_config_scale_p2d_disabled)
    assert result is None