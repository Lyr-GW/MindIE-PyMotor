# pyMotor 可观测性平台（本地一键部署）

一套对标 **NVIDIA Dynamo Observability (Local)** 的可视化栈，基于 Docker Compose 一键拉起 Prometheus + Grafana + Tempo + Loki + OpenTelemetry Collector + Exporters，并为 pyMotor 量身预置 Dashboard。

> 设计取向：**只负责"展示数据"**。不修改 pyMotor 应用代码；对应用侧尚未暴露的指标使用 `motor-metrics-mock` 按真实 schema 模拟，后续真实指标接入时 Dashboard 零修改。

---

## 1. 快速开始

```bash
cd examples/features/observability/stack
./start.sh                          # 含 mock 数据，任何节点都能跑
# 或在昇腾节点上：
./start.sh --profile mock,npu-real  # 同时启用 NPU 真实数据
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
| motor-metrics-mock | http://localhost:9105/metrics | — |
| **controller-metrics-proxy** | http://localhost:9106/metrics | — |
| npu-exporter | http://localhost:8082/metrics | — |

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
   │ Controller   │──/metrics──┘           │   - relabel source="mock"      │
   └──────┬───────┘                        └────────────┬────────────────────┘
          │ OTLP                                       │
          ▼                                            ▼
   ┌──────────────────┐                       ┌──────────────────┐
   │ OTel Collector   │──traces──▶ Tempo ────▶│                  │
   │  :4317 / :4318   │──logs────▶ Loki  ────▶│  Grafana :3000   │
   └──────────────────┘                       │  (motor/motor)   │
                                              │ Dashboards:      │
   ┌──────────────────┐                       │   motor-overview │
   │ motor-metrics-   │──scrape──▶ Prometheus │   motor-kv-cache │
   │ mock (profile:   │  (source=mock)       │   motor-npu      │
   │  mock)           │                       └──────────────────┘
   └──────────────────┘
   ┌──────────────────┐
   │ npu-exporter     │──scrape──▶ Prometheus
   │ (profile:        │  (source=real)
   │  npu-real)       │
   └──────────────────┘
```

所有 Dashboard 顶部带 `source` 变量（`All` / `real` / `mock`），切换 mock/real 视图无需修改 PromQL。

---

## 3. 目录结构

```
stack/
├── docker-compose.yml           # 编排（mock / npu-real profiles）
├── .env.example
├── start.sh / stop.sh
├── grafana/
│   ├── Dockerfile               # 预置 dashboards 的自定义镜像
│   ├── provisioning/
│   │   ├── datasources/datasources.yml
│   │   └── dashboards/dashboard-providers.yml
│   └── dashboards/
│       ├── motor-overview.json
│       ├── motor-kv-cache.json
│       └── motor-npu.json
├── prometheus/prometheus.yml
├── tempo/tempo.yaml
├── loki/loki.yaml
├── otel-collector/otel-collector.yaml
├── controller-proxy/             # Controller JSON 指标 → Prometheus 文本适配器
│   ├── Dockerfile
│   ├── main.py
│   ├── dev_stub_controller.py    # 本地离线联调用的 Controller 桩
│   └── README.md
└── mock-exporter/
    ├── Dockerfile
    ├── requirements.txt
    ├── main.py                  # 按 spec/profile 注册并刷新指标
    ├── profiles/                # default / multi_pd / dsv3_ep
    └── specs/                   # 6 个 spec：motor / vllm / http / coordinator_future / kv_future / npu
```

---

## 4. Dashboard 说明

### 4.1 pyMotor Overview (`motor-overview`)

- P/D 实例数（基于 `motor_active_*`）
- 5 分钟成功请求数
- Engine HTTP QPS by handler
- Coordinator 请求速率 by pd_role（mock 占位，应用侧补齐自动有数据）
- **TTFT / ITL / E2E Latency** P50/P95/P99（vllm + coordinator）
- Prompt / Generation token rate
- vLLM running / waiting / kv_cache usage
- 节点 CPU / 内存

### 4.2 KV Cache (`motor-kv-cache`)

- vLLM `kv_cache_usage_perc`（真实，立即可用）
- vLLM prefix cache hit rate（真实）
- `motor_kv_cache_hit_rate` / `motor_kv_*` 未来指标（mock）
- offload / onboard blocks per direction（mock）

### 4.3 Ascend NPU (`motor-npu`)

- 总 NPU 数 / 不健康数量 / 平均 AI Core 利用率 / 平均温度 / 总功耗
- 每 NPU 的：AI Core 利用率、Vector 利用率、显存使用%、功耗、温度、频率、带宽
- 标签：`pod_name` / `id` / `pcie_bus_info` 与华为 npu-exporter 1:1 对齐

---

## 5. 接入真实 pyMotor

### 5.1 接入指标

修改 [prometheus/prometheus.yml](prometheus/prometheus.yml) 中的 `motor-coordinator` / `motor-engine-prefill` / `motor-engine-decode` / `motor-controller` job 的 `targets`，替换为你的实际 `host:port`：

```yaml
- job_name: motor-coordinator
  metrics_path: /metrics
  static_configs:
    - targets:
        - "10.0.0.10:1026"     # Coordinator 管理端口
        - "10.0.0.11:1026"
      labels:
        source: real
```

热加载：`curl -X POST http://localhost:9090/-/reload`

### 5.2 接入链路追踪

在 pyMotor 的 `env.json` 中对应 service 段下，将 OTLP endpoint 指向本地 collector：

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

trace 自动入 Tempo，在 Grafana **Explore → Tempo** 中按 service 名 / span 名 / `x_request_id` 检索。

### 5.3 Mock → Real 平滑切换

| 切换内容 | 操作 |
|----------|------|
| 应用侧补齐 `motor_coordinator_*` 等指标 | 注释 prometheus.yml 中 `motor-metrics-mock` job → `curl -X POST http://localhost:9090/-/reload` |
| 切到生产 NPU 数据 | 启动时加 `--profile npu-real`，stop 后 `./start.sh --profile npu-real --no-mock` 重启 |
| 临时只看真实数据 | Dashboard 顶部把 `source` 变量切到 `real` |

### 5.4 接入 Controller 指标接口（controller-metrics-proxy）

Coordinator / Engine 的 `/metrics` 是原生 Prometheus 文本，可被 Prometheus 直接抓取；
但 **Controller** 的 `GET /observability/metrics`（默认端口 `1027`）返回的是 JSON 信封：

```json
{ "code": 200, "message": "Success", "data": "# HELP ...\n# TYPE ...\n..." }
```

Prometheus 直接抓取会报 `Invalid labels: "code":200,...` 并把 target 标记为 DOWN，
因此 **Grafana 无法直接接入 Controller 指标接口**。本栈用 `controller-metrics-proxy`
解决：它拉取 Controller 的 JSON，取出 `data` 字段，重新以原生 Prometheus 文本暴露在
`:9106/metrics`，由 Prometheus 抓取。

- 镜像 / 源码：[controller-proxy/](controller-proxy/)（仅依赖 Python 标准库）。
- `docker-compose.yml` 已内置该 service，默认随栈启动。
- `prometheus.yml` 的 `motor-controller` job 抓取的是 `controller-metrics-proxy:9106`。

接入真实 Controller：编辑 `.env`：

```bash
CONTROLLER_METRICS_URL=http://<controller-host>:1027/observability/metrics
# Controller observability 端口启用 TLS 时：
# CONTROLLER_INSECURE_SKIP_VERIFY=false   # 并在 compose 中挂载 CA_FILE/CERT_FILE/KEY_FILE
```

> 前提：Controller 侧 `motor_controller_config.observability_config.observability_enable`
> 必须为 `true`，且网络可达 `observability_api_port`（默认 1027）。

校验：

```bash
curl -s localhost:1027/observability/metrics | head -c 80          # 应为 {"code":200,...}
curl -s localhost:9106/metrics | grep motor_controller_proxy_up    # 解包后文本 + up 1
```

**没有完整集群？** 用自带的桩快速看效果：`python controller-proxy/dev_stub_controller.py`
会在 `:1027/observability/metrics` 返回与真实 Controller 一致的 JSON 信封（`data` 取自
真实样本 `tests/coordinator/core/metrics_example.txt`），proxy 默认即可抓到。详见
[controller-proxy/README.md](controller-proxy/README.md)。

---

## 6. Mock Exporter 内部机制

### 6.1 指标 schema 与真实形态一致

`mock-exporter/specs/` 下每个 YAML 描述一族指标，**指标名、标签、bucket、help 文本完全复刻 pyMotor 现有真实暴露形态**（vllm bucket 取自 `tests/coordinator/core/metrics_example.txt` 实测样本）。当前包含：

| Spec | 来源 / 对标 | 状态 |
|------|------------|------|
| `motor.yaml` | `motor/coordinator/metrics/metrics_collector.py` | 真实已存在 |
| `http.yaml` | `motor/engine_server/core/mgmt_endpoint.py` (prometheus_fastapi_instrumentator) | 真实已存在 |
| `vllm.yaml` | vLLM 引擎透传，bucket 与实测一致 | 真实已存在 |
| `coordinator_future.yaml` | 对标 `dynamo_frontend_*`（pymotor 未实现） | 占位，待补齐 |
| `kv_future.yaml` | 对标 `kvbm_*`（pymotor 未实现） | 占位，待补齐 |
| `npu.yaml` | 1:1 复刻华为 mind-cluster npu-exporter | 真实可替换 |

### 6.2 数据生成模式

| mode | 适用 | 说明 |
|------|------|------|
| `pd_active_count` / `pd_inactive_count` | Gauge | 根据 profile 的 P/D 实例数模拟（2% 概率短暂降为 N-1） |
| `gauge_sin` | Gauge | base + amp·sin(2π·t/period) + Gaussian noise，可 clamp |
| `counter_rate` | Counter | 每 tick 按 `rate_per_sec × dt × (0.8~1.2)` 增量 |
| `counter_rate_per_label` | Counter | 不同 label 值给不同 rate（如 `finished_reason: stop=0.35, length=0.13, abort=0.02`） |
| `histogram_lognormal` | Histogram | 对数正态样本，每 tick 数量按 `rate_per_sec` 取整 + 伯努利 |
| `histogram_constant` | Histogram | 恒定值（如 `request_params_n=1`） |
| `summary_uniform` | Summary | 区间均匀分布 |
| `gauge_npu_used/total_memory_mb` | Gauge | 与 hardware_type 联动（A2=64GB, A3=128GB） |
| `constant` / `info_gauge` | Info Gauge | 恒为 1.0 |

### 6.3 切换 mock profile

```bash
MOCK_PROFILE=multi_pd ./start.sh     # 4P+4D
MOCK_PROFILE=dsv3_ep ./start.sh      # DeepSeek-V3.2 EP
```

或编辑 `.env` 中的 `MOCK_PROFILE`，再 `docker compose up -d motor-metrics-mock`。

### 6.4 新增 mock 指标

在 `mock-exporter/specs/<name>.yaml` 中追加：

```yaml
- name: my_metric_name
  type: gauge|counter|histogram|summary|info_gauge
  help: ...
  labels: [foo, bar]
  buckets: [0.1, 0.5, 1.0]   # 仅 histogram
  value:
    mode: gauge_sin
    base: 50.0
    amp: 10.0
    period_sec: 60
```

然后在对应 profile 的 `specs:` 列表中加入文件名（不带 `.yaml`），重启容器。

---

## 7. 端口冲突 / 自定义

复制 `.env.example` 为 `.env` 后修改：

```bash
GRAFANA_PORT=3030
PROMETHEUS_PORT=19090
MOCK_PROFILE=multi_pd
REGISTRY_PREFIX=harbor.example.com/library/
```

---

## 8. 镜像构建（离线环境）

```bash
# 单独构建自定义镜像
docker compose build grafana motor-metrics-mock

# 推送到内网 Harbor
REGISTRY_PREFIX=harbor.example.com/library/ \
  docker compose build && \
  docker push harbor.example.com/library/pymotor/grafana:11.3.0 && \
  docker push harbor.example.com/library/pymotor/metrics-mock:latest
```

---

## 9. 与 NVIDIA Dynamo 的对标关系

| Dynamo | 本栈对应 |
|--------|----------|
| `deploy/docker-observability.yml` | `docker-compose.yml` |
| `grafana_dashboards/dynamo.json` | `motor-overview.json` |
| `grafana_dashboards/dcgm-metrics.json` | `motor-npu.json`（DCGM → npu-exporter） |
| `grafana_dashboards/kvbm.json` | `motor-kv-cache.json` |
| `dynamo_frontend_*` 指标 | `motor_coordinator_*`（mock 占位） |
| `dynamo_component_*` 指标 | pyMotor `motor_*` + vLLM 透传 |
| `kvbm_*` 指标 | `motor_kv_*`（mock 占位） |
| `dcgm_*` 指标 | `npu_chip_info_*` |
| Loki + Tempo + trace_id 跳转 | 完全对齐 |
| OTel Collector | 完全对齐 |

---

## 10. 后续工作（不在本目录范围）

> 这些是应用侧需要补齐的能力，等待独立 PR 推进。补齐后无需修改本栈即可让 Dashboard 显示真实数据：

- Coordinator 埋点 `motor_coordinator_time_to_first_token_seconds` / `motor_coordinator_inter_token_latency_seconds` 等 SLI
- 修正 [motor/coordinator/metrics/metrics_collector.py](../../motor/coordinator/metrics/metrics_collector.py) 对 histogram 的 sum/mean 聚合（破坏分位数）
- KV Pool / KV Conductor / Mooncake 暴露 `motor_kv_*` 指标
- pyMotor 各组件默认 OTLP 目标改为 Collector（当前默认 Jaeger）
- pyMotor 日志切换为 JSONL 并带 `trace_id` 字段，使 Loki ↔ Tempo 互跳无缝

---

## 11. 相关文档

- pyMotor 架构：[docs/zh/architecture.md](../../../../docs/zh/architecture.md)
- 现有 tracing 部署：[docs/zh/user_guide/tracing_deployment.md](../../../../docs/zh/user_guide/tracing_deployment.md)
- CCAE 北向：[examples/features/observability/REAME.md](../REAME.md)
- 华为 npu-exporter：<https://gitcode.com/Ascend/mind-cluster>
- NVIDIA Dynamo Observability：<https://docs.nvidia.com/dynamo/user-guides/observability-local>
