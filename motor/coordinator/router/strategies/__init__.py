# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.

"""Routing strategy implementations (PD/CDP/hybrid/dual-dispatch)."""

__all__ = [
    "BaseRouter",
    "PDHybridRouter",
    "RecomputeState",
    "SeparateCDPRouter",
    "SeparatePDDualDispatchRouter",
    "SeparatePDRouter",
]

from motor.coordinator.router.strategies.base import BaseRouter, RecomputeState
from motor.coordinator.router.strategies.cdp_separate import SeparateCDPRouter
from motor.coordinator.router.strategies.pd_dual_dispatch import SeparatePDDualDispatchRouter
from motor.coordinator.router.strategies.pd_hybrid import PDHybridRouter
from motor.coordinator.router.strategies.pd_separate import SeparatePDRouter
