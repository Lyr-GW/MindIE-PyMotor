# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
Controller module - main entry point for the controller service.

This module provides the core controller functionality including instance management,
API serving, and fault tolerance capabilities.
"""

__all__ = [
    # Main functions
    "init_all_modules",
    "start_all_modules",
    "stop_all_modules",
    "get_controller_status",
    "on_become_master",
    "on_become_standby",
    "main",

    # Submodules
    "api_server",
    "core",
    "ft",
]

from .main import (
    init_all_modules,
    start_all_modules,
    stop_all_modules,
    get_controller_status,
    on_become_master,
    on_become_standby,
    main
)
from . import api_server
from . import core
from . import ft
