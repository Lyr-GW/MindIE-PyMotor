# 候选实例 / Endpoint 选点插件

## 范围与兼容

插件只在已确定角色的候选池内排序，决定建议的 `(instance_id, endpoint_id)`。
Router 拓扑选择、角色与引擎能力过滤、熔断、优先级准入、负载公式、CAS 提交及释放继续由 Motor 核心管理。
指定实例、精度探针和有效会话亲和 pin 优先执行，不调用插件。
未配置插件或 `name` 为空时，不启动插件进程，执行现有内置策略路径；存量配置无需修改。
Prefill 和 Decode 的内置策略仍分别由原配置决定，轮询、负载均衡、KV 亲和及动态分桶均保留。

## 配置和分发

在 `motor_coordinator_config.scheduler_config` 中增加可选字段：

```json
{
  "prefill_scheduler_type": "kv_cache_affinity",
  "decode_scheduler_type": "load_balance",
  "policy_plugin": {
    "name": "acme.weighted_load",
    "roles": ["prefill", "union"],
    "options": {"instance_weight": 0.05},
    "timeout_ms": 50,
    "startup_timeout_ms": 5000,
    "cooldown_seconds": 30
  }
}
```

| 字段 | 默认 | 含义 |
|------|------|------|
| name | 空 | Entry Point 名称，空则禁用 |
| roles | prefill/decode/union/encode | 调用插件的角色集合 |
| options | `{}` | JSON 对象，原样传给构造函数 |
| timeout_ms | 50 | 单次排序的 IPC 等待上限，整数 1–60000 毫秒 |
| startup_timeout_ms | 5000 | 插件发现、导入和构造的等待上限，整数 1–60000 毫秒 |
| cooldown_seconds | 30 | 故障后的恢复冷却期，有限数值且至少 1 秒 |

插件独立打包，通过固定 group `mindie_motor.scheduling_policies` 注册。
只加载配置指定的条目；缺失、重名、版本不兼容或初始化失败时记录告警并继续内置策略。
安装插件包、修改插件配置或切换版本后需要重启 Worker；不支持热加载。
安装环境必须与 Motor 相同，Motor 与插件版本应由部署系统共同锁定。

## 接口与上下文

公共接口位于 `motor.coordinator.scheduler.policy.api`。继承 `LoadBalancingPolicy`，
声明 `api_version = 1`，实现同步 `rank(selection) -> Sequence[RankedCandidate]`。
返回非空候选子集，按优先顺序排列，分数必须有限；Motor 使用返回顺序，不另行按分数排序。
候选必须来自本次输入，不允许重复或返回已排除的 ID。空结果也会回退。

`SelectionInput` 包含：

- `request`：请求 ID、角色字符串、模型、已知输入 token 数、最大输出 token 数、可选 user/session_id。
- `candidates`：只读候选 DTO，提供 ID、endpoint/实例 active_tokens、endpoint IP、引擎类型及可选缓存使用率。
- `excluded`：本次分配已拒绝的候选 ID。
- `attempt`：CAS 重选次数，从 0 开始。

未获得输入 token IDs 时 `prompt_tokens=0`，表示未知，不代表空请求。
user 和 session_id 来自请求元数据，不是经认证的租户身份；不能据此实施安全隔离。
本版不为插件额外查询 KV Conductor，也不提供原始请求正文、token IDs、凭据或可写 SHM 句柄。
DTO 在独立进程中重建，插件不能通过修改 DTO 改写核心状态。
endpoint IP 在容器网络中不一定是物理节点地址，不能据此宣称获得了完整硬件拓扑。

完整示例和构建安装方法见 [examples/scheduler_plugin](../../../examples/scheduler_plugin/README.md)。

## 请求路径与一致性

1. Worker 读取 SHM 负载，处理 pin，执行核心候选过滤和优先级准入。
2. 将快照序列化为 JSON，向该 Worker 的插件子进程发起排序。
3. 校验输出标识与分数，再校验候选可用性，按插件决策时的负载执行 CAS。
4. CAS Changed 时刷新状态重新调用同一插件；Blocked / SlotInvalid 时排除候选后重选。
5. 插件最多尝试 3 次 CAS 选点，然后回到内置策略自身的原有重试路径。
6. 成功后统一记账、记录选点日志和 DP 统计，结束时走原有释放路径。

插件分数仅用于选点日志，不作为记账 delta。插件成功时用核心通用 demand 公式；
不会因回退配置是轮询而提交零负载，也不使用内置动态分桶的专属账本单位。
回退后恢复对应内置策略的原有公式和行为。负载快照只代表读取时刻，CAS 是最终提交闸门。

## 超时、失败与生命周期

每个配置了插件的 Inference Worker 启动一个独立 Python 子进程，在连接阶段预加载。
Mgmt / Obs 不启动插件。使用 JSON-lines 通信，单条输入或输出最多 1 MiB，不使用 pickle。
在导入 Motor 和客户模块前将子进程 stdout 重定向到 stderr，避免日志破坏协议。

每个子进程同一时刻执行一次排序；忙时直接用内置策略，不排队。
排序异常、非法输出、空结果、超时或子进程退出时终止并回收进程，进入冷却期。
冷却期间请求直接走原角色配置的内置策略；到期后在后台尝试恢复，恢复过程中也用内置策略。
配置错误导致的加载失败采用相同回退方式。Worker 正常退出时取消后台恢复任务并回收子进程。
请求取消时丢弃并终止在途插件进程，取消信号继续传播，不消耗下一请求的协议响应。

一次调度最多等待 3 次排序预算；进程回收和核心工作仍有执行开销，不构成端到端时延硬上限。
默认策略也无可用后端时仍会失败；插件故障回退保证的是不因插件故障额外拒绝原本可调度的请求。
忙时回退会降低插件参与比例，应结合调用量、回退率及选点时延评估吞吐。
插件以 Worker 相同系统权限运行，进程隔离提供故障回收能力，不提供安全沙箱。

## 日志与指标

加载成功、加载失败、异常、超时及 CAS 重选回退有日志；`scheduled` 的策略名为 `plugin:<name>`。
每个 Worker metaserver 的 `GET /metrics` 暴露进程内样本，标签为配置中的 `policy` 名称：

- `motor_policy_loads_total` / `motor_policy_load_errors_total`
- `motor_policy_calls_total` / `motor_policy_errors_total` / `motor_policy_timeouts_total`
- `motor_policy_fallbacks_total`
- `motor_policy_selection_seconds_sum` / `motor_policy_selection_seconds_count`

应逐个抓取 `worker_metaserver_base_port + worker_index`，Obs 不聚合这些样本。
禁用 metaserver 时不能从该端口抓取插件指标；需要指标时应启用并配置相应监控网络访问。
超时或异常首次进入冷却时告警，冷却期间以计数器反映每次回退，避免重复日志淹没。

## 验证

```bash
bash tests/run_tests.sh --serial tests/coordinator/scheduler/test_policy_plugin.py
bash tests/run_tests.sh --serial tests/coordinator/scheduler/ tests/coordinator/core/test_config.py tests/config/
```

测试覆盖真实 distribution metadata 发现、真实子进程排序、异常/阻塞/崩溃回退、冷却、取消、
配置兼容、核心 CAS 重选和 pin 优先；原生 SHM 与集群吞吐验收需具备相应运行环境。
