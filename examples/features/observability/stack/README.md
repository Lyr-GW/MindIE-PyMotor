# pyMotor 可观测性一键栈（PR202）

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
export PROXY_SH=/mnt/l00957062/proxy.sh
```

## 2. 脚本职责

- `launch.sh`：用户入口，执行目标发现 + 启动；Docker 失败自动回退 native。
- `scripts/discover-targets.py`：自动发现 Coordinator / Engine / Controller，生成：
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
  - 自动推断 `pd_role` 与 `instance_id`（`p0/p1/d0`）
  - Engine job 启用 `honor_labels: true`
- Controller：
  - 自动发现 Controller observability NodePort（默认服务端口 `1027`）
  - 写入 `CONTROLLER_METRICS_URL=http://<host>:<port>/observability/metrics`
  - Prometheus 抓取 `controller-metrics-proxy:9106`（native 下自动改写成 `localhost:9106`）
- Tracing：
  - 写入 `OBS_HOST`
  - 写入 `OTLP_HTTP_ENDPOINT=http://<obs-host>:4318/v1/traces`
  - 写入 `OTLP_GRPC_ENDPOINT=http://<obs-host>:4317`

## 4. 默认端口

| 组件 | 默认端口 | 用途 |
|------|----------|------|
| Grafana | `3000` | 浏览器访问看板 |
| Prometheus | `9090` | 指标查询与 targets |
| Tempo | `3200` | Trace 查询 API |
| OTel Collector gRPC | `4317` | OTLP gRPC 上报 |
| OTel Collector HTTP | `4318` | OTLP HTTP `/v1/traces` |
| Coordinator observability | `1027` | Coordinator typed metrics |
| Engine management metrics | `10001` | Engine `/metrics` |
| Controller metrics proxy | `9106` | Controller JSON 解包后 Prometheus 文本 |
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

建议 pyMotor 配置：

- Coordinator：`tracer_config.endpoint = http://<obs-host>:4318/v1/traces`
- Engine：`engine_config.otlp-traces-endpoint = http://<obs-host>:4318/v1/traces`
- `OTEL_SERVICE_NAME` 建议：
  - `mindie-motor-coordinator`
  - `vllm-server-p`
  - `vllm-server-d`

示例见：`config/tracing.example.json`

Grafana Explore 使用 Tempo 时，如果默认 Query type 为 TraceQL，可：

- 切换到 `Search`；或
- TraceQL 输入 `{}` 后执行搜索。

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
  --data-urlencode 'query=count(up{motor_component=~"coordinator|engine|controller"})'
curl -s http://localhost:3200/api/search?limit=5
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
