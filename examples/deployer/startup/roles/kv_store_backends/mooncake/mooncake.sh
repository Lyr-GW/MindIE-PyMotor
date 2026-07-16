#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

export LD_LIBRARY_PATH=/driver/lib64/driver:/driver/lib64/common:/usr/local/Ascend/driver/lib64/driver:/usr/local/Ascend/driver/lib64/common:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/local/Ascend/ascend-toolkit/latest/python/site-packages/mooncake:$LD_LIBRARY_PATH

if [ -z "${MOONCAKE_MASTER_RPC_ADDRESS:-}" ]; then
    if [[ "${POD_IP:-}" == *:* ]]; then
        MOONCAKE_MASTER_RPC_ADDRESS="::"
    else
        MOONCAKE_MASTER_RPC_ADDRESS="0.0.0.0"
    fi
fi

mooncake_master --rpc_port "$KV_CACHE_STORE_PORT" \
    --rpc_address "$MOONCAKE_MASTER_RPC_ADDRESS" \
    --eviction_high_watermark_ratio "$KV_STORE_EVICTION_HIGH_WATERMARK_RATIO" \
    --eviction_ratio "$KV_STORE_EVICTION_RATIO" --default_kv_lease_ttl "$DEFAULT_KV_LEASE_TTL"
