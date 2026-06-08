# Function Call 亲和性调度 详细设计

> 适用代码范围：`motor/coordinator/scheduler/policy/function_call_affinity.py`、
> `motor/coordinator/scheduler/policy/factory.py`、`motor/config/coordinator.py`、
> `motor/coordinator/scheduler/runtime/scheduler_client.py`。

---

## 1. 背景与动机

LLM Agent / Function-Call 工作负载具有极强的**前缀复用**特征：

1. **`tools` schema 共享**：同一 Agent 在多个请求里通常重复使用相同的 tool 定义，长度可达数千 tokens，是一段稳定的"长前缀"。
2. **多轮 `tool_calls`**：随着对话轮数增长，前缀单调累加，但工具集保持稳定。
3. **conductor 不可用 / tokenizer 缺失**：现有 `kv_cache_affinity` 依赖 conductor 服务返回的 token-id 最长前缀匹配长度，当 conductor 不可达、tokenizer 未加载，或匹配长度为 0 时，会**完全退化为负载均衡**，丢失 KV-cache 复用机会。

针对上述问题，本特性新增 `function_call_affinity` 调度策略，通过**对 tools schema 取稳定指纹做 sticky 路由**，在 conductor 信号缺失或 KV 命中为 0 的边界场景下仍能稳定提高 cache 命中率。

### 1.1 与现有策略的差异

| 维度 | round_robin | load_balance | kv_cache_affinity | **function_call_affinity** |
| --- | --- | --- | --- | --- |
| 选择信号 | 计数器 | 实时负载 | conductor 返回的最长 token-id 匹配 | tools 指纹 + 上述全部 |
| 是否依赖 conductor | 否 | 否 | **是** | 否（缺失时 fallback） |
| 是否依赖 tokenizer | 否 | 否 | **是** | 否（缺失时 fallback） |
| 多轮粘性 | 无 | 无 | 取决于 token-id 重叠 | **强（指纹相同即粘性）** |
| 失败回退 | 无 | round_robin | load_balance → round_robin | kv_cache_affinity → load_balance → round_robin |

---

## 2. 设计目标

| ID | 目标 | 验收 |
| --- | --- | --- |
| G1 | 同 tools schema 的请求尽量被路由到同一 `(instance, endpoint)` | 单元测试 `test_sticky_routing_on_fingerprint_hit` |
| G2 | 实例下线 / endpoint 下线时自动失效粘性记录 | `test_sticky_invalidated_when_instance_gone` / `test_sticky_invalidated_when_endpoint_gone` |
| G3 | conductor / tokenizer 不可用时仍能调度（不破坏可用性） | `test_falls_back_to_load_balance_when_kv_fails` |
| G4 | 内存与延迟可控（缓存大小、TTL 可配置；hot path 单锁） | LRU+TTL 设计 + 并发压测 |
| G5 | 完全向后兼容：未启用时所有现有路径行为不变 | factory 注册式接入；`SchedulerType` 仅新增枚举 |
| G6 | 不依赖 conductor / tokenizer，可在 kv_cache_affinity 不可用环境下独立工作 | sticky-only 路径无外部依赖 |

---

## 3. 总体架构

### 3.1 上下文图（C4-Context 视角）

```mermaid
flowchart LR
    Client[OpenAI 兼容客户端]
    subgraph Coordinator
        APIServer[Inference API Server]
        Dispatcher[Router / dispatch.py]
        SchedClient[AsyncSchedulerClient]
        SchedSrv[AsyncSchedulerServer]
        Policy[FunctionCallAffinityPolicy]
        Cache[(ToolsAffinityCache<br/>LRU + TTL)]
    end
    Conductor[Conductor 服务<br/>可选]
    EngineP[Prefill 实例]
    EngineD[Decode 实例]

    Client -- "/v1/chat/completions 含 tools" --> APIServer
    APIServer --> Dispatcher
    Dispatcher --> SchedClient
    SchedClient -- "候选 instances + req_info" --> Policy
    Policy <-- "get/put fingerprint" --> Cache
    Policy -. fallback .-> Conductor
    Policy -- "返回 instance, endpoint" --> SchedClient
    SchedClient --> EngineP
    SchedClient --> EngineD
    SchedClient <-- "订阅实例变更" --> SchedSrv
```

### 3.2 进程内组件层次

```mermaid
flowchart TB
    subgraph runtime[motor.coordinator.scheduler.runtime]
        SchedClient[AsyncSchedulerClient<br/>scheduler_client.py]
    end

    subgraph policy[motor.coordinator.scheduler.policy]
        Base[BaseSchedulingPolicy]
        Factory[SchedulingPolicyFactory<br/>factory.py]
        FCAP[FunctionCallAffinityPolicy<br/>function_call_affinity.py]
        KVCA[KvCacheAffinityPolicy<br/>kv_cache_affinity.py]
        LB[LoadBalancePolicy<br/>load_balance.py]
        RR[RoundRobinPolicy<br/>round_robin.py]
    end

    subgraph helpers[helpers in function_call_affinity.py]
        Fingerprint[compute_tools_fingerprint]
        Signal[has_function_call_signal]
        Cache[ToolsAffinityCache<br/>LRU + TTL]
    end

    SchedClient -->|静态调用| FCAP
    Factory -->|create FUNCTION_CALL_AFFINITY| FCAP
    FCAP --> Base
    FCAP -->|fallback 1| KVCA
    FCAP -->|fallback 2| LB
    FCAP --> Fingerprint
    FCAP --> Signal
    FCAP --> Cache
```

---

## 4. 关键类与数据结构

### 4.1 类图

```mermaid
classDiagram
    class BaseSchedulingPolicy {
        <<abstract>>
        +InstanceProvider _instance_provider
        +select_instance_and_endpoint(role) tuple
        #_select_instance(role) Instance
        #_select_endpoint(instance) Endpoint
    }

    class FunctionCallAffinityPolicy {
        +ToolsAffinityCache affinity_cache
        +select_endpoint_from_list(instances, req_info) tuple$
        +reset_global_cache_for_testing() void$
        +select_endpoint_from_list_with_cache(instances, req_info) tuple
        #_select_instance(role) None
        #_select_endpoint(instance) None
    }

    class KvCacheAffinityPolicy {
        +select_endpoint_from_list(instances, req_info) tuple$
    }

    class LoadBalancePolicy {
        +select_instance_from_list(instances, role, start_index) Instance$
        +select_endpoint_from_instance(instance) Endpoint$
    }

    class ToolsAffinityCache {
        -OrderedDict _data
        -RLock _lock
        -int _max_size
        -float _ttl
        +get(fingerprint) AffinityRecord
        +put(fingerprint, instance_id, endpoint_id) void
        +size() int
        +clear() void
    }

    class AffinityRecord {
        <<frozen>>
        +int instance_id
        +int endpoint_id
        +float inserted_at
    }

    BaseSchedulingPolicy <|-- FunctionCallAffinityPolicy
    BaseSchedulingPolicy <|-- KvCacheAffinityPolicy
    BaseSchedulingPolicy <|-- LoadBalancePolicy
    FunctionCallAffinityPolicy --> ToolsAffinityCache
    FunctionCallAffinityPolicy ..> KvCacheAffinityPolicy : fallback
    FunctionCallAffinityPolicy ..> LoadBalancePolicy : fallback
    ToolsAffinityCache *-- AffinityRecord : 1..*
```

### 4.2 缓存数据结构

`ToolsAffinityCache` 使用 `OrderedDict` 实现 LRU，附加 `inserted_at` 字段做 TTL 判定。读路径单 `RLock`；过期项在 `get` 中 lazy 淘汰（避免后台线程）。

```mermaid
flowchart LR
    subgraph OD[OrderedDict 顺序：左旧 → 右新]
        direction LR
        A["fp_a → AffinityRecord(iid=1, eid=10, t=100.0)"]
        B["fp_b → AffinityRecord(iid=2, eid=20, t=120.0)"]
        C["fp_c → AffinityRecord(iid=2, eid=21, t=140.0)"]
    end

    Get1["get(fp_b)<br/>命中且未过期<br/>move_to_end"] --> OD
    Put1["put(fp_d, ...)<br/>size > max_size<br/>popitem(last=False)"] --> OD
```

### 4.3 指纹生成

```mermaid
flowchart LR
    Tools["tools: list[dict]"] --> WalkBytes{含 bytes/<br/>bytearray 叶子?}
    WalkBytes -- 是 --> NoneOut[返回 None]
    WalkBytes -- 否 --> Each["对每个 tool<br/>json.dumps(sort_keys=True,<br/>default=str)"]
    Each -- 失败 TypeError/<br/>ValueError --> NoneOut
    Each --> Join["用 \\x1f 连接<br/>保留列表顺序"]
    Join --> Hash["sha256(...).hexdigest()"]
    Hash --> Out[fingerprint: str]
```

要点：

- **键内排序**：`sort_keys=True` 让相同字段不同顺序产生相同指纹。
- **列表外不排序**：tools 顺序会影响 chat-template 渲染输出与 prefix 局部性，必须保留。
- **bytes 拒绝**：`json.dumps(default=str)` 会把 `bytes` 静默 `str()` 化产生不稳定值，因此先 `_walk_values` 拒绝。
- **稳定性**：仅依赖标准库 `json` + `hashlib.sha256`，跨进程/跨主机一致。

---

## 5. 调度算法（核心流程）

### 5.1 主流程图

```mermaid
flowchart TD
    Start([select_endpoint_from_list]) --> Empty{instances<br/>为空?}
    Empty -- 是 --> RetNone1([return None])
    Empty -- 否 --> Signal{has_function_<br/>call_signal?}
    Signal -- 否 --> KV1
    Signal -- 是 --> Tools{tools 字段<br/>存在?}
    Tools -- 否 --> KV1
    Tools -- 是 --> FP[compute_tools_fingerprint]
    FP -- None --> KV1
    FP -- hex --> Hit{cache.get<br/>命中?}
    Hit -- 否 --> KV1
    Hit -- 是 --> InList{instance<br/>仍在候选?}
    InList -- 否 --> KV1
    InList -- 是 --> EpAlive{endpoint 仍<br/>存在?}
    EpAlive -- 否 --> KV1
    EpAlive -- 是 --> Sticky([Sticky 命中:<br/>return instance, endpoint])

    KV1[KvCacheAffinity<br/>select_endpoint_from_list]
    KV1 -- 异常 --> KV2[捕获 + warning]
    KV1 -- result --> KvOk{result<br/>非 None?}
    KV2 --> KvOk
    KvOk -- 是 --> CachePut1[fp 非 None?<br/>cache.put]
    CachePut1 --> RetKv([return kv_pair])
    KvOk -- 否 --> LB1[LoadBalance<br/>select_instance_from_list]
    LB1 --> LbInst{instance<br/>非 None?}
    LbInst -- 否 --> RetNone2([return None])
    LbInst -- 是 --> LB2[LoadBalance<br/>select_endpoint_from_instance]
    LB2 --> LbEp{endpoint<br/>非 None?}
    LbEp -- 否 --> RetNone3([return None])
    LbEp -- 是 --> CachePut2[fp 非 None?<br/>cache.put]
    CachePut2 --> RetLb([return lb_pair])
```

### 5.2 状态图：单条指纹的生命周期

```mermaid
stateDiagram-v2
    [*] --> Absent : 进程启动
    Absent --> Active : put(fp, iid, eid)
    Active --> Active : get/put 刷新 LRU
    Active --> Expired : now - inserted_at > ttl
    Active --> Evicted : LRU 满 + 被挤出
    Active --> Absent : reset_global_cache_for_testing()
    Active --> StaleInstance : 命中但 instance 已下线
    Active --> StaleEndpoint : 命中但 endpoint 已下线
    StaleInstance --> Active : KV/LB 选出新 (iid', eid')<br/>cache.put 覆盖
    StaleEndpoint --> Active : KV/LB 选出新 (iid', eid')<br/>cache.put 覆盖
    Expired --> Absent : 下次 get 时被 lazy 淘汰
    Evicted --> [*]
```

---

## 6. 时序图

### 6.1 同 tools schema 三次连续请求（典型场景）

```mermaid
sequenceDiagram
    autonumber
    participant Cli as Client
    participant Disp as Router
    participant SC as AsyncSchedulerClient
    participant FCA as FunctionCallAffinityPolicy
    participant Cache as ToolsAffinityCache
    participant KV as KvCacheAffinityPolicy
    participant Inst as Instance/Endpoint

    Note over Cli,Inst: 第 1 次请求 (cache miss)
    Cli->>Disp: POST /v1/chat/completions<br/>{tools=[T_a, T_b], messages=[...]}
    Disp->>SC: select_instance_and_endpoint(req_info, ROLE_P)
    SC->>FCA: select_endpoint_from_list(instances, req_info)
    FCA->>FCA: has_function_call_signal -> true
    FCA->>FCA: fp = sha256(canon(tools))
    FCA->>Cache: get(fp) -> None
    FCA->>KV: select_endpoint_from_list(instances, req_info)
    KV-->>FCA: (Inst_2, Ep_20)
    FCA->>Cache: put(fp, 2, 20)
    FCA-->>SC: (Inst_2, Ep_20)
    SC-->>Disp: (Inst_2, Ep_20)
    Disp->>Inst: 推理请求

    Note over Cli,Inst: 第 2 次请求 (sticky hit)
    Cli->>Disp: POST /v1/chat/completions<br/>{tools=[T_a, T_b], messages=[..., turn2]}
    Disp->>SC: select_instance_and_endpoint
    SC->>FCA: select_endpoint_from_list
    FCA->>Cache: get(fp) -> AffinityRecord(2, 20, t)
    FCA->>FCA: 验证 Inst_2 仍在候选 ✓<br/>验证 Ep_20 仍存在 ✓
    FCA-->>SC: (Inst_2, Ep_20)<br/>**未调用 KV / Conductor**
    SC-->>Disp: (Inst_2, Ep_20)
    Disp->>Inst: 推理请求<br/>（KV-cache 命中显著提升）

    Note over Cli,Inst: 第 3 次请求：Inst_2 下线 (sticky 失效)
    Cli->>Disp: POST /v1/chat/completions<br/>{tools=[T_a, T_b], ...}
    Disp->>SC: select_instance_and_endpoint
    SC->>FCA: select_endpoint_from_list<br/>(候选只剩 Inst_3)
    FCA->>Cache: get(fp) -> AffinityRecord(2, 20, t)
    FCA->>FCA: Inst_2 ∉ 候选 → sticky 失效
    FCA->>KV: select_endpoint_from_list
    KV-->>FCA: (Inst_3, Ep_30)
    FCA->>Cache: put(fp, 3, 30)<br/>覆盖旧记录
    FCA-->>SC: (Inst_3, Ep_30)
```

### 6.2 conductor 不可用时的兜底（KV 路径返回 None）

```mermaid
sequenceDiagram
    autonumber
    participant FCA as FunctionCallAffinityPolicy
    participant Cache as ToolsAffinityCache
    participant KV as KvCacheAffinityPolicy
    participant LB as LoadBalancePolicy

    FCA->>Cache: get(fp) -> None
    FCA->>KV: select_endpoint_from_list
    Note right of KV: tokenizer/conductor<br/>未配置或调用失败<br/>返回 None
    KV-->>FCA: None
    FCA->>LB: select_instance_from_list(instances)
    LB-->>FCA: Inst_1
    FCA->>LB: select_endpoint_from_instance(Inst_1)
    LB-->>FCA: Ep_10
    FCA->>Cache: put(fp, 1, 10)
    FCA-->>FCA: return (Inst_1, Ep_10)
```

### 6.3 AsyncSchedulerClient runtime 完整路径

```mermaid
sequenceDiagram
    autonumber
    participant Disp as Router
    participant SC as AsyncSchedulerClient
    participant FCA as FunctionCallAffinityPolicy
    participant LBp as LoadBalance / RR

    Disp->>SC: select_instance_and_endpoint(req_info, role)
    SC->>SC: cache_role = role or ROLE_U
    SC->>SC: cached_instances = self._cache.get_instances(cache_role)
    alt cached_instances 非空
        SC->>SC: _select_instance_and_endpoint_from_list
        alt scheduler_type == "function_call_affinity"
            alt role == ROLE_P
                SC->>FCA: select_endpoint_from_list
                alt FCA 命中
                    FCA-->>SC: (inst, ep)
                else FCA 失败
                    SC->>LBp: load_balance fallback
                    alt LB 失败
                        SC->>LBp: round_robin fallback
                    end
                end
            else role != ROLE_P (e.g. ROLE_D)
                SC->>LBp: load_balance
            end
        end
    else 缓存为空
        SC->>SC: get_available_instances(role)
        SC->>SC: 重走上面的选择流程
    end
    SC-->>Disp: (instance, endpoint) | None
```

---

## 7. 接口契约

### 7.1 配置侧

`motor/config/coordinator.py`：

```python
class SchedulerType(Enum):
    LOAD_BALANCE = "load_balance"
    ROUND_ROBIN = "round_robin"
    KV_CACHE_AFFINITY = "kv_cache_affinity"
    FUNCTION_CALL_AFFINITY = "function_call_affinity"   # ← 新增
```

启用方式：在 `user_config.json` 的 `scheduler_config` 中将 `scheduler_type` 设为 `"function_call_affinity"`，与已有 `kv_cache_affinity` 启用方式一致。

### 7.2 公共 API

`motor/coordinator/scheduler/policy/function_call_affinity.py` 暴露的入口：

| 名称 | 形式 | 用途 |
| --- | --- | --- |
| `compute_tools_fingerprint(tools)` | 模块函数 | 仅用于本策略，但导出以便测试与未来扩展（如打到 metrics） |
| `extract_tools(req_data)` | 模块函数 | 标准化 tools 提取，防御 `None` / 非 dict 输入 |
| `has_function_call_signal(req_data)` | 模块函数 | 一站式 function-call 信号探测 |
| `ToolsAffinityCache(max_size, ttl_seconds)` | 类 | 可独立用于其他策略的指纹缓存 |
| `FunctionCallAffinityPolicy.select_endpoint_from_list(instances, req_info)` | 静态方法 | runtime 路径直接调用，使用进程级缓存 |
| `FunctionCallAffinityPolicy(...).select_endpoint_from_list_with_cache(...)` | 实例方法 | 单元测试或多策略隔离场景，每个 policy 实例独占缓存 |
| `FunctionCallAffinityPolicy.reset_global_cache_for_testing()` | 静态方法 | 仅供测试 |

> 静态 + 实例两套 API 是有意设计：runtime 路径需要跨请求复用同一缓存（粘性），而单测希望每次干净起步；这两个需求由两套 API 自然承担。

### 7.3 不变量（Invariants）

| ID | 描述 |
| --- | --- |
| INV-1 | 任何路径返回的 `(instance, endpoint)` 中 `endpoint ∈ instance.get_all_endpoints()`。 |
| INV-2 | `cache.size() <= max_size` 任意时刻成立。 |
| INV-3 | 仅当本次成功选出 `(instance, endpoint)` 且 `fingerprint != None` 时才会写入缓存。 |
| INV-4 | 失败链不会引发 `Exception` 冒泡到调用方（KV 异常被 `_safe_kv_select` 捕获并打 warning）。 |

---

## 8. 并发与线程安全

### 8.1 并发读写模型

```mermaid
flowchart LR
    subgraph Workers[多个 API Server worker / asyncio 协程]
        W1[Worker 1]
        W2[Worker 2]
        Wn[Worker N]
    end
    Lock{{RLock}}
    OD[(OrderedDict)]
    W1 -->|get/put| Lock
    W2 -->|get/put| Lock
    Wn -->|get/put| Lock
    Lock --> OD
```

- **锁粒度**：单 `RLock` 包住 `OrderedDict` 操作。临界区只做 dict 索引、`move_to_end`、`popitem`、`pop`，全部为常数时间操作，不阻塞 IO。
- **可重入**：选用 `RLock` 是为兼容未来在锁内回调（虽然当前实现没有）。
- **无死锁风险**：缓存 lock 与外部锁（如 `Instance._lock`）调用顺序为单向（policy → cache），且没有从 cache 回调到 instance 的反向路径。
- **lazy 过期**：避免后台线程，过期项在 `get` 时被丢弃；最坏情形为 N 个并发 worker 同时观察到过期项，各自尝试 `pop`，但 `pop(default=None)` 保证幂等。

### 8.2 并发测试

`test_thread_safety_basic`：8 个线程 × 50 次 `put + get`，断言执行无异常且 `size <= max_size`。

---

## 9. 性能分析

### 9.1 复杂度

| 操作 | 时间 | 空间 |
| --- | --- | --- |
| `compute_tools_fingerprint(tools)` | O(\|tools\| · \|tool_dict\|)（一次 JSON 序列化 + 一次 SHA256） | 与 tools 序列化字节数线性 |
| `cache.get` | O(1)（dict 索引 + 链表移动） | — |
| `cache.put` | O(1) 摊销（最多触发一次 `popitem`） | — |
| `_try_sticky` | O(\|instances\|) 找 instance + O(\|endpoints\|) 找 endpoint | — |

### 9.2 与 KV 路径对比

KV 路径每次都会：

1. 调用 tokenizer 编码（一般是数 ms 到数十 ms 量级）；
2. 跨进程访问 conductor（HTTP 调用）；
3. 在所有 instances/endpoints 上做 `longest_matched` 比较。

Sticky 命中时，本策略**完全跳过**这两步，纯内存路径，单请求开销在百纳秒到微秒级。在 tools 稳定的 Agent 场景下命中率高，能显著降低调度延迟。

### 9.3 内存上限

`max_size · sizeof(AffinityRecord + str-fingerprint)` ≈ `1024 × (~80 + 64) B` ≈ **≈ 144 KB**，可忽略。

---

## 10. 失败与降级矩阵

| 场景 | 表现 | 兜底 |
| --- | --- | --- |
| 请求无 `tools` 也无 `tool_calls` | `has_function_call_signal == False`，无指纹 | 直接走 `KvCacheAffinity → LoadBalance → RoundRobin` |
| 有 `tool_calls` 但无 `tools` | 信号 True 但 fingerprint=None | 同上（不写缓存） |
| `tools` 含 bytes 字段 | `compute_tools_fingerprint` 返回 None | 同上 |
| conductor 调用失败抛异常 | `KvCacheAffinityPolicy.select_endpoint_from_list` 异常 | `_safe_kv_select` 捕获并 warning，进入 LoadBalance 兜底 |
| 缓存命中但 instance 下线 | sticky 失效 | KV → LB |
| 缓存命中但 endpoint 下线 | sticky 失效 | KV → LB |
| TTL 过期 | `get` 返回 None | 走 KV → LB，下次再 put 新记录 |
| 候选 instances 列表为空 | 直接 None | 上层处理 503 |

---

## 11. 兼容性与升级影响

| 维度 | 影响 |
| --- | --- |
| 线下二进制 / proto | 无（纯 Python，无新 proto）。 |
| 配置文件 | `scheduler_type` 仅新增可选值，旧值行为不变。 |
| 运维监控 | 复用现有调度日志；新策略额外打印 `function_call_affinity sticky-hit` debug 日志。 |
| 其他策略 | 零侵入：通过 factory 注册接入，未启用时整条调用链都不会被触达。 |
| 接口/客户端 | 客户端无需改动；启用方式仅修改 coordinator 侧 scheduler 配置。 |

---

## 12. 测试设计（TDD）

### 12.1 测试金字塔

```mermaid
flowchart TB
    subgraph L1[L1 - 工具函数单测]
        T1[compute_tools_fingerprint]
        T2[extract_tools]
        T3[has_function_call_signal]
    end
    subgraph L2[L2 - 缓存单测]
        T4[get/put 往返]
        T5[TTL 过期]
        T6[LRU 驱逐]
        T7[update existing]
        T8[并发安全]
        T9[clear]
    end
    subgraph L3[L3 - 策略行为]
        T10[sticky 命中]
        T11[instance 下线失效]
        T12[endpoint 下线失效]
        T13[KV 失败兜底 LB]
        T14[无信号路径]
        T15[空 instances]
        T16[静态方法共享缓存]
    end
    subgraph L4[L4 - 集成]
        T17[SchedulerType 注册]
        T18[Factory 创建]
        T19[from_string 转换]
        T20[AsyncSchedulerClient P 角色]
        T21[AsyncSchedulerClient 兜底链]
        T22[AsyncSchedulerClient D 角色走 LB]
    end
    L1 --> L2 --> L3 --> L4
```

### 12.2 用例对应表

| 测试 | 对应需求 |
| --- | --- |
| `TestComputeToolsFingerprint::*` | 设计 §4.3、INV-3 |
| `TestToolsAffinityCache::*` | 设计 §4.2、INV-2、§8 |
| `TestFunctionCallAffinityPolicy::test_sticky_routing_on_fingerprint_hit` | G1、§5.1 |
| `..._sticky_invalidated_when_instance_gone` / `..._endpoint_gone` | G2、§5.2 |
| `..._falls_back_to_load_balance_when_kv_fails` | G3、§10 |
| `..._no_signal_uses_kv_only` | §10、INV-3 |
| `..._static_helper_uses_global_cache` | §7.2 |
| `TestSchedulerTypeAndFactory::*` | §7.1、G5 |
| `TestSchedulerClientFunctionCallAffinityRouting::*` | §6.3、runtime 集成 |

### 12.3 TDD 节奏

```mermaid
gitGraph
    commit id: "tests-red(指纹/缓存)"
    commit id: "tests-red(策略链)"
    commit id: "tests-red(factory/runtime)"
    commit id: "impl-green: function_call_affinity.py"
    commit id: "impl-green: factory + SchedulerType"
    commit id: "impl-green: scheduler_client.py 接入"
    commit id: "回归: tests/coordinator/scheduler/ 87 passed"
    commit id: "回归: tests/coordinator/ 434 passed"
    commit id: "回归: tests/ 1072 passed"
```

---

## 13. 维测（DFX）能力

| 维度 | 设计 |
| --- | --- |
| 日志 | `INFO`：策略启动；`DEBUG`：sticky 命中输出 `instance_id=...,endpoint_id=...`；`WARNING`：KV 异常、各级 fallback 触发 |
| Metrics（未来） | 预留指标点位：`fc_affinity_sticky_hit_total{instance_id}`、`fc_affinity_kv_fallback_total`、`fc_affinity_lb_fallback_total` |
| 故障定位 | 复用现有 trace 头透传；在 sticky 命中时不发起 conductor 请求，conductor trace 中"消失"是符合预期的可观测信号 |

---

## 14. 风险与未来扩展

### 14.1 已识别风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 长尾 tools 多样化 → 指纹爆炸 | 缓存 churn 增加，命中率下降 | LRU 上限 + TTL；可调参 |
| 进程重启后缓存丢失 | 首次请求退化为 KV 路径 | 接受：等价于冷启动 |
| 多 Coordinator 实例 | 不同 worker 各自缓存，可能选不同实例 | 可接受（KV 路径仍会兜底）；未来可考虑用 etcd / Conductor 做共享 |
| tools 顺序变化 → 误判为不同请求 | 命中率下降但不影响正确性 | 设计上有意保留顺序敏感性（影响 chat-template 输出） |

### 14.2 未来扩展点

1. **共享指纹缓存**：通过 etcd 或 conductor 的 KV 接口对外暴露 fingerprint→instance 映射，让多 worker / 多 Coordinator 协同。
2. **自适应 TTL**：根据 instance 平均空闲时间动态调整 TTL。
3. **MetaServer 路径接入**：当 Decode 角色也需要 sticky 时，复用同一缓存（当前 D 角色走纯 LB）。
4. **混合权重**：将 fingerprint sticky 与 longest_matched 长度做加权评分，而不是当前的二元决策。

---

## 15. 相关代码文件

| 文件 | 角色 |
| --- | --- |
| `motor/coordinator/scheduler/policy/function_call_affinity.py` | 本特性核心实现 |
| `motor/coordinator/scheduler/policy/factory.py` | 工厂注册 |
| `motor/coordinator/scheduler/policy/__init__.py` | 公共导出 |
| `motor/config/coordinator.py` | `SchedulerType.FUNCTION_CALL_AFFINITY` |
| `motor/coordinator/scheduler/runtime/scheduler_client.py` | runtime 路径接入 |
| `tests/coordinator/scheduler/test_function_call_affinity.py` | 全量单元测试 |
