# MindIE Motor 可观测性一键栈

本目录提供 Prometheus、Grafana、Tempo、OTel Collector 等组件的一键发现与拉起能力。

## 文档导航

| 文档 | 说明 |
|------|------|
| [SERVICE_GUIDE.md](SERVICE_GUIDE.md) | 前提条件、镜像准备、`launch.sh` 拉起与停止、常见问题 |
| [GRAFANA_GUIDE.md](GRAFANA_GUIDE.md) | Grafana 页面、数据源、看板设计与新增指标步骤 |

## 快速开始

```bash
cd examples/features/observability/stack
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

Grafana 默认：<http://localhost:3000>（`motor` / `motor`）。

## KV 池化后端

每套可观测栈只发现所选 namespace 中的 KV pool Service。`launch.sh --namespace <namespace>`
会在该 namespace 中查找名称为 `mindie-motor-kvs-master` 或以此前缀开头的 Service；候选必须有
ClusterIP 和唯一的 `metrics` 命名端口。恰好一个有效候选时，生成 `motor-kv-pool` scrape job，并附带
`cluster=<namespace>`、`motor_component=kv_pool` 和 `pool_service` 标签。没有候选时会告警且不生成该 job；
多个候选时发现失败，避免混合不同池。Docker 模式通过观测机本地 TCP 转发访问 Service ClusterIP，
Prometheus target 使用 `host.docker.internal`；Native 模式直接访问 Service 地址。IPv6 地址会按 Prometheus
target 格式加方括号。可用 `MOTOR_PORT_FORWARD_BASE` 更改 Docker 转发端口起点。

切换后端时重新用对应 namespace 启动栈，例如：

```bash
OBS_COMPOSE_PULL=never OBS_COMPOSE_BUILD=0 \
  bash launch.sh --namespace mindie-memcache --node-ip <node-ip> --minimal
```

切到 Mooncake 时将 namespace 改为 `mindie-mooncake`。不要在同一套配置中同时固定两个后端的 Service 地址。

MemCache 和 Mooncake 共用 Grafana 的 **Motor KV 池化后端**（UID `motor-pool-backends`）dashboard。
dashboard 按实际采集到的指标显示对应后端数据；当前未启用或未暴露该指标的后端面板会显示 `No data`。
请求速率面板使用 `rate(...[5m])`，计数器变化后请等待至少一个 scrape 周期，并确认 Grafana 时间范围覆盖请求时段。
面板按 namespace / 后端聚合，不关联压测批次或请求 ID；事件队列为零也不能单独证明发布链路正常。

重复相同前缀的请求可能由 Prefill 前缀缓存命中，因此不能仅凭业务请求成功推断 KV pool 的读取路径已验证。
验证池读路径时，应区分写入和重放阶段，并以 `memcache_get_*` 指标增量为判据。

需要产生受控流式请求时，可使用限时、限速的合成负载工具（速率最高 20 请求/秒）：

```bash
python3 scripts/simulate-business-load.py --model <model-name> --duration 60 --rate 1 --unique-prefixes
```

默认向 `http://127.0.0.1:1027/v1/chat/completions` 发送请求。可用 `--url` 指向目标 API、
`--prompt` 设置请求内容；需要认证时设置 `MOTOR_API_KEY`。对比请求前后的池计数和容量时，使用不同的
长前缀可减少 Prefill 前缀缓存命中对分配观测的影响。

## 代理 / 内网拉镜像

内网需代理访问外网时，请区分 **Docker 拉镜像**（当前 shell 的 `HTTP_PROXY`）与 **Native 下载二进制**（`.env` 中的 `PROXY_SH`）；发现阶段建议关闭代理。完整说明见 [SERVICE_GUIDE.md §2.4](SERVICE_GUIDE.md#24-代理配置)。
