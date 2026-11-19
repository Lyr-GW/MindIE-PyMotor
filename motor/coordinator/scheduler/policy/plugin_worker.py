# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""In-process entry point loader for external endpoint selection policies."""

import inspect
from collections.abc import Mapping
from importlib.metadata import entry_points
from typing import Any

from motor.common.logger import get_logger
from motor.coordinator.scheduler.policy.api import (
    SUPPORTED_POLICY_API_VERSION,
    EndpointSelectionPolicy,
)

logger = get_logger(__name__)

ENTRY_POINT_GROUP = "mindie_motor.scheduling_policies"


def load_policy(name: str, options: Mapping[str, Any] | None) -> EndpointSelectionPolicy:
    """Load exactly one configured class and validate its API contract."""
    entries = [entry for entry in entry_points(group=ENTRY_POINT_GROUP) if entry.name == name]
    if len(entries) != 1:
        raise ValueError("Expected exactly one entry point for %r, found %d" % (name, len(entries)))
    entry = entries[0]
    dist = getattr(entry, "dist", None)
    logger.info(
        "Scheduling plugin source name=%s package=%s version=%s entry=%s",
        name,
        dist.metadata.get("Name", "?") if dist is not None else "?",
        dist.version if dist is not None else "?",
        entry.value,
    )
    policy_class = entry.load()
    if not isinstance(policy_class, type) or not issubclass(policy_class, EndpointSelectionPolicy):
        raise ValueError("Entry point must be an EndpointSelectionPolicy subclass")
    if policy_class.api_version != SUPPORTED_POLICY_API_VERSION:
        raise ValueError("Incompatible scheduling policy API version")
    if (
        inspect.isabstract(policy_class)
        or not callable(policy_class.rank)
        or inspect.iscoroutinefunction(policy_class.rank)
    ):
        raise ValueError("Policy must override synchronous rank()")
    return policy_class(options=dict(options or {}))
