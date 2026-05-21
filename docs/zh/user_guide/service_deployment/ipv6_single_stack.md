# IPv6 单栈部署（Atlas 800I A3）

本章描述如何在 **Atlas 800I A3** 上以 **IPv6 单栈**模式运行 PyMotor 控制面与推理引擎。

## 适用范围

- **支持**：Controller、Coordinator、Engine Server、Node Manager 四个控制面组件之间的 HTTP/gRPC 通信走 IPv6；推理请求经 Coordinator 转发到 Engine Server / vLLM 走 IPv6。
- **不支持（本期）**：IPv4/IPv6 双栈监听；HCCL/NPU RoCE 平面的 IPv6（由 CANN/驱动决定）；vllm-ascend 进程内不支持的 IPv6 接口（属上游）。

## 协议族选择规则

PyMotor **无需新增配置项**，运行时按 host 字面量自动判别：

- host 是 IPv6 字面量（如 `::1`、`2001:db8::1`）→ socket 用 `AF_INET6`，URL 自动包成 `http://[v6]:port`；
- host 是 IPv4 字面量或域名 → 行为与原 IPv4 部署完全一致。

这一规则的实现在 [motor/common/utils/net.py](../../../../motor/common/utils/net.py)。

## 必要的部署约束

1. **K8s Service 配置**：所有暴露 PyMotor 组件的 Service 必须设置：
   ```yaml
   spec:
     ipFamilies: [IPv6]
     ipFamilyPolicy: SingleStack
   ```
2. **`POD_IP` 必须是 IPv6 字面量**：K8s downward API 在 v6 集群会自动注入 v6 的 `POD_IP`；Docker 部署需手动设置。
3. **etcd 集群必须支持 IPv6**：`etcd_host` 若为域名，集群 DNS 必须返回 AAAA 记录；若为 IP，直接填 v6 字面量（不需要 `[]`，PyMotor 内部自动包裹）。
4. **TLS 证书**：若启用 mTLS，证书 SAN 必须包含 v6 IP（`IP:::1` 或 `IP:2001:db8::1`）。仓库内 [examples/features/http/enable_tls/openssl_gen_cert.sh](../../../../examples/features/http/enable_tls/openssl_gen_cert.sh) 已包含 `::1` SAN 示例。
5. **`ASCEND_MF_STORE_URL`（若使用 MF Store）**：使用 RFC 3986 形式 `tcp://[v6]:port`。脚本 [examples/deployer/startup/common.sh](../../../../examples/deployer/startup/common.sh) 已支持该格式。
6. **Node Manager 默认 bind**：未在配置中显式设置 `pod_ip` 时，PyMotor 会读 `POD_IP` 环境变量：若为 v6 字面量则默认 bind `::`，否则默认 `0.0.0.0`。**v6 单栈下推荐显式设置 `pod_ip`**。

## 示例配置

参见 [examples/features/ipv6_single_stack/config_sample.json](../../../../examples/features/ipv6_single_stack/config_sample.json)。
关键字段：

| 字段 | v4 默认 | v6 单栈示例 |
|------|---------|-------------|
| `motor_controller_config.api_config.controller_api_host` | `127.0.0.1` | `::1` |
| `motor_coordinator_config.api_config.coordinator_api_host` | `127.0.0.1` | `::1` |
| Node Manager `pod_ip` | downward API `POD_IP` | downward API `POD_IP`（必须是 v6） |
| `etcd_host` | `etcd.default.svc.cluster.local` | 同左，但集群 DNS 必须返回 AAAA |

## 验收清单（A3 真机 runbook）

进行下列每一项前请确认 K8s/物理机的 v6 路由可达；用 `ping6` 与 `curl -g -6 'http://[::1]:1025/'` 先做基础连通性自检。

### A1：单条推理请求成功
```bash
curl -g 'http://[<coordinator-pod-ipv6>]:1025/v1/chat/completions' \
  -H 'Content-Type: application/json' \
  -d '{"model":"<model_name>","messages":[{"role":"user","content":"hi"}]}'
```
**期望**：HTTP 200，返回合法的 `choices[0].message.content`。

### A2：PD 分离 KV 传递（大 EP 关键）
- prefill 与 decode 实例分别运行在 v6 Pod 上；
- Coordinator 日志中应出现 `metaserver=http://[v6]:port/v1/metaserver` 形式的 URL（无未包裹的 `:` 歧义）；
- KV Conductor `/register` 调用日志中 `endpoint` 字段形如 `tcp://[v6]:port`。

### A3：多实例调度
- 启动 ≥2 个 Engine Server v6 实例；
- 重复发 100 请求，统计 200 / 5xx 比例；
- **期望**：所有请求成功；`HTTPClientPool` 不应出现重复连接（pool_key 已归一化）。

### A4：健康检查 / 可观测性
```bash
curl -g 'http://[<engine-pod-ipv6>]:<mgmt_port>/health'
curl -g 'http://[<engine-pod-ipv6>]:<mgmt_port>/metrics'
curl -g 'http://[<controller-pod-ipv6>]:1027/observability/...'
```
**期望**：均返回 200 + 合法响应体。

### B1/B2/B3：各 API Server v6 bind 验证
启动后查日志，应分别看到：
- Controller: `Starting Controller API server on http://[v6]:1026`；
- Coordinator: `Created shared socket on [v6]:1025` 与 `[v6]:1026`；
- Engine Server: `InferEndpoint started: http://[v6]:port` 与 `MgmtEndpoint server started: http://[v6]:port`；
- Node Manager: `Node Manager server stated: http://[v6]:port`。

### C1：Node Manager 心跳互调
- `kubectl logs` Node Manager 应见周期性 `query_status` 调用 v6 Engine Server 成功；
- `kubectl logs` Controller 应见周期性接收来自 Node Manager 的 v6 心跳，无 4xx/5xx。

### D1：etcd v6 注册/选主
- 所有四组件启动日志无 `gRPC` 连接失败；
- `etcdctl --endpoints='[v6]:2379' get / --prefix --keys-only` 应看到 PyMotor 注册的键。

## 常见故障定位

| 现象 | 排查点 |
|------|--------|
| `Failed to bind socket on [::]:1025` | OS 内核未开启 v6 (`sysctl net.ipv6.conf.all.disable_ipv6=0`)，或 Pod 缺少 v6 地址 |
| `gRPC Connection refused` 到 etcd | 检查 etcd Service 的 `ipFamilies` 与 `ipFamilyPolicy`，以及集群 CoreDNS 是否返回 AAAA |
| HTTP 客户端连 `http://::1:1025` 失败 | 检查 SafeHTTPSClient 接收的 `address` 是否经过规范化；预期日志 `base_url=http://[::1]:1025` |
| Node Manager 心跳超时 | 检查 `format_address(item.ip, item.mgmt_port)` 是否产生 `[v6]:port`；检查 K8s NetworkPolicy 是否放通 v6 |
| MF Store URL `format invalid` | 必须使用 `tcp://[v6]:port` 形式，不能写 `tcp://v6:port` |

## 相关代码改造点

| 改造点 | 文件 |
|--------|------|
| 地址工具 | [motor/common/utils/net.py](../../../../motor/common/utils/net.py) |
| HTTP 客户端规范化 | [motor/common/http/http_client.py](../../../../motor/common/http/http_client.py) |
| 共享 socket 族选择 | [motor/coordinator/process/inference_manager.py](../../../../motor/coordinator/process/inference_manager.py) |
| etcd gRPC target | [motor/common/etcd/etcd_client.py](../../../../motor/common/etcd/etcd_client.py) |
| KV Conductor 注册 | [motor/coordinator/api_client/conductor_api_client.py](../../../../motor/coordinator/api_client/conductor_api_client.py) |
| Node Manager 默认 bind | [motor/node_manager/api_server/node_manager_api.py](../../../../motor/node_manager/api_server/node_manager_api.py) |
| 部署脚本 MF Store 解析 | [examples/deployer/startup/common.sh](../../../../examples/deployer/startup/common.sh) |
