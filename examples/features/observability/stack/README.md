# pyMotor 可观测性平台（本地一键部署）

一套对标 **NVIDIA Dynamo Observability (Local)** 的可视化栈，基于 Docker Compose 一键拉起 Prometheus + Grafana + Tempo + Loki + OpenTelemetry Collector + Exporters，并为 pyMotor 预置 Dashboard。

> 设计取向：**只负责"展示数据"**。不修改 pyMotor 应用代码；指标来自真实 Coordinator / Engine / Controller 端点及可选的 npu-exporter。

---

## 1. 快速开始

```bash
cd examples/features/observability/stack
./start.sh
# 昇腾节点上额外启用 NPU exporter：
./start.sh --profile npu-real
```

启动完成后访问：

| 服务 | 地址 | 默认账号 |
|------|------|----------|
| **Grafana** | http://localhost:3000 | `motor / motor` |
| Prometheus | http://localhost:9090 | — |
| Tempo（链路） | http://localhost:3200 | — |
| Loki（日志） | http://localhost:3100 | — |
| OTel Collector | grpc :4317 / http :4318 | — |
| node-exporter | http://localhost:9100/metrics | — |
| cAdvisor | http://localhost:8088 | — |
| controller-metrics-proxy | http://localhost:9106/metrics | — |
| npu-exporter | http://localhost:8082/metrics | —（`--profile npu-real`） |

停止：

```bash
./stop.sh          # 保留数据卷
./stop.sh --purge  # 同时清理 Prometheus/Tempo/Loki 数据卷
```

---

## 2. 架构

```
       pyMotor                                    docker compose
   ┌──────────────┐
   │ EngineServer │──/metrics──┐
   ├──────────────┤            │           ┌─────────────────────────────────┐
   │ Coordinator  │──/metrics──┼──scrape──▶│ Prometheus :9090                │
   ├──────────────┤            │           │   - prometheus.yml multi-job   │
   │ Controller   │──/metrics──┘           └────────────┬────────────────────┘
   └──────┬───────┘                                     │
          │ OTLP                                         ▼
          ▼                                  ┌──────────────────┐
   ┌──────────────────┐                      │  Grafana :3000   │
   │ OTel Collector   │──traces──▶ Tempo ───▶│  Dashboards:     │
   │  :4317 / :4318   │──logs────▶ Loki  ───▶│   motor-all-     │
   └──────────────────┘                      │   metrics / ...  │
                                             └──────────────────┘
   ┌──────────────────┐
   │ npu-exporter     │──scrape──▶ Prometheus  (profile: npu-real)
   └──────────────────┘
```

---

## 3. 目录结构

```
stack/
├── docker-compose.yml
├── .env.example
├── start.sh / stop.sh
├── grafana/
│   ├── Dockerfile
│   ├── provisioning/
│   └── dashboards/
│       ├── motor-all-metrics.json
│       ├── motor-overview.json
│       ├── motor-kv-cache.json
│       ├── motor-npu.json
│       └── motor-vllm-profiling.json
├── prometheus/prometheus.yml
├── tempo/tempo.yaml
├── loki/loki.yaml
├── otel-collector/otel-collector.yaml
└── controller-proxy/
```

---

## 4. Dashboard 说明

### 4.1 pyMotor All Metrics (`motor-all-metrics`)

可视化总览看板，聚合 Coordinator / Engine 核心指标，全部以 stat / timeseries / barchart / piechart 呈现。

顶部变量：`$cluster` / `$motor_metric_scope` / `$role` / `$pd_role` / `$instance_id` / `$model_name`。

### 4.2 pyMotor Overview (`motor-overview`)

P/D 实例数、请求吞吐、TTFT / ITL / E2E 延迟、token rate、vLLM running/waiting、节点 CPU/内存。

### 4.2 KV Cache (`motor-kv-cache`)

vLLM `kv_cache_usage_perc`、prefix cache hit rate 等引擎侧真实指标。

### 4.3 Ascend NPU (`motor-npu`)

华为 npu-exporter 指标（需 `--profile npu-real`）。

### 4.4 vLLM Profiling (`motor-vllm-profiling`)

`ms_service_metric` hook 暴露的 `vllm_profiling_*` 指标。前置条件见 [5.4](#54-接入-vllm-profiling-指标)。

---

## 5. 接入 pyMotor

### 5.1 接入指标

**请勿在仓库配置中硬编码真实 IP / NodePort。** 文档示例使用 `<placeholder>`；真实环境通过本地配置文件或 `file_sd_configs` 接入。

#### Coordinator 多 scope 接口

| Scope | 路径 | `motor_metric_scope` 标签 |
|-------|------|---------------------------|
| 集群聚合 | `/metrics` | `cluster` |
| 按 instance | `/metrics?type=instance` | `instance` |
| 按 PD 角色 | `/metrics?type=role&role=prefill` / `decode` | `role` |

#### Engine 标签

`motor-engine` job 使用 `honor_labels: true`。按实际部署为每个 target 配置 `role` / `pd_role` / `instance_id`，或使用 `file_sd_configs`（见 [prometheus/prometheus.yml](prometheus/prometheus.yml) 注释）。

#### 切换 Prometheus 配置

```bash
cp .env.example .env
# 复制 prometheus.yml 为本地文件，修改 targets 后：
PROMETHEUS_CONFIG_FILE=./prometheus/prometheus.local.yml
docker compose up -d prometheus
```

热加载：`curl -X POST http://localhost:9090/-/reload`

### 5.2 接入链路追踪

在 pyMotor `env.json` 中将 OTLP endpoint 指向 collector：

```json
{
  "motor_coordinator_env": {
    "OTEL_SERVICE_NAME": "motor-coordinator",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "grpc",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://<obs-host>:4317",
    "OTEL_EXPORTER_OTLP_TRACES_INSECURE": "true"
  }
}
```

### 5.3 接入 Controller 指标（controller-metrics-proxy）

Controller 的 `/observability/metrics` 返回 JSON 信封，Prometheus 无法直接解析。本栈通过 `controller-metrics-proxy` 解包后在 `:9106/metrics` 暴露原生 Prometheus 文本。

```bash
CONTROLLER_METRICS_URL=http://<controller-host>:1027/observability/metrics
```

详见 [controller-proxy/README.md](controller-proxy/README.md)。

### 5.4 接入 vLLM profiling 指标

**前置条件：** 安装 [ms_service_metric](https://gitcode.com/Ascend/msserviceprofiler/tree/master/ms_service_metric) 并执行 `ms-service-metric on`。

- **pymotor engine_server**：`vllm_profiling_*` 通常已随 `motor-engine` job 一并采集。
- **独立 vllm serve**：启用 `vllm-profiling` job 并填写 targets。

---

## 6. 端口冲突 / 自定义

```bash
GRAFANA_PORT=3030
PROMETHEUS_PORT=19090
PROMETHEUS_CONFIG_FILE=./prometheus/prometheus.yml
REGISTRY_PREFIX=harbor.example.com/library/
```

---

## 7. 镜像构建（离线环境）

```bash
docker compose build grafana controller-metrics-proxy
```

---

## 8. 相关文档

- pyMotor 架构：[docs/zh/architecture.md](../../../../docs/zh/architecture.md)
- tracing 部署：[docs/zh/user_guide/tracing_deployment.md](../../../../docs/zh/user_guide/tracing_deployment.md)
- CCAE 北向：[examples/features/observability/REAME.md](../REAME.md)
- 华为 npu-exporter：<https://gitcode.com/Ascend/mind-cluster>
- NVIDIA Dynamo Observability：<https://docs.nvidia.com/dynamo/user-guides/observability-local>
