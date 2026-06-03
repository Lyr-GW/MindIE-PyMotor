# Tempo 无 Tracing 数据 — 排障指南

本文档汇总 pyMotor 可观测性栈中 **Tracing（Tempo）无数据** 的常见根因、验证步骤与修复方法。

---

## 1. 问题现象

| 现象 | 说明 |
|------|------|
| Grafana Explore → Tempo 搜索为空 | 时间范围内无任何 trace |
| Prometheus 指标正常 | 仅 Trace 缺失，说明 metrics 通路正常 |
| `curl http://127.0.0.1:3200/api/search` 返回 `"traces":[]` | Tempo 查询 API 可达但无数据 |

---

## 2. 根因速查（按优先级）

| 优先级 | 根因 | 状态 / 处理 |
|--------|------|-------------|
| **P0** | OTel Collector 经 HTTP 代理连不上 Tempo | 已在 `docker-compose.yml` 为 `otel-collector` 清空 `HTTP_PROXY` 并设置 `NO_PROXY`（含 `tempo`） |
| **P1** | OTLP 主机端口与 pyMotor 配置不一致 | `discover-targets.py` 已读取 `.env` 的 `OTEL_HTTP_PORT` / `OTEL_GRPC_PORT`；pyMotor 端 endpoint 须与 `.env` 一致 |
| **P2** | pyMotor 未开启 Tracing | `tracer_config.endpoint` 为空时使用 `NoOpTracerProvider`，不上报 span；见 [README.md §6](README.md#6-tracing-接入pymotor-侧) |

---

## 3. P0 — OTel Collector 代理问题

### 原因

主机设置了 `HTTP_PROXY`（如 `http://90.255.216.225:3128`），Docker Compose 会把代理注入容器。若 `NO_PROXY` 未包含 `tempo`，Collector 导出到 `tempo:4317` 时会走外网代理并超时。

Grafana 容器已禁用代理，因此能查 Tempo，但里面没有数据。

### 证据

```bash
docker compose logs otel-collector | grep -i 'dial tcp.*3128\|i/o timeout'
```

### 修复（已内置）

`docker-compose.yml` 中 `otel-collector` 服务已配置：

```yaml
environment:
  HTTP_PROXY: ""
  HTTPS_PROXY: ""
  NO_PROXY: tempo,otel-collector,prometheus,...
```

### 验证

```bash
docker inspect pymotor-otel-collector --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -i proxy
# HTTP_PROXY= 应为空，NO_PROXY 含 tempo

./scripts/verify-tracing.sh
# 应看到 OK — trace visible in Tempo (service.name=pymotor-tracing-verify)
```

---

## 4. P1 — OTLP 端口不一致

### 原因

`.env` 中 `OTEL_HTTP_PORT=14318`（或其他非默认端口），但 pyMotor 的 `tracer_config.endpoint` 仍写 `:4318`，span 不会进入本栈 Collector。

### 修复

1. 确认栈侧端口：

   ```bash
   grep OTEL_HTTP_PORT .env
   # 例如 OTEL_HTTP_PORT=14318
   ```

2. 查看发现脚本生成的 endpoint：

   ```bash
   grep OTLP_HTTP_ENDPOINT generated/discovered.env
   # 应与 .env 中 OTEL_HTTP_PORT 一致
   ```

3. pyMotor 配置中使用**相同端口**（见 §5）。

---

## 5. P2 — pyMotor 未开启 Tracing（需手动配置）

### 原因

`motor_coordinator_config.tracer_config.endpoint` 为空时，Coordinator 日志会显示：

```text
TracerManager init.(enable:False,endpoint:,protocol:)
```

此时使用 `NoOpTracerProvider`，**推理请求再频繁也不会产生 trace**。

### 配置步骤

完整操作见 [README.md §6](README.md#6-tracing-接入pymotor-侧)。摘要如下。

**1）确认观测栈通路已通**

```bash
./scripts/verify-tracing.sh
```

**2）修改 deploy 使用的 `user_config.json`**

将 `<obs-host>` 替换为观测栈所在主机 IP，`<otel-http-port>` 替换为 `.env` 中 `OTEL_HTTP_PORT`（默认 `4318`）：

```json
{
  "motor_coordinator_config": {
    "tracer_config": {
      "endpoint": "http://<obs-host>:<otel-http-port>/v1/traces",
      "root_sampling_rate": 1.0,
      "remote_parent_sampled": 1.0,
      "remote_parent_not_sampled": 1.0,
      "local_parent_sampled": 1.0,
      "local_parent_not_sampled": 1.0
    }
  },
  "motor_engine_prefill_config": {
    "engine_config": {
      "otlp-traces-endpoint": "http://<obs-host>:<otel-http-port>/v1/traces"
    }
  },
  "motor_engine_decode_config": {
    "engine_config": {
      "otlp-traces-endpoint": "http://<obs-host>:<otel-http-port>/v1/traces"
    }
  }
}
```

**3）修改 `env.json`（Coordinator / Prefill / Decode 三个模块）**

```json
{
  "OTEL_SERVICE_NAME": "mindie-motor-coordinator",
  "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf",
  "OTEL_EXPORTER_OTLP_TRACES_INSECURE": "true"
}
```

Engine 模块建议分别使用 `vllm-server-p`、`vllm-server-d`。

**4）重新部署**

```bash
cd examples/deployer
python deploy.py --config_dir <你的配置目录>
```

**5）确认 Coordinator 日志**

```text
TracerManager init.(enable:True,endpoint:http://<obs-host>:<otel-http-port>/v1/traces,protocol:http/protobuf)
```

**6）Grafana 查看**

Explore → Tempo → Search，时间范围 Last 15 minutes，按 `service.name = mindie-motor-coordinator` 搜索（需有推理流量）。

---

## 6. 架构示意（修复后）

```text
pyMotor ──OTLP HTTP──► OTel Collector (:OTEL_HTTP_PORT，默认 4318)
         │              │（Docker 内网直连 tempo，不走 HTTP 代理）
         │              ▼
         │           Tempo (:3200 查询)
         │              ▼
         │           Grafana Explore
         │
verify-tracing.sh ──► OTel Collector (:OTEL_GRPC_PORT gRPC)
```

---

## 7. 常见问题 FAQ

| 问题 | 说明 |
|------|------|
| Tempo 只有 `pymotor-tracing-verify`，没有业务服务 | 栈通路正常；pyMotor 侧 Tracing 未配置或未 deploy |
| 改了配置但没有 trace | 必须 `deploy.py` 重启 Pod，仅改文件不生效 |
| 端口用 4318 还是 14318 | 以栈 `.env` 中 `OTEL_HTTP_PORT` 为准，与 pyMotor endpoint 必须一致 |
| 历史请求能补 trace 吗 | 不能；仅配置生效后的新请求会产生 trace |
| 采样率 1.0 仍无数据 | 当前多为**完全未上报**（endpoint 为空），不是采样问题 |

---

## 8. 相关文件

| 文件 | 用途 |
|------|------|
| [README.md §6](README.md#6-tracing-接入pymotor-侧) | pyMotor 开启 Tracing 完整配置步骤 |
| [PR20_LAUNCH_GUIDE.md](PR20_LAUNCH_GUIDE.md) | PR #20 拉起与代理说明 |
| [config/tracing.example.json](config/tracing.example.json) | `env.json` / `user_config.json` 配置片段 |
| [scripts/verify-tracing.sh](scripts/verify-tracing.sh) | 验证 OTLP → Tempo 通路 |
| [docs/zh/user_guide/tracing_deployment.md](../../../docs/zh/user_guide/tracing_deployment.md) | 上游 Tracing 部署文档 |
