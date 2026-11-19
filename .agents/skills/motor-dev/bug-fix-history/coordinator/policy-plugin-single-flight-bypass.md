# [2026-11-19] 外部选点插件单飞子进程导致高并发静默旁路与性能退化

- **现象 (Symptom)**：配置 `scheduler_config.policy_plugin` 后，在单 Worker 64 并发请求下，87.5%–98.4% 的请求走 `busy` 回退到内置策略（仅打 `logger.debug` 并写入 Worker 各自 metaserver `/metrics`），且单次选点平均延迟由 ~0.06–0.21 ms 升至 ~0.65–1.60 ms（慢 ~7–8×），64 并发突发耗时升至 ~30.8–62.7 ms（慢 ~4.3–5.4×）。
- **根因 (Root cause)**：PR #1434 将四种内置策略接入 Worker 进程内 `BuiltinEndpointPolicy` 同步路径的同时，把外部插件单独做成了「每角色 1 个子进程 + 半双工 stdin/stdout JSON Lines IPC + 单飞 `asyncio.Lock`」旁路（原 `plugin_runner.py::PolicyRunner.rank`、`scheduler_client.py::_rank_external_policy`）。高并发时首个请求持有锁并 `await` 管道，后续所有并发请求立即命中 `self._lock.locked()` 静默回退内置策略，且在此之前还构造了全量 `CandidateSnapshot` 白做序列化准备，并通过异步窗口扩大了 SHM CAS 冲突率。
- **为什么会写出 (Why)**：将「插件选点可扩展性」与「POSIX 子进程强杀隔离」强绑定，误把同步 `rank()` 放入需要 `await` 和互斥锁的跨进程半双工管道，使外部插件脱离了内置策略共享的同步无锁调度热路径。
- **修复 (Fix)**：
  - 将 `PolicyRunner`（`motor/coordinator/scheduler/policy/plugin_runner.py`）与 `plugin_worker.py::load_policy` 改为 Worker 进程内加载与同步无锁执行：`start()` 通过 `asyncio.to_thread` 受 `startup_timeout_ms` 约束预加载；热路径调用 `is_available()` 预检 + `rank_sync()`；捕获 `Exception`/`SystemExit`/`RecursionError`/`MemoryError`、非法返回值及超出 `timeout_ms` 的慢调用，按分级日志打印后进入冷却并回退内置策略。
  - 在 `motor/coordinator/scheduler/runtime/builtin_endpoint_policy.py` 新增 `ExternalEndpointPolicy(BuiltinEndpointPolicy)`，与内置四种策略实现完全相同的 `EndpointPolicy` 接口；唯一差异仅在其内部 `rank()` 调用客户插件 `rank_sync()`。
  - 在 `motor/coordinator/scheduler/runtime/scheduler_client.py` 删除 `_try_rank_external_policy`/`_rank_external_policy`/`_use_plugin` 独立分支，通过 `_endpoint_policy_for_role()` 让外部插件与内置策略共用 `_select_endpoint_candidates_with_policy()` 与统一 Rust SHM CAS 循环（CAS 重试在同循环内进程内重算，超过 3 次记 `cas_retry_limit` 无缝切换内置策略）。
- **测试拦截 (Test interception)**：`tests/coordinator/scheduler/test_policy_plugin.py` 新增 `test_high_concurrency_zero_busy_bypass`（64 并发 `calls == 64`、`busy == 0`）、`test_real_cas_contention_across_concurrent_requests`（32 并发真实 CAS 竞争均衡分配且 `busy == 0`）、`test_mid_cas_retry_fallback_preserves_builtin_demand`，以及 `SystemExit`/`RecursionError`/超 `timeout_ms` 等极端异常隔离与日志测试。
- **场景 (Scenario)**：Inference Worker 启用 `scheduler_config.policy_plugin` 且存在并发推理请求时；若客户插件出现真正无限死循环或 C 扩展段错误，仍需依赖 Worker 级 `SubprocessSupervisor` 监控重启。
- **关键词 (Keywords)**：policy_plugin, single-flight, busy bypass, ExternalEndpointPolicy, PolicyRunner, rank_sync
