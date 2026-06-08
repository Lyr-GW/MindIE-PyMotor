# Function Call 亲和性调度（特性说明）

**Function Call 亲和性调度**针对 LLM Agent / Function-Call 工作负载，通过对请求的 `tools` schema 计算稳定指纹做 sticky 路由，最大化 KV-cache 复用率，并在 conductor / tokenizer 不可用时仍然可用。

详细设计文档见 [开发者指南 - Function Call 亲和性调度详细设计](../developer_guide/function_call_affinity/function_call_affinity_design.md)。

## 调度策略枚举

`motor/config/coordinator.py` 中 `SchedulerType` 取值：

| 枚举成员 | 字符串值 |
| --- | --- |
| `LOAD_BALANCE` | `load_balance` |
| `ROUND_ROBIN` | `round_robin` |
| `KV_CACHE_AFFINITY` | `kv_cache_affinity` |
| `FUNCTION_CALL_AFFINITY` | `function_call_affinity` |

启用方式：在 coordinator 的 `scheduler_config.scheduler_type` 中配置 `function_call_affinity`，与已有 `kv_cache_affinity` 启用方式一致。

## 选择优先级

```mermaid
flowchart LR
    Req[请求] --> Sig{含 tools?}
    Sig -- 是 --> FP[计算指纹]
    Sig -- 否 --> KV[KV-Cache Affinity]
    FP --> Hit{缓存命中且<br/>实例/endpoint 仍在?}
    Hit -- 是 --> Sticky[Sticky 路由]
    Hit -- 否 --> KV
    KV -- 失败 --> LB[Load Balance]
    LB -- 失败 --> RR[Round Robin]
    Sticky --> Update[更新缓存]
    KV -- 成功 --> Update
    LB -- 成功 --> Update
```

## 与 `kv_cache_affinity` 的关系

`function_call_affinity` 是 `kv_cache_affinity` 的**严格超集**：在 KV 路径之上叠加了一层基于 tools 指纹的 sticky 缓存。当请求没有 `tools` 字段时，行为与 `kv_cache_affinity` 完全一致；当存在 `tools` 时优先尝试 sticky，失败再退化为 KV → LB → RR。

## 兼容性

- `SchedulerType` 仅新增枚举值，未启用时所有现有路径行为不变。
- 不引入对 conductor / tokenizer 的新依赖；当它们不可用时本策略仍可用。
- 客户端无需修改，启用仅修改 coordinator 侧 scheduler 配置。
