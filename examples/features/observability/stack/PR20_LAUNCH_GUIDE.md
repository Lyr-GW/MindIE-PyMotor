# PR20 可观测性栈 · 拉起指导

本文档面向 **PR #20**（`feat(observability): PR202 一键发现并拉起本地观测栈`）的联调与验收，说明前提条件、镜像与代理策略，以及 **`launch.sh` 统一入口** 与各启动模式。日常参数与端口见 [README.md](README.md)；Tempo 无数据排障见 [TRACING_TROUBLESHOOTING.md](TRACING_TROUBLESHOOTING.md)；合入范围见 [PR202_CHANGE_GUIDE.md](PR202_CHANGE_GUIDE.md)；联调问题根因见 [PR202_LAUNCH_FIX_CHECKLIST.md](PR202_LAUNCH_FIX_CHECKLIST.md)。

---

## 1. 本 PR 拉起能力概览

PR20 在 `examples/features/observability/stack/` 提供：

| 能力 | 说明 |
|------|------|
| 一键发现 | `scripts/discover-targets.py` 根据 K8s / `user_config.json` 生成 `generated/prometheus.yml`、`generated/discovered.env` |
| 统一入口 | **`./launch.sh`**：发现 → Docker Compose 启动；失败时自动回退 **native** |
| 主机转发 | Docker 场景下 PodIP 经 `tcp-forward.py` / `run-k8s-port-forwards-host.sh` 桥接到 `host.docker.internal` |
| 栈模式 | **minimal**（Prometheus / Grafana / Tempo / OTel）与 **full**（另含 Loki、node-exporter、cAdvisor 等） |
| 兼容入口 | `start-real.sh` 仅转发到 `launch.sh`，旧脚本调用方式可保留 |

**已移除**：Controller metrics proxy（`controller-proxy`、9106 等）不再参与发现与 Prometheus job。

---

## 2. 前提条件

### 2.1 运行环境

| 项 | 要求 |
|----|------|
| 工作目录 | 在仓库内进入 `examples/features/observability/stack` |
| Python | `python3`（运行 `discover-targets.py`） |
| Kubernetes | 能访问目标集群 API；`kubectl get pods -n <namespace>` 正常 |
| Docker（推荐） | Docker Compose **v2**（`docker compose`）；无 Docker 时可 `--native` |
| 网络 | 观测机到 pyMotor Coordinator / Engine **NodePort** 或经主机转发的 PodIP 可达 |

### 2.2 业务侧就绪

- 目标 **namespace** 内 Coordinator、Engine（含 `vllm-p0` / `vllm-d0` 等命名）Pod 已 **Running**。
- 勿复用其他 namespace 的旧 `generated/discovered.env`；切换 `mindie-*` 环境时建议先 `./stop.sh` 再重新 `launch.sh`。
- 可选：准备 `user_config.json` 路径（`--user-config` / `MOTOR_USER_CONFIG`），用于从 `motor_deploy_config.job_id` 推断 namespace。

### 2.3 配置文件

```bash
cd examples/features/observability/stack
cp -n .env.example .env   # launch.sh 也会在无 .env 时自动从 .env.example 复制
```

按需编辑 `.env`：

- `REGISTRY_PREFIX`：与内网 Harbor / 镜像前缀一致（空则走 Docker Hub）。
- 各组件版本：`GRAFANA_VERSION`、`PROMETHEUS_VERSION`、`TEMPO_VERSION` 等（见 `.env.example`）。
- `OBS_STACK_MODE`：默认 `full`；也可在命令行用 `--minimal` / `--full` 覆盖。

---

## 3. 镜像拉取与网络代理（重要）

拉起过程会启动多个容器镜像。**首次本地无镜像时**，`start.sh` 默认执行：

```text
docker compose up -d --pull missing --no-build
```

含义：**本地已有镜像则不拉取；缺失时才 `docker pull`**。可通过环境变量覆盖：

| 变量 | 取值 | 含义 |
|------|------|------|
| `OBS_COMPOSE_PULL` | `missing`（默认） | 缺镜像才拉 |
| | `never` | 禁止拉取（离线 / 镜像已齐） |
| | `always` | 每次启动都尝试拉取 |
| `OBS_COMPOSE_BUILD` | `0`（默认） | 不 build Grafana |
| | `1` | 允许 `compose up --build` |

### 3.1 需要拉取的核心镜像（minimal）

| 镜像（默认 tag，见 `.env.example`） | 用途 |
|-----------------------------------|------|
| `grafana/grafana:11.3.0` | Grafana 看板 |
| `prom/prometheus:v2.55.1` | 指标存储 |
| `grafana/tempo:2.6.1` | Trace |
| `otel/opentelemetry-collector-contrib:0.115.1` | OTLP 接入 |

**full** 模式额外拉起（`--profile full`）：`grafana/loki`、`prom/node-exporter`、`gcr.io/cadvisor/cadvisor` 等；可选 `--profile npu` 使用 Ascend `npu-exporter` 镜像。

### 3.2 代理分工（必须区分阶段）

内网需 HTTP 代理才能访问外网 registry 时，**不要**让 kubectl 与容器内访问栈内服务共用同一套代理策略：

| 阶段 | 主机 `HTTP_PROXY` | 说明 |
|------|-------------------|------|
| `kubectl` / `discover-targets.py` | **建议关闭** | 脚本内 `_kubectl_env()` 会剔除代理，避免 API Server 经代理超时；也可 `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY` |
| `docker pull` / `compose pull` / `up --pull missing` | **需要时开启** | 拉镜像时 Docker 客户端继承**当前 shell** 代理 |
| Grafana / Prometheus / OTel Collector 等容器内 | **已禁用** | Compose 为 Grafana、otel-collector 清空 `HTTP_PROXY`，`NO_PROXY` 含 `prometheus,tempo,otel-collector` |

### 3.3 推荐流程（代理环境 · 首次拉起）

```bash
cd examples/features/observability/stack

# ① 需要拉镜像时：先开代理预拉（可选；也可交给 launch 的 --pull missing）
source /path/to/proxy.sh          # 或 export PROXY_SH=/path/to/proxy.sh
docker compose pull               # 仅需一次；本地已有可跳过

# ② 发现与启动：建议关闭代理，避免 kubectl 异常
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

**仅本地已有镜像、禁止任何拉取**：

```bash
export OBS_COMPOSE_PULL=never
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

---

## 4. 统一入口：`launch.sh`

**所有联调与验收请使用 `./launch.sh`**，不要直接跳过发现步骤调用 `start.sh`（除非仅调试 Compose）。

### 4.1 基本用法

```bash
cd examples/features/observability/stack

# 最常用：指定 namespace，minimal 栈（联调推荐）
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal

# 完整栈（含 Loki、node-exporter、cAdvisor 等）
MOTOR_NAMESPACE=<namespace> ./launch.sh --full

# 指定 NodePort 访问 IP（可选）
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal --node-ip <node-ip>
```

### 4.2 `launch.sh` 模式一览

| 模式 | 命令 / 参数 | 行为 |
|------|-------------|------|
| **默认 Docker · full** | `./launch.sh` 或 `./launch.sh --full` | 发现 → `start.sh --full` 启动完整 Compose profile |
| **Docker · minimal** | `./launch.sh --minimal` | 发现 → `start.sh --minimal`；生成 minimal provisioning / Prometheus / OTel；启动主机 port-forward helper |
| **仅发现** | `./launch.sh --discover-only` | 只运行 `discover-targets.py`，写出 `generated/*`，不启动栈 |
| **发现 + 预览配置** | `./launch.sh --dry-run` | 发现并打印 `generated/prometheus.yml` 前 240 行，不启动栈 |
| **强制 native** | `./launch.sh --native` | 跳过 Docker，直接 `scripts/start-native.sh`（本地下载二进制运行 Prometheus/Grafana/Tempo 等） |
| **Docker 失败回退** | `./launch.sh`（未加 `--native`） | Docker 启动非 0 退出时，**自动** fallback 到 native（日志会提示） |

命令行参数：

```text
--namespace <ns>      # 等同 MOTOR_NAMESPACE
--node-ip <ip>        # 等同 MOTOR_NODE_IP
--user-config <path>  # 等同 MOTOR_USER_CONFIG
--minimal | --full
--discover-only | --dry-run | --native
-h, --help
```

环境变量（可与参数混用，参数优先）：

```bash
export MOTOR_NAMESPACE=<namespace>
export MOTOR_NODE_IP=<node-ip>
export MOTOR_USER_CONFIG=/path/to/user_config.json
export MOTOR_ENGINE_MGMT_PORT=10001
export OBS_HOST=<obs-host>              # tracing / OTLP 上报主机
export OBS_STACK_MODE=minimal|full      # 未传 --minimal/--full 时生效
export PROXY_SH=/path/to/proxy.sh       # native 运行时下载二进制用
```

### 4.3 内部调用链（便于排障）

```text
launch.sh
  ├─ discover-targets.py  → generated/prometheus.yml, discovered.env
  ├─ [discover-only / dry-run] → 结束
  ├─ [--native] → start-native.sh
  └─ [默认] start.sh --minimal|--full
        ├─ run-k8s-port-forwards-host.sh（有 discovered.env 时）
        ├─ ensure_compose_images + compose up --pull missing
        └─ [失败] launch.sh 回退 start-native.sh
```

兼容：`./start-real.sh [options]` ≡ `./launch.sh [options]`。

### 4.4 停止栈

```bash
./stop.sh    # 停止 Docker Compose 与 native runtime、清理相关主机转发
```

---

## 5. 拉起后验收

### 5.1 健康检查

```bash
curl -s http://localhost:9090/-/healthy
curl -s -u motor:motor http://localhost:3000/api/health
curl -s http://localhost:3200/ready
curl -s http://localhost:9090/api/v1/targets
```

### 5.2 Grafana

- 地址：http://localhost:3000（默认 `motor` / `motor`）
- 变量：`source=real`，`cluster=<当前 namespace>`
- Prometheus Targets 中 `motor-coordinator`、`motor-engine` 应为 **UP**

### 5.3 发现产物（排障用）

| 文件 | 内容 |
|------|------|
| `generated/discovery-summary.txt` | 发现摘要 |
| `generated/discovered.env` | `OBS_HOST`、`PORT_FORWARD_*` 等 |
| `generated/prometheus.yml` | 自动生成的 scrape 配置 |

---

## 6. 常见问题

| 现象 | 处理建议 |
|------|----------|
| `kubectl` 超时 | 发现阶段 `unset` 代理；确认 `MOTOR_NAMESPACE` 正确 |
| `docker pull` 超时 | 拉镜像前 `source` 代理；或内网预拉后 `OBS_COMPOSE_PULL=never` |
| Grafana 看板 500/504 | Grafana 或 otel-collector 容器继承了 `HTTP_PROXY`，访问栈内服务走外网代理超时；确认 Compose 为最新，容器内 `HTTP_PROXY` 为空 |
| Tempo 无 trace / 仅 `pymotor-tracing-verify` | 栈通路正常但 pyMotor 未配置 Tracing，或 endpoint 端口与 `OTEL_HTTP_PORT` 不一致。见 [README.md §6](README.md#6-tracing-接入pymotor-侧) 与 [TRACING_TROUBLESHOOTING.md](TRACING_TROUBLESHOOTING.md) |
| `verify-tracing.sh` 失败 | 检查 `docker compose logs otel-collector` 是否有代理超时；确认 otel-collector 的 `NO_PROXY` 含 `tempo` |
| Dashboard No Data | 重新 `./launch.sh` 发现；确认 namespace / Pod IP 变化后 port-forward 已重建 |
| 无 Docker | `./launch.sh --native` |

---

## 7. 与 PR20 变更的对应关系

- **统一入口**：`launch.sh` 合入 PR20，替代分散的「先手写 prometheus 再 compose up」流程。
- **minimal / full**：对应 PR 中 `start.sh` 模式与 Compose `profile full`。
- **无 controller-proxy**：发现结果与 `prometheus.yml` 不再含 `9106` / `motor-controller` proxy job。
- **代理与 pull**：`--pull missing`、Grafana / otel-collector 容器禁代理、kubectl 清代理，见 PR 说明与 [README.md §1.1](README.md#11-代理环境与镜像拉取)。
- **Tracing**：栈内通路验证 `./scripts/verify-tracing.sh`；业务 trace 需在 pyMotor 配置 `tracer_config.endpoint` 并 `deploy.py` 重新部署，见 [README.md §6](README.md#6-tracing-接入pymotor-侧)。

---

**文档版本**：2026-06-03  
**适用 PR**：GitHub PR #20 · 分支 `cursor/add-metric-profiling-guide-a86b`
