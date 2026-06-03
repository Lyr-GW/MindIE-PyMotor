# PR202 可观测性栈 · 拉起与 Dashboard 修复 Checklist

基于 mindie-yangan 环境联调结论整理，用于合入 PR202（MR !202）。

- **提交**：`fix(observability): proxy-safe launch, vllm discovery, local grafana image`
- **相对基线**：`origin/merge-requests/202/head`（GitCode MR !202）

---

## 一、问题与根因

| # | 现象 | 根因 |
|---|------|------|
| P1 | `kubectl is unavailable` … mindie-yangan | `source proxy` 后 `kubectl get ns` 走 HTTP 代理访问 API Server 超时 |
| P2 | `launch.sh` / `docker compose up --build` 失败 | 强制 build `pymotor/grafana`，buildx 拉 Docker Hub 超时；本地仅有 `grafana/grafana` |
| P3 | Grafana Dashboard 变量报错 500/504 | Grafana 容器继承 `HTTP_PROXY`，访问 `prometheus:9090` / `tempo:3200` 走外网代理超时 |
| P4 | Dashboard 无曲线 | Prometheus target 指向节点 IP `90.90.97.42:1027` 不可达；未识别 `vllm-p0`/`vllm-d0` Pod；Docker 未生成 PodIP 端口转发 |

---

## 二、变更文件一览

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `scripts/discover-targets.py` | 修改 | kubectl 免代理、vllm Pod、Coordinator PodIP、Docker 端口转发、Controller URL |
| `docker-compose.yml` | 修改 | Grafana 镜像/代理、核心服务 `pull_policy` |
| `start.sh` | 修改 | 本地镜像 tag、`--pull missing --no-build`、`cp -f` |
| `PR202_LAUNCH_FIX_CHECKLIST.md` | 新增 | 本文档 |
| `PR202_CHANGE_GUIDE.md` | 修改 | 文首增加指向本 Checklist 的链接 |

---

## 三、修改项 Checklist（勾选合入）

### 3.1 `scripts/discover-targets.py`

- [x] 新增 `ENGINE_POD_RE`、`COORDINATOR_POD_KEYWORDS`、`_PROXY_ENV_KEYS`
- [x] 新增 `_kubectl_env()`、`_is_engine_pod()`、`_infer_engine_identity_from_pod()`、`_discover_coordinator_pod()`
- [x] 新增 `_register_docker_port_forward()`、`_controller_metrics_url()`
- [x] 修改 `_run_kubectl_json()`、`_is_kubectl_ready()` 使用 `_kubectl_env()`
- [x] 修改 `_discover_engine_targets_from_pods()` 使用 vllm Pod 匹配
- [x] 修改 `_apply_docker_gateway()` 为 Coordinator 增加端口转发
- [x] 修改 `_discover()` Coordinator 发现逻辑
- [x] 修改 `_build_env()` 中 `CONTROLLER_METRICS_URL` 生成方式

### 3.2 `docker-compose.yml`

- [x] `prometheus` / `tempo` / `otel-collector` 增加 `pull_policy: if_not_present`
- [x] `grafana` 删除 `build`，镜像改为 `grafana/grafana`
- [x] `grafana` 增加清空代理与 `NO_PROXY` 环境变量

### 3.3 `start.sh`

- [x] `prepare_minimal_provisioning`：`cp` → `cp -f`
- [x] 新增 `ensure_compose_images()` 与 `COMPOSE_UP_ARGS` 逻辑
- [x] `docker compose up` 默认 `--pull missing --no-build`（本地无镜像时才拉取）

### 3.4 `PR202_CHANGE_GUIDE.md`

- [x] 文首增加：`> **联调修复 Checklist**：见 [PR202_LAUNCH_FIX_CHECKLIST.md](PR202_LAUNCH_FIX_CHECKLIST.md)。`

---

## 四、发现结果示例（mindie-yangan）

```
Coordinator: host.docker.internal:19000
Engine prefill targets: 1
Engine decode targets: 1
Port forwards: 3
- mindie-yangan/mindie-motor-coordinator 192.168.222.250:1027 -> localhost:19000
- mindie-yangan/vllm-d0-58595db8bf-z8qgr 192.168.40.83:10001 -> localhost:19001
- mindie-yangan/vllm-p0-6d66bb5446-vsxwr 192.168.222.229:10001 -> localhost:19002
```

---

## 五、使用侧 Checklist

### 5.1 拉起前

- 在能访问 K8s API 的终端执行（发现阶段可 `unset` 代理，或依赖脚本内 kubectl 清代理）
- `kubectl get pods -n <namespace>` 就绪
- `.env` 中 `REGISTRY_PREFIX` 与本地镜像前缀一致
- 勿沿用其他 namespace 的旧 `generated/discovered.env`

### 5.2 一键拉起

```bash
cd examples/features/observability/stack
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY   # 可选
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

### 5.3 Grafana

- http://localhost:3000（`motor` / `motor`）
- `source = real`，`cluster = 当前 namespace`
- Prometheus Targets 中 `motor-coordinator` / `motor-engine` 为 UP

### 5.4 代理分工

| 场景 | 是否 `source proxy` |
|------|---------------------|
| `kubectl` / `discover-targets.py` | 否 |
| `docker pull` / `buildx` | 是（仅拉镜像时） |
| Grafana / Prometheus 容器内 | 否 |

---

## 六、验证命令

```bash
MOTOR_NAMESPACE=mindie-yangan python3 scripts/discover-targets.py \
  --namespace mindie-yangan --runtime docker --output-dir ./generated

docker exec pymotor-grafana printenv HTTP_PROXY

curl -s -u motor:motor \
  'http://localhost:3000/api/datasources/proxy/uid/prometheus/api/v1/query?query=up' \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('status'))"

curl -s http://localhost:9090/api/v1/targets | grep -E 'motor-coordinator|motor-engine' | head
```

---

## 七、合入 PR202 / 推送

```bash
git push -u origin HEAD:pr202/observability-launch-fix
```

在 GitCode MR !202 合入分支 `pr202/observability-launch-fix` 或 cherry-pick 本提交。

---

## 八、已知限制

- Docker 内 Prometheus 依赖主机 `tcp-forward.py`；观测机到 Pod 网段 `192.168.x.x` 不通时 target 仍为 DOWN。
- `minimal` 模式生成的 `prometheus.yml` 仍含 `node-exporter`/`cadvisor` job（无对应容器时为 DOWN）。

---

**文档版本**：2026-06-02  
**验证环境**：mindie-yangan @ node 90.90.97.42
