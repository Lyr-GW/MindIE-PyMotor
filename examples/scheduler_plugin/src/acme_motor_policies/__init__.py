# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Example: prefer a configured node, then minimize weighted endpoint/instance load."""

from motor.coordinator.scheduler.policy.api import LoadBalancingPolicy, RankedCandidate, SelectionInput


class WeightedLoadPolicy(LoadBalancingPolicy):
    api_version = 2

    def rank(self, selection: SelectionInput) -> list[RankedCandidate]:
        weight = float(self.options.get("instance_weight", 0.05))
        preferred_node = self.options.get("preferred_node")
        candidates = [item for item in selection.candidates if item.id not in selection.excluded]
        preferred = [item for item in candidates if item.node_address == preferred_node]
        if preferred:
            candidates = preferred
        return sorted(
            [
                RankedCandidate(item.id, item.active_tokens + weight * item.instance_active_tokens)
                for item in candidates
            ],
            key=lambda item: (item.score, item.id.instance_id, item.id.endpoint_id),
        )
