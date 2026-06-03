# pyMotor 可观测性一键栈（PR202）

合入与联调说明：[PR20_LAUNCH_GUIDE.md](PR20_LAUNCH_GUIDE.md)（PR #20 拉起指导）· [PR202_CHANGE_GUIDE.md](PR202_CHANGE_GUIDE.md) · [PR202_LAUNCH_FIX_CHECKLIST.md](PR202_LAUNCH_FIX_CHECKLIST.md) · [TRACING_TROUBLESHOOTING.md](TRACING_TROUBLESHOOTING.md)（Tempo 无数据排障）

目标：在已部署 pyMotor 的节点上，通过一条命令自动发现真实接口并启动观测栈，浏览器可直接查看 metrics / tracing / profiling 页面。

## 1. 推荐启动方式（唯一入口）

```bash
cd examples/features/observability/stack
MOTOR_NAMESPACE=<namespace> ./launch.sh
```

Docker 不可用或镜像拉取失败时，可显式走 native runtime：

```bash
cd examples/features/observability/stack
MOTOR_NAMESPACE=<namespace> ./launch.sh --native
```

常用参数：

```bash
./launch.sh --namespace <namespace>
./launch.sh --namespace <namespace> --node-ip <node-ip>
./launch.sh --namespace <namespace> --discover-only
./launch.sh --namespace <namespace> --dry-run
./launch.sh --namespace <namespace> --native
```

环境变量：

```bash
export MOTOR_NAMESPACE=<namespace>
export MOTOR_NODE_IP=<node-ip>
export MOTOR_USER_CONFIG=/path/user_config.json
export MOTOR_ENGINE_MGMT_PORT=10001
export OBS_HOST=<obs-host>
export PROXY_SH=/path/to/proxy.sh
```

### 1.1 代理环境与镜像拉取

`start.sh` 默认执行 `docker compose up -d --pull missing`：**本地已有镜像则不拉取，缺失时才 `docker pull`**（可用 `OBS_COMPOSE_PULL=never|always|missing` 覆盖）。

在需要 HTTP 代理才能访问外网 registry 的环境中，建议按下面分工操作（与 [PR202_LAUNCH_FIX_CHECKLIST.md](PR202_LAUNCH_FIX_CHECKLIST.md) 第五节一致）：

| 阶段 | 是否启用主机 `HTTP_PROXY` | 说明 |
|------|---------------------------|------|
| `kubectl` / `discover-targets.py` | **否** | 脚本内 `_kubectl_env()` 会去掉代理，避免 API Server 经代理超时；也可在拉起前 `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY` |
| 首次缺镜像、`docker pull` / `compose pull` | **是** | `--pull missing` 触发拉取时，Docker 客户端继承**当前 shell** 的代理；可先 `source` 代理脚本再执行 `launch.sh` 或 `docker compose pull` |
| Grafana / Prometheus / OTel Collector 等容器内 | **否** | `docker-compose.yml` 已为 Grafana、otel-collector 清空 `HTTP_PROXY` 并设置 `NO_PROXY`（含 `prometheus,tempo,otel-collector`），避免访问栈内数据源走外网代理 |

**推荐流程（代理环境、首次拉起）**

```bash
cd examples/features/observability/stack

# 1) 若本地尚无镜像：在代理下预拉（可选，也可交给 launch 时 --pull missing）
source /path/to/proxy.sh    # 或 export PROXY_SH 后由你方脚本 source
docker compose pull         # 仅需做一次；本地已有则跳过

# 2) 发现与启动：可不保留代理（发现脚本会清 kubectl 代理；保留代理时仅 pull 会走代理）
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY  # 可选
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

**仅本地已有镜像、禁止任何拉取**（离线 / 联调）：

```bash
export OBS_COMPOSE_PULL=never
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

## 2. 脚本职责

- `launch.sh`：用户入口，执行目标发现 + 启动；Docker 失败自动回退 native。
- `scripts/discover-targets.py`：自动发现 Coordinator / Engine，生成：
  - `generated/prometheus.yml`
  - `generated/discovered.env`
  - `generated/discovery-summary.txt`
- `start.sh`：Docker Compose 启动入口（被 `launch.sh` 调用）。
- `scripts/start-native.sh`：native runtime 启动入口（无 Docker 场景）。
- 兼容入口脚本：仅用于转发到 `launch.sh`。
- `stop.sh`：同时停止 Docker Compose 与 native runtime。

## 3. 自动发现规则

- Namespace：
  1) `--namespace` / `MOTOR_NAMESPACE`  
  2) `user_config.json` 的 `motor_deploy_config.job_id`  
  3) 扫描包含 Coordinator observability NodePort 的 namespace
- Node IP：
  1) `--node-ip` / `MOTOR_NODE_IP`  
  2) Coordinator Pod `hostIP`  
  3) Kubernetes Node `InternalIP`
- Coordinator：
  - 自动发现 observability NodePort（默认服务端口 `1027`）
  - 生成 `/metrics`、`/metrics?type=instance`、`/metrics?type=role&role=prefill|decode`、`/metrics?type=dp`、`/metrics?type=node`
- Engine：
  - 优先使用 Engine metrics NodePort
  - 若无 NodePort，回退 PodIP + `MOTOR_ENGINE_MGMT_PORT`（默认 `10001`）
  - 识别 `vllm-p0` / `vllm-d0` 等 Pod 命名（见 `ENGINE_POD_RE`）
  - 自动推断 `pd_role` 与 `instance_id`（`p0/p1/d0`）
  - Engine job 启用 `honor_labels: true`
- Tracing：
  - 写入 `OBS_HOST`
  - 写入 `OTLP_HTTP_ENDPOINT=http://<obs-host>:<OTEL_HTTP_PORT>/v1/traces`（端口读取 `.env`，默认 `4318`）
  - 写入 `OTLP_GRPC_ENDPOINT=http://<obs-host>:<OTEL_GRPC_PORT>`（默认 `4317`）

## 4. 默认端口

| 组件 | 默认端口 | 用途 |
|------|----------|------|
| Grafana | `3000` | 浏览器访问看板 |
| Prometheus | `9090` | 指标查询与 targets |
| Tempo | `3200` | Trace 查询 API |
| OTel Collector gRPC | `4317` | OTLP gRPC 上报 |
| OTel Collector HTTP | `4318`（`.env` 中 `OTEL_HTTP_PORT` 可改） | OTLP HTTP `/v1/traces`，pyMotor 上报须与此端口一致 |
| Coordinator observability | `1027` | Coordinator typed metrics |
| Engine management metrics | `10001` | Engine `/metrics` |
| Loki（仅 Docker） | `3100` | 日志数据源 |

## 5. Grafana 看板（仅保留 3 个）

Dashboards 根目录只保留：

- `pyMotor Metrics · 指标总览` (`motor-all-metrics.json`)
- `KV 缓存` (`motor-kv-cache.json`)
- `引擎性能剖析` (`motor-vllm-profiling.json`)

说明：

- 看板 provider 配置为平铺（`foldersFromFilesStructure: false`）。
- native runtime 启动时会写入本地 provisioning，并复制这 3 个看板。

## 6. Tracing 接入（pyMotor 侧）

> 完整排障见 [TRACING_TROUBLESHOOTING.md](TRACING_TROUBLESHOOTING.md)。

**重要**：观测栈本身（Collector → Tempo）与 pyMotor 业务 Trace 是**两个独立环节**。栈内通路修好后，`verify-tracing.sh` 能产生测试 trace；**真实推理请求**仍需在 pyMotor 侧配置 `tracer_config.endpoint` 并重新部署，否则 Coordinator 使用 `NoOpTracerProvider`，不会上报任何 span。

### 6.1 前置：确认观测栈 Tracing 通路已通

```bash
cd examples/features/observability/stack
docker compose up -d otel-collector tempo
./scripts/verify-tracing.sh
# 期望输出：OK — trace visible in Tempo (service.name=pymotor-tracing-verify)
```

若失败，先检查 OTel Collector 是否被主机 HTTP 代理污染（见 [TRACING_TROUBLESHOOTING.md §3](TRACING_TROUBLESHOOTING.md)）：

```bash
docker inspect pymotor-otel-collector --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -i proxy
# HTTP_PROXY= 应为空，NO_PROXY 含 tempo
```

### 6.2 端口说明（易错）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OTEL_HTTP_PORT` | `4318` | pyMotor **HTTP OTLP 上报端口**，在栈 `.env` 中配置 |
| `OTEL_GRPC_PORT` | `4317` | gRPC OTLP 端口（`verify-tracing.sh` 使用） |

若 `.env` 中修改了 `OTEL_HTTP_PORT`（例如 `14318`），pyMotor 的 `tracer_config.endpoint` **必须使用相同端口**，不能沿用文档默认的 `4318`。`launch.sh` 发现脚本会将 `OTLP_HTTP_ENDPOINT` 写入 `generated/discovered.env`：

```bash
grep OTLP_HTTP_ENDPOINT generated/discovered.env
```

### 6.3 pyMotor 配置（deploy 使用的 `user_config.json` / `env.json`）

将 `<obs-host>` 替换为观测栈所在主机 IP（或 `generated/discovered.env` 中的 `OBS_HOST`），`<otel-http-port>` 替换为 `.env` 中 `OTEL_HTTP_PORT`（默认 `4318`）。

**`user_config.json`：**

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

**`env.json`（Coordinator / Prefill Engine / Decode Engine 三个模块均需配置）：**

```json
{
  "OTEL_SERVICE_NAME": "mindie-motor-coordinator",
  "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf",
  "OTEL_EXPORTER_OTLP_TRACES_INSECURE": "true"
}
```

Engine 模块建议分别设置 `OTEL_SERVICE_NAME` 为 `vllm-server-p`、`vllm-server-d`。

完整片段见 `config/tracing.example.json`；上游说明见 `docs/zh/user_guide/tracing_deployment.md`。

### 6.4 重新部署（必须）

仅修改配置文件**不会生效**，须用 `deploy.py` 重启 Pod：

```bash
cd examples/deployer
python deploy.py --config_dir <你的配置目录>
```

### 6.5 部署后验证

**1）Coordinator 日志** — 确认 Tracing 已启用：

```text
TracerManager init.(enable:True,endpoint:http://<obs-host>:<otel-http-port>/v1/traces,protocol:http/protobuf)
```

若仍为 `enable:False,endpoint:`，说明 `tracer_config.endpoint` 未生效，检查 deploy 使用的配置路径是否正确。

**2）发一笔推理请求**，然后在 Grafana 查看：

- Explore → Tempo → **Search**（非 TraceQL）
- 时间范围：Last 15 minutes
- 按 `service.name = mindie-motor-coordinator`（或你设置的 `OTEL_SERVICE_NAME`）搜索

**3）Tempo API 快速检查：**

```bash
curl -sG 'http://127.0.0.1:3200/api/search' --data-urlencode 'limit=20' | grep -E 'mindie-motor-coordinator|vllm-server'
```

### 6.6 当前状态对照

| 观测栈 verify-tracing | pyMotor tracer_config | Tempo 中可见 |
|----------------------|----------------------|-------------|
| OK | 未配置 / 未 deploy | 仅 `pymotor-tracing-verify` |
| OK | 已配置且已 deploy | 业务服务名 + 测试服务 |
| FAIL | — | 先修栈内通路（代理 / Collector） |

### 6.7 注意事项

| 项 | 说明 |
|----|------|
| 端口 | 以 `.env` 的 `OTEL_HTTP_PORT` 为准，与 pyMotor endpoint 必须一致 |
| 仅改配置不 deploy | 不会生效，必须 `deploy.py` 重启 Pod |
| 采样率 | 默认 `1.0`；当前无 trace 多为 endpoint 为空（完全未上报），不是采样问题 |
| 历史请求 | 未开启 tracing 期间的请求无法补录 |

Grafana Explore 使用 Tempo 时，如果默认 Query type 为 TraceQL，可切换到 **Search**，或在 TraceQL 输入 `{}` 后执行搜索。

## 7. Profiling 接入（Grafana 路径）

PR202 中 Grafana profiling 走 `ms_service_metric` 暴露的 `vllm_profiling_*`。

Engine 启动前：

```bash
export PROMETHEUS_MULTIPROC_DIR=/dev/shm/vllm_metrics
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
```

Engine ready 后：

```bash
ms-service-metric on
ms-service-metric status
```

补充：`grafana/scripts/build-profiling-dashboard.py` 可从 Prometheus 拉取 `vllm_profiling_*` 指标族并生成单一 profiling 看板，核心面板常开、明细面板默认折叠。

## 8. 验收命令

```bash
curl -s http://localhost:9090/-/healthy
curl -s -u motor:motor http://localhost:3000/api/health
curl -s http://localhost:3200/ready
curl -s http://localhost:9090/api/v1/targets
curl -sG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=count(up{motor_component=~"coordinator|engine"})'
curl -s http://localhost:3200/api/search?limit=5
./scripts/verify-tracing.sh
# OK 表示 Collector → Tempo 通路正常；业务 trace 仍需 §6 pyMotor 配置
```

## 9. 运行产物与提交边界

运行时文件不应进入 PR：

- `.env`
- `.native-runtime/`
- `generated/prometheus.yml`
- `generated/discovered.env`
- `generated/discovery-summary.txt`
- 本地下载二进制、日志、pid、Tempo WAL、Prometheus TSDB、Grafana data

已通过 `.gitignore` 忽略上述目录与文件。
