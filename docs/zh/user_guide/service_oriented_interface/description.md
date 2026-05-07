# 说明

本文描述 **Coordinator 推理面**对外提供的 HTTP 路径及其在代码中的入口；推理端口、管理端口、TLS、API Key 与限流等横切配置见 [接口说明](../../api_reference/interface_description.md)。

## 推理应用注册的路径

`motor/coordinator/api_server/inference_server.py` 中 `InferenceServer._register_routes` 在推理用 FastAPI 应用上注册：

| 方法 | 路径 | 行为概要 |
|------|------|----------|
| `POST` | `/v1/completions` | 校验 API Key（若启用）后进入 `_handle_openai_request`，校验 OpenAI 风格 body，再调用 `motor.coordinator.router.dispatch.handle_request` |
| `POST` | `/v1/chat/completions` | 同上 |
| `GET` | `/v1/models` | 基于 `CoordinatorConfig.get_aigw_models()` 与调度器中的 P/D 可用实例数组装列表；未配置 AIGW 模型时返回 503 |

`handle_request` 根据 `CoordinatorConfig.scheduler_config.deploy_mode` 与调度器返回的实例就绪状态选择 Router（详见 [PD 分离](../../features/PD_disaggregation.md) 特性页中的 `_ROUTER_MAP` 与回退逻辑）。

## Metaserver（独立端口上的 `POST /v1/metaserver`）

在 `motor/coordinator/process/inference_manager.py` 中，当配置存在 `worker_metaserver_port` 时，会为该 Worker 额外挂载一个仅包含 **`POST /v1/metaserver`** 的 FastAPI 应用；该端点调用 `InferenceServer.handle_metaserver_request`，最终进入 `motor.coordinator.router.dispatch.handle_metaserver_request`。

`handle_metaserver_request` 的文档字符串说明：用于 **Decode 侧将 prefill 相关请求转发到 Prefill 实例**。源码中仅当 `deploy_mode` 为 `CDP_SEPARATE`、`PD_SEPARATE` 或 `PD_DISAGGREGATION_SINGLE_CONTAINER` 时继续处理，否则抛出 HTTP 500。处理逻辑委托 `SeparateCDPRouter.handle_metaserver_request`。

Decode 侧构造 Worker metaserver URL 的逻辑见 `motor/coordinator/router/strategies/cdp_separate.py` 中 `_worker_metaserver_url`（形如 `http://{host}:{worker_port}/v1/metaserver`，且依赖 `inference_workers_config` 中 `worker_metaserver_base_port` 等配置，与类内注释一致）。

## 与「面向服务」的关系

对用户暴露的入口为上述 OpenAI 兼容路径及条件启用的 metaserver；调度、转发与错误处理由 Coordinator 内 Router / Scheduler 模块完成，无需客户端感知具体 P/D Pod 地址（由服务端根据实例与端点选择）。
