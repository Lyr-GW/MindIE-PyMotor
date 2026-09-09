# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""Built-in scheduling policies adapted to the LoadBalancingPolicy rank() interface."""

from __future__ import annotations

import math
from collections.abc import Sequence

from motor.config.coordinator import (
    KV_AFFINITY_MODE_LOAD_GATED,
    KV_AFFINITY_MODE_UNIFIED,
)
from motor.coordinator.scheduler.policy.api import (
    CandidateId,
    LoadBalancingPolicy,
    RankedCandidate,
    SelectionInput,
)
from motor.coordinator.scheduler.policy.kv_cache_affinity import KvCacheAffinityPolicy


class BuiltinLoadBalancePolicy(LoadBalancingPolicy):
    """Built-in load_balance strategy exposed through rank()."""

    api_version = 1
    requires_kv_match = False

    def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
        weight = float(self.options.get("instance_score_weight", 0.05))
        tie_order = 0
        scored: list[tuple[float, int, RankedCandidate]] = []
        for candidate in selection.candidates:
            if candidate.id in selection.excluded or candidate.blocked:
                continue
            endpoint_count = 1
            if candidate.attributes and "endpoint_count" in candidate.attributes:
                try:
                    endpoint_count = max(1, int(candidate.attributes["endpoint_count"]))
                except ValueError:
                    endpoint_count = 1
            score = candidate.active_tokens + weight * (candidate.instance_active_tokens / endpoint_count)
            item = RankedCandidate(id=candidate.id, score=score)
            scored.append((score, tie_order, item))
            tie_order += 1
        scored.sort(key=lambda item: (item[0], item[1]))
        return [item for _, _, item in scored]


class BuiltinRoundRobinPolicy(LoadBalancingPolicy):
    """Built-in round_robin strategy exposed through rank()."""

    api_version = 1
    requires_kv_match = False

    def __init__(self, options=None) -> None:
        super().__init__(options)
        self._counter = int(self.options.get("start_counter", 0))

    def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
        eligible = [
            candidate
            for candidate in selection.candidates
            if candidate.id not in selection.excluded and not candidate.blocked
        ]
        if not eligible:
            return []
        n = len(eligible)
        start = self._counter % n
        self._counter = (self._counter + 1) % n if n else self._counter
        ordered = [eligible[(start + i) % n] for i in range(n)]
        return [RankedCandidate(id=candidate.id, score=float(index)) for index, candidate in enumerate(ordered)]


class BuiltinKvCacheAffinityPolicy(LoadBalancingPolicy):
    """Built-in kv_cache_affinity strategy exposed through rank()."""

    api_version = 1
    requires_kv_match = True

    def rank(self, selection: SelectionInput) -> Sequence[RankedCandidate]:
        mode = str(self.options.get("mode", KV_AFFINITY_MODE_UNIFIED)).lower()
        overlap_credit = float(self.options.get("overlap_credit", 1.0))
        prefill_load_scale = float(self.options.get("prefill_load_scale", 1.0))
        load_weight = float(self.options.get("load_weight", 1.0))
        load_gate_topn = int(self.options.get("load_gate_topn", 0))
        w_npu = float(self.options.get("w_npu", 1.0))
        w_cpu = float(self.options.get("w_cpu", 1.0))
        w_disk = float(self.options.get("w_disk", 0.0))
        lookup = self.options.get("_instance_lookup")
        if not callable(lookup):
            return []
        instances = []
        for candidate in selection.candidates:
            if candidate.id in selection.excluded or candidate.blocked:
                continue
            resolved = lookup(candidate.id.instance_id, candidate.id.endpoint_id)
            if resolved is None:
                continue
            instance, endpoint = resolved
            endpoint.workload.active_tokens = candidate.active_tokens
            instances.append(instance)
        if not instances:
            return []
        unique_instances = list({inst.id: inst for inst in instances}.values())
        req_info = self.options.get("_req_info")
        if req_info is None:
            return []
        ranked_legacy = KvCacheAffinityPolicy.select_endpoint_candidates_from_list(
            unique_instances,
            req_info,
            mode=mode,
            overlap_credit=overlap_credit,
            prefill_load_scale=prefill_load_scale,
            load_weight=load_weight,
            load_gate_topn=load_gate_topn,
            w_npu=w_npu,
            w_cpu=w_cpu,
            w_disk=w_disk,
            top_k=len(unique_instances) * 8,
        )
        if not ranked_legacy:
            if mode == KV_AFFINITY_MODE_LOAD_GATED:
                return BuiltinLoadBalancePolicy(options=self.options).rank(selection)
            return BuiltinLoadBalancePolicy(options=self.options).rank(selection)
        result: list[RankedCandidate] = []
        for instance, endpoint, score in ranked_legacy:
            cid = CandidateId(instance_id=instance.id, endpoint_id=endpoint.id)
            if cid in selection.excluded:
                continue
            if not math.isfinite(score):
                continue
            result.append(RankedCandidate(id=cid, score=score))
        return result
