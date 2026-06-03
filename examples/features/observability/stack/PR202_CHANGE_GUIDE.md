> **联调修复 Checklist**：见 [PR202_LAUNCH_FIX_CHECKLIST.md](PR202_LAUNCH_FIX_CHECKLIST.md)。

# PR202 可观测性栈 · 合入指导

本文档说明 PR202（MR !202）可观测性一键栈的合入范围、评审要点与验收步骤。日常使用说明见 [README.md](README.md)。

---

## 1. 合入范围

PR202 在 `examples/features/observability/stack/` 提供：

- 一键发现（`scripts/discover-targets.py`）+ 启动（`launch.sh` / `start.sh`）
- Docker Compose 栈：Prometheus、Grafana、Tempo、OTel Collector
- 三个 Grafana 看板：指标总览、KV 缓存、引擎性能剖析
- Controller metrics 经主机 `controller-proxy` 与 Coordinator PodIP 端口转发接入

**联调修复**（见 Checklist）解决代理环境下 kubectl / compose build / Grafana 数据源 / vllm Pod 发现四类问题。

---

## 2. 关键文件

| 路径 | 职责 |
|------|------|
| `launch.sh` | 用户入口：发现 → 生成配置 → 启动 |
| `scripts/discover-targets.py` | K8s 发现、Prometheus 配置、`discovered.env` |
| `start.sh` | Compose 启动、`ensure_compose_images`、端口转发脚本 |
| `docker-compose.yml` | 服务定义；Grafana 使用上游镜像且禁用容器内代理 |
| `scripts/run-k8s-port-forwards-host.sh` | 主机侧 PodIP → localhost 转发 |
| `scripts/run-controller-proxy-host.sh` | Controller `/observability/metrics` 代理 |

---

## 3. 评审 Checklist

- [ ] 显式 `MOTOR_NAMESPACE` 时，kubectl 不可达应报错而非静默 fallback
- [ ] `vllm-p0` / `vllm-d0` 等 Pod 能被识别为 engine target
- [ ] Docker runtime 下 Coordinator / Engine PodIP 生成 `PORT_FORWARD_*` 与 `host.docker.internal` target
- [ ] `docker compose up` 默认 `--pull missing`（本地有镜像不拉）、不 build Grafana（`OBS_COMPOSE_BUILD=1` 可显式开启）
- [ ] Grafana 容器 `HTTP_PROXY` 为空，`NO_PROXY` 含 `prometheus,tempo`
- [ ] 运行时产物（`generated/`、`.env`）未提交

---

## 4. 验收（minimal）

```bash
cd examples/features/observability/stack
MOTOR_NAMESPACE=<ns> ./launch.sh --minimal

curl -s http://localhost:9090/-/healthy
curl -s -u motor:motor http://localhost:3000/api/health
curl -s http://localhost:9090/api/v1/targets | grep -E 'motor-coordinator|motor-engine'
```

Grafana：http://localhost:3000，`source=real`，`cluster=<ns>`，曲线可见。

---

## 5. 与 GitCode MR !202 的关系

- GitHub / 本仓库 feature 分支可推送到 `pr202/observability-launch-fix` 供 GitCode 合入
- 联调细节与问题根因见 [PR202_LAUNCH_FIX_CHECKLIST.md](PR202_LAUNCH_FIX_CHECKLIST.md)

---

**文档版本**：2026-06-02
