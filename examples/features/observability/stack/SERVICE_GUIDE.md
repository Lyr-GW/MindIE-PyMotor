# pyMotor 可观测性栈 · 服务拉起与停止指导

本指导面向需要在已部署 pyMotor 的节点上拉起 / 停止可观测性栈（Prometheus + Grafana + Tempo + OTel Collector + Loki）的使用者，提供可逐步复现的完整操作步骤。

> 配套文档：Grafana 页面设计与看板指标扩展见 [GRAFANA_GUIDE.md](GRAFANA_GUIDE.md)。

整体流程：

```text
前提条件检查 → 准备镜像（联网拉取） → 拉起服务（launch.sh） → 验收 → 停止服务（stop.sh）
```

---

## 1. 前提条件

### 1.1 运行环境

| 项 | 要求 |
|----|------|
| 工作目录 | 进入仓库内 `examples/features/observability/stack` |
| Python | 已安装 `python3`（用于运行 `scripts/discover-targets.py`） |
| Kubernetes | 能访问目标集群 API，`kubectl get pods -n <namespace>` 可正常返回 |
| Docker（推荐） | 安装 Docker，且支持 Docker Compose **v2**（`docker compose version` 可用）；无 Docker 时可用 `--native` 走原生二进制 |
| 网络 | 观测机到 pyMotor Coordinator / Engine 的 **NodePort**，或经主机端口转发的 **PodIP** 可达 |

### 1.2 业务侧就绪

- 目标 **namespace** 内 Coordinator、Engine（含 `vllm-p0` / `vllm-d0` 等命名）Pod 已处于 **Running**。
- 切换 `mindie-*` 等不同环境时，先执行 `./stop.sh` 再重新 `./launch.sh`，避免复用其他 namespace 的旧 `generated/discovered.env`。
- 可选：准备 pyMotor 的 `user_config.json` 路径，用于从 `motor_deploy_config.job_id` 推断 namespace。

### 1.3 配置文件

```bash
cd examples/features/observability/stack
cp -n .env.example .env   # launch.sh 在无 .env 时也会自动从 .env.example 复制
```

按需编辑 `.env`（所有值均有默认，见 `.env.example`）：

| 变量 | 说明 |
|------|------|
| `REGISTRY_PREFIX` | 镜像前缀，与内网 Harbor 一致；留空则从 Docker Hub 拉取 |
| `GRAFANA_VERSION` / `PROMETHEUS_VERSION` / `TEMPO_VERSION` / `OTEL_COLLECTOR_VERSION` / `LOKI_VERSION` | 各组件镜像版本 |
| `OBS_STACK_MODE` | 栈模式，默认 `full`；也可在命令行用 `--minimal` / `--full` 覆盖 |
| `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` | Grafana 管理员账号 / 密码（默认 `motor` / `motor`） |
| `GRAFANA_PORT` / `PROMETHEUS_PORT` / `TEMPO_QUERY_PORT` / `OTEL_GRPC_PORT` / `OTEL_HTTP_PORT` / `LOKI_PORT` | 主机侧服务端口 |
| `MOTOR_PORT_FORWARD_BASE` | Docker 需要 PodIP 桥接转发时使用的起始主机端口（默认 `19000`） |

### 1.4 需要调整 pyMotor 配置才能生效的能力（重要，请提前配置）

部分观测能力需要在 **pyMotor 侧**（`env.json` / `user_config.json`，或引擎运行环境）提前配置，否则观测栈拉起后对应看板会无数据。请在拉起栈**之前**对照下表完成配置：

| 观测能力 | 是否需改 pyMotor 配置 | 需要的配置 |
|----------|----------------------|-----------|
| Coordinator 基础指标（指标总览 / KV 缓存的请求数、KV、吞吐、延迟等） | **否** | Coordinator 默认在管理端口暴露 `/metrics`、`/instance/metrics`，无需额外配置；只需保证该端口可被观测机或主机端口转发访问 |
| Engine / vLLM 指标 | **否**（默认开启） | Engine 在管理端口（默认 `10001`）暴露 `/metrics`；保证端口可达即可 |
| Tracing（Tempo 链路） | **是** | 见下方「1.4.1 Tracing 接入」 |
| 引擎性能剖析（`vllm_profiling_*`） | **是** | 需安装并开启 `ms_service_metric`，见下方「1.4.2 Profiling 接入」 |

> 说明：当前方案**不使用 Controller 的 metrics 接口**，因此 Controller observability 相关配置（如 `observability_enable`、`1027` 端口）无需调整，可忽略。

#### 1.4.1 Tracing 接入（让 Tempo 链路看板有数据）

需修改 deploy 使用的 `env.json` 与 `user_config.json`（`<obs-host>` 为观测栈所在主机 IP），随后用 `deploy.py` 重新部署生效：

- `env.json`：在 `motor_coordinator_env` / `motor_engine_prefill_env` / `motor_engine_decode_env` 下新增：
  - `OTEL_SERVICE_NAME`（建议 `mindie-motor-coordinator` / `vllm-server-p` / `vllm-server-d`）
  - `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf`
  - `OTEL_EXPORTER_OTLP_TRACES_INSECURE=true`
- `user_config.json`：
  - `motor_coordinator_config.tracer_config.endpoint = http://<obs-host>:4318/v1/traces`
  - `motor_engine_prefill_config.engine_config.otlp-traces-endpoint = http://<obs-host>:4318/v1/traces`
  - `motor_engine_decode_config.engine_config.otlp-traces-endpoint = http://<obs-host>:4318/v1/traces`

> `4318` 为栈内 OTel Collector 的 OTLP HTTP 端口。完整片段见 `config/tracing.example.json`，详细部署见 `docs/zh/user_guide/tracing_deployment.md`。

#### 1.4.2 Profiling 接入（让「引擎性能剖析」看板有数据）

「引擎性能剖析」看板依赖 `ms_service_metric` 暴露的 `vllm_profiling_*` 指标，需在 **Engine 侧**：

1. 安装 `ms_service_metric`（随 MindIE / 引擎环境提供）。
2. Engine 启动**前**设置多进程指标目录：

   ```bash
   export PROMETHEUS_MULTIPROC_DIR=/dev/shm/vllm_metrics
   mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
   ```

3. Engine ready **后**开启采集：

   ```bash
   ms-service-metric on
   ms-service-metric status
   ```

未执行上述步骤时，`vllm_profiling_*` 指标不会产生，「引擎性能剖析」看板将无数据。

---

## 2. 准备镜像（联网拉取）

拉起过程会启动多个容器镜像。**首次本地无镜像时**，`start.sh` 默认执行：

```text
docker compose up -d --pull missing --no-build
```

含义：**本地已有镜像则不拉取，缺失时才 `docker pull`**。可通过环境变量覆盖：

| 变量 | 取值 | 含义 |
|------|------|------|
| `OBS_COMPOSE_PULL` | `missing`（默认） | 缺镜像才拉取 |
| | `never` | 禁止拉取（离线 / 镜像已齐全） |
| | `always` | 每次启动都尝试拉取 |
| `OBS_COMPOSE_BUILD` | `0`（默认） | 不本地 build Grafana |
| | `1` | 允许 `compose up --build` |

### 2.1 需要拉取的核心镜像（minimal 模式）

| 镜像（默认 tag，见 `.env.example`） | 用途 |
|-----------------------------------|------|
| `grafana/grafana:11.3.0` | Grafana 看板 |
| `prom/prometheus:v2.55.1` | 指标存储与查询 |
| `grafana/tempo:2.6.1` | Trace 存储 |
| `otel/opentelemetry-collector-contrib:0.115.1` | OTLP 接入 |

**full** 模式额外拉起（默认 `full`，对应 Compose `--profile full`）：`grafana/loki`、`prom/node-exporter`、`gcr.io/cadvisor/cadvisor`；可选 `--profile npu` 使用 Ascend `npu-exporter` 镜像。

### 2.2 代理分工（需区分阶段）

内网需 HTTP 代理才能访问外网 registry 时，**不要**让 kubectl 发现、镜像拉取、容器内访问栈内服务共用同一套代理策略：

| 阶段 | 主机 `HTTP_PROXY` | 说明 |
|------|-------------------|------|
| `kubectl` / `discover-targets.py` | **建议关闭** | 发现脚本内 `_kubectl_env()` 会剔除代理，避免 API Server 经代理超时；也可先 `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY` |
| `docker pull` / `compose pull` / `up --pull missing` | **需要时开启** | 拉镜像时 Docker 客户端继承**当前 shell** 代理 |
| Grafana / Prometheus 等容器内 | **已禁用** | Compose 已为 Grafana 清空 `HTTP_PROXY`，`NO_PROXY` 含 `prometheus,tempo`，访问栈内数据源不走外网代理 |

### 2.3 推荐拉取流程（代理环境 · 首次拉起）

```bash
cd examples/features/observability/stack

# ① 需要拉镜像时：先开代理预拉（可选；也可交给 launch 的 --pull missing 拉取）
source /path/to/proxy.sh          # 或 export PROXY_SH=/path/to/proxy.sh
docker compose pull               # 仅需一次；本地已有镜像可跳过

# ② 发现与启动：建议关闭代理，避免 kubectl 异常
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

**仅本地已有镜像、禁止任何拉取**（离线场景）：

```bash
export OBS_COMPOSE_PULL=never
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

---

## 3. 拉起服务（`launch.sh` 统一入口）

**所有联调与验收请使用 `./launch.sh`**，它会先做目标发现，再启动栈；不要直接跳过发现步骤调用 `start.sh`（除非仅调试 Compose）。

### 3.1 基本用法

```bash
cd examples/features/observability/stack

# 最常用：指定 namespace，minimal 栈（联调推荐）
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal

# 完整栈（含 Loki、node-exporter、cAdvisor 等）
MOTOR_NAMESPACE=<namespace> ./launch.sh --full

# 指定 NodePort 访问 IP（可选）
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal --node-ip <node-ip>

# Docker 不可用 / 镜像拉取失败时，显式走 native runtime
MOTOR_NAMESPACE=<namespace> ./launch.sh --native
```

### 3.2 命令行参数说明

| 参数 | 说明 |
|------|------|
| `--namespace <ns>` | Kubernetes namespace / job_id，等同环境变量 `MOTOR_NAMESPACE` |
| `--node-ip <ip>` | NodePort 访问使用的节点 IP，等同 `MOTOR_NODE_IP` |
| `--user-config <path>` | pyMotor `user_config.json` 路径，等同 `MOTOR_USER_CONFIG` |
| `--minimal` | 启动 minimal Docker 栈（Prometheus / Grafana / Tempo / OTel） |
| `--full` | 启动 full Docker 栈（额外含 Loki / node-exporter / cAdvisor） |
| `--discover-only` | 只运行目标发现，写出 `generated/*`，不启动栈 |
| `--dry-run` | 发现并打印生成的 `generated/prometheus.yml`（前 240 行），不启动栈 |
| `--native` | 跳过 Docker Compose，直接运行原生二进制 runtime |
| `-h`, `--help` | 显示帮助 |

### 3.3 环境变量（可与参数混用，参数优先）

```bash
export MOTOR_NAMESPACE=<namespace>          # K8s namespace / job_id
export MOTOR_NODE_IP=<node-ip>              # NodePort 访问 IP
export MOTOR_USER_CONFIG=/path/user_config.json
export MOTOR_ENGINE_MGMT_PORT=10001         # Engine /metrics 管理端口，默认 10001
export OBS_HOST=<obs-host>                  # pyMotor 上报 tracing / OTLP 的观测主机
export OBS_STACK_MODE=minimal|full          # 未传 --minimal/--full 时生效
export PROXY_SH=/path/to/proxy.sh           # native runtime 下载二进制时使用
```

### 3.4 `launch.sh` 模式一览

| 模式 | 命令 / 参数 | 行为 |
|------|-------------|------|
| **默认 Docker · full** | `./launch.sh` 或 `./launch.sh --full` | 发现 → `start.sh --full` 启动完整 Compose profile |
| **Docker · minimal** | `./launch.sh --minimal` | 发现 → `start.sh --minimal`；生成 minimal provisioning / Prometheus / OTel；启动主机 port-forward helper |
| **仅发现** | `./launch.sh --discover-only` | 只运行 `discover-targets.py`，写出 `generated/*`，不启动栈 |
| **发现 + 预览配置** | `./launch.sh --dry-run` | 发现并打印 `generated/prometheus.yml`，不启动栈 |
| **强制 native** | `./launch.sh --native` | 跳过 Docker，直接 `scripts/start-native.sh`（本地下载二进制运行 Prometheus / Grafana / Tempo 等） |
| **Docker 失败回退** | `./launch.sh`（未加 `--native`） | Docker 启动非 0 退出时，**自动** fallback 到 native（日志会提示） |

### 3.5 内部调用链（便于排障）

```text
launch.sh
  ├─ discover-targets.py  → generated/prometheus.yml, generated/discovered.env
  ├─ [--discover-only / --dry-run] → 结束
  ├─ [--native] → scripts/start-native.sh
  └─ [默认] start.sh --minimal|--full
        ├─ scripts/run-k8s-port-forwards-host.sh（存在 discovered.env 时）
        ├─ ensure_compose_images + docker compose up --pull missing
        └─ [失败] launch.sh 自动回退 scripts/start-native.sh
```

兼容入口：`./start-real.sh [options]` 等价于 `./launch.sh [options]`，仅做转发。

### 3.6 自动发现规则（参考）

- **Namespace**：`--namespace` / `MOTOR_NAMESPACE` → `user_config.json` 的 `motor_deploy_config.job_id` → 扫描含 Coordinator observability NodePort 的 namespace。
- **Node IP**：`--node-ip` / `MOTOR_NODE_IP` → Coordinator Pod `hostIP` → Kubernetes Node `InternalIP`。
- **Coordinator**：自动发现 observability NodePort（默认服务端口 `1027`），生成 `/metrics` 及 `type=instance|role|dp|node` 等指标端点。
- **Engine**：优先 Engine metrics NodePort；无 NodePort 时回退 PodIP + `MOTOR_ENGINE_MGMT_PORT`（默认 `10001`），识别 `vllm-p0` / `vllm-d0` 等命名并推断 `pd_role` 与 `instance_id`。
- **Tracing**：写入 `OBS_HOST`、`OTLP_HTTP_ENDPOINT=http://<obs-host>:4318/v1/traces`、`OTLP_GRPC_ENDPOINT=http://<obs-host>:4317`。

### 3.7 默认端口

| 组件 | 默认端口 | 用途 |
|------|----------|------|
| Grafana | `3000` | 浏览器访问看板 |
| Prometheus | `9090` | 指标查询与 targets |
| Tempo | `3200` | Trace 查询 API |
| OTel Collector gRPC | `4317` | OTLP gRPC 上报 |
| OTel Collector HTTP | `4318` | OTLP HTTP `/v1/traces` |
| Loki（仅 full） | `3100` | 日志数据源 |
| Coordinator observability | `1027` | Coordinator typed metrics |
| Engine management metrics | `10001` | Engine `/metrics` |

---

## 4. 拉起后验收

### 4.1 健康检查

```bash
curl -s http://localhost:9090/-/healthy                       # Prometheus
curl -s -u motor:motor http://localhost:3000/api/health       # Grafana
curl -s http://localhost:3200/ready                           # Tempo
curl -s http://localhost:9090/api/v1/targets                  # 抓取目标
curl -sG http://localhost:9090/api/v1/query \
  --data-urlencode 'query=count(up{motor_component=~"coordinator|engine"})'
```

### 4.2 Grafana

- 访问地址：`http://localhost:3000`（默认账号 `motor` / `motor`）。
- 看板变量：`source=real`，`cluster=<当前 namespace>`。
- Prometheus Targets 中 `motor-coordinator`、`motor-engine` 应为 **UP**。
- 页面布局与看板指标扩展详见 [GRAFANA_GUIDE.md](GRAFANA_GUIDE.md)。

### 4.3 发现产物（排障用）

| 文件 | 内容 |
|------|------|
| `generated/discovery-summary.txt` | 发现摘要 |
| `generated/discovered.env` | `OBS_HOST`、`PORT_FORWARD_*` 等 |
| `generated/prometheus.yml` | 自动生成的 scrape 配置 |

---

## 5. 停止服务

```bash
cd examples/features/observability/stack

# 停止 Docker Compose 与 native runtime，并清理相关主机端口转发
./stop.sh

# 同时清空数据卷 / native 数据（彻底重置）
./stop.sh --purge
```

`stop.sh` 行为：

1. 先执行 `scripts/stop-k8s-port-forwards-host.sh` 清理主机侧 port-forward。
2. 若 `docker compose` 可用，执行 `docker compose --profile npu down`（带 `--purge` 时追加 `-v` 删除数据卷）。
3. 停止 native runtime 进程（Grafana / Prometheus / OTel / Tempo 的 pid），`--purge` 时删除 `.native-runtime/{data,logs,run}`。

---

## 6. 常见问题总结

| 现象 | 根因 / 处理建议 |
|------|----------------|
| `kubectl is unavailable` / `kubectl` 超时 | `source proxy` 后 kubectl 经 HTTP 代理访问 API Server 超时。发现阶段 `unset` 代理（脚本内已对 kubectl 清代理），并确认 `MOTOR_NAMESPACE` 正确。 |
| `docker pull` / `compose pull` 超时 | 外网 registry 需代理。拉镜像前 `source` 代理脚本；或内网预拉镜像后设 `OBS_COMPOSE_PULL=never`。 |
| `docker compose up --build` 失败 | 默认不应 build Grafana。确认未设置 `OBS_COMPOSE_BUILD=1`，使用上游 `grafana/grafana` 镜像。 |
| Grafana 看板 500 / 504 | Grafana 容器继承了 `HTTP_PROXY`，访问 `prometheus:9090` / `tempo:3200` 走外网代理超时。确认镜像与 Compose 为最新，容器内 `HTTP_PROXY` 为空（`docker exec pymotor-grafana printenv HTTP_PROXY` 应为空）。 |
| Dashboard 无曲线 / No Data | Prometheus target 指向的节点 IP 不可达，或未识别 `vllm-p0`/`vllm-d0` Pod，或 namespace / Pod IP 变化后未重建转发。重新 `./launch.sh` 发现；切换环境先 `./stop.sh`。 |
| `motor-coordinator` / `motor-engine` 为 DOWN | 观测机到 Pod 网段不通，或 NodePort 不可达。检查 `generated/discovered.env` 的 `PORT_FORWARD_*` 与主机 `tcp-forward.py` 是否生效。 |
| 无 Docker 环境 | 使用 `./launch.sh --native` 走原生二进制 runtime。 |
| 误用其他 namespace 的旧发现结果 | 切换环境时先 `./stop.sh` 再 `./launch.sh`，勿复用旧 `generated/discovered.env`。 |

---

## 7. 运行产物与提交边界

以下运行时文件不应进入版本库（已由 `.gitignore` 忽略）：

- `.env`
- `.native-runtime/`
- `generated/prometheus.yml`、`generated/discovered.env`、`generated/discovery-summary.txt`
- 本地下载的二进制、日志、pid、Tempo WAL、Prometheus TSDB、Grafana data
