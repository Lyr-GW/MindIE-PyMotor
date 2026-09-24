# 服务限流

## 特性介绍

服务限流在 Coordinator **推理面**入口限制单位时间内进入的 HTTP 请求，避免瞬时流量把调度和推理实例打满。配置位于 `user_config.json` 的 `motor_coordinator_config.rate_limit_config`，**默认关闭**。

开启后，推理进程通过中间件处理进入推理面的请求。内置 `simple` 提供者使用全局令牌桶；`olc` 提供者使用过载控制库，按 URL、Method、IP 等标签匹配规则。请求体还可以单独设上限，超限返回 HTTP `413`，且不消耗限流令牌。

该能力只挂在 Coordinator 推理面应用上，覆盖例如：

- `POST /v1/completions`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/messages`
- `POST /v1/messages/count_tokens`
- `GET /v1/models`

管理面、Controller、Node Manager 和推理引擎进程不走这套限流。

## 工作机制

### 令牌桶（provider: simple）

`simple` 使用一个全局令牌桶：

```text
桶容量     = max_requests
填充速率   = max_requests / window_size   （令牌/秒）
每个请求   = 消耗 1 个令牌
初始状态   = 满桶
```

令牌足够则放行，否则立即拒绝，不排队。`skip_paths` 中的路径按**前缀**匹配（`startswith`），命中后直接放行，不消耗令牌。

推理面可以按 `inference_workers_config.num_workers` 启动多个 Worker 进程，默认 `4`。每个进程各自持有一只令牌桶，桶之间不共享。因此单个 Coordinator 上 `simple` 限流的总通过量大约是 `max_requests × num_workers`，不是配置里的单个 `max_requests`。

`scope` 默认是 `global`。当前 `simple` 实现固定使用这一只全局桶，把 `scope` 改成其他值不会变成按 IP 或按用户限流。

限流检查失败时请求默认放行：`is_allowed` 抛错，或中间件调用限流器失败，都不会因为限流模块自身异常把推理面整段拒绝。

### 请求拥堵事件

`simple` 限流器在每次判定后，用已用额度 `used = max_requests - available`（容量减去当前剩余令牌）与 `max_requests` 的比例比较，并向 Controller 上报 `ReqCongestionEvent`：

| 条件 | 行为 |
|------|------|
| 尚未上报，且 `used >= int(max_requests × 0.85)` | 上报一次，告警状态置位 |
| 已经上报，且 `used < int(max_requests × 0.75)` | 再上报一次，并清除告警状态 |

事件固定为 `alarm_id=0xFC001005`、名称 `Coordinator Request Congestion Alarm`、级别 MAJOR、`reason_id=DEALING_WITH_CONGESTION`。触发和恢复使用同一个 `reason_id`。附加信息里的数字是已用额度。空载满桶时 `used` 很小，不会告警。状态在置位后不会重复上报，直到已用额度落到 75% 阈值之下。

### 请求体大小

`max_request_body_size` 单位是 MB（1 MB = 1024×1024 字节），允许小数，例如 `0.5`。启动校验拒绝负数。运行时 **小于等于 0 表示不限制**；大于 0 时，体大小检查发生在消耗令牌之前：

- 带有合法 `Content-Length`：按该头比较，超限直接 `413`，不预读正文。
- 没有合法 `Content-Length`（例如 chunked）：先读实际字节，超限返回 `413`；未超限则把已读正文重放给下游。

带 `Content-Length` 且超限时，响应体为：

```json
{
  "error": "request_body_too_large",
  "message": "Request body size (52428800 bytes) exceeds maximum"
}
```

无 `Content-Length` 且实际字节超限时，`message` 为 `Request body size exceeds maximum (<上限字节数> bytes)`。

### 拒绝响应与响应头

被限流拒绝的请求不会进入调度。默认 HTTP 状态码为 `error_status_code`（`429`），响应体为：

```json
{
  "error": "rate_limit_exceeded",
  "message": "too many requests, please try again later",
  "details": {
    "available": 0,
    "limit": 1000,
    "window_size": 60
  }
}
```

`simple` 在放行和拒绝的响应里都会带上：

```text
X-RateLimit-Remaining: <剩余令牌数>
X-RateLimit-Limit: <max_requests>
X-RateLimit-Window: <window_size>
```

### 过载控制（provider: olc）

`provider` 为 `olc` 且 `enable_rate_limit` 为 `true` 时，启动校验要求 `olc_config_path` 指向一个已存在的目录，目录内需有 OLC 规则文件（如 `overload-config.properties`、`olc.json`）。Coordinator 将该路径写入环境变量 `OLC_CONFIG_PATH`，并挂载 `OlcFastAPIAdapter`。标签提取器提供：

| 标签 | 来源 |
|------|------|
| URL | 请求路径 |
| Method | HTTP 方法 |
| IP | 客户端地址；取不到时为 `unknown` |

配额、并发等规则由 OLC 配置决定，见仓库示例 `examples/features/http/overload_control` 与 [OLC 文档](https://gitcode.com/openFuyao/olc-python)。

OLC 中间件创建失败时，Coordinator 记录错误日志 `Using simple rate limit, Failed to create olc limit middleware`，并回退到内置令牌桶，服务仍能启动。

### 热更新

启动时已经创建 `simple` 限流器之后（`enable_rate_limit=true` 且 `provider` 为 `simple`，或 `olc` 创建失败后已回退），热更新会立即改这些字段：

- `skip_paths`、`error_message`、`error_status_code`、`max_request_body_size`
- `enable_rate_limit`：写入运行时开关。改为 `false` 后再来的请求直接放行；改回 `true` 后继续走已有令牌桶
- `max_requests`、`window_size`：先按旧速率结算桶内令牌，再更新容量和填充速率。新容量更小则截断多余令牌；容量变大则把差额立即补进桶

热更新会拒绝非法值并保持旧参数：`max_requests` 必须 `>= 0`，`window_size` 必须 `> 0`。

以下变更不能靠热更新完成，需要重启 Coordinator：

- 启动时 `enable_rate_limit=false`，之后想补装限流中间件
- 切换 `provider`，或修改 `olc_config_path`
- 修改 `scope`（当前实现也不读取该字段做分桶）

字段清单见 [热更新配置项说明](../configuration/update_config_whitelist.md)。

## 配置说明

在 `motor_coordinator_config` 中增加 `rate_limit_config`。下面是内置令牌桶的最小配置，表示约每 60 秒 1000 个请求（平均约 16.7 QPS），**每个推理 Worker 进程各算一份**：

```json
{
  "motor_coordinator_config": {
    "rate_limit_config": {
      "enable_rate_limit": true,
      "provider": "simple",
      "max_requests": 1000,
      "window_size": 60
    }
  }
}
```

全量字段示例：

```json
{
  "motor_coordinator_config": {
    "rate_limit_config": {
      "enable_rate_limit": true,
      "provider": "simple",
      "max_requests": 1000,
      "window_size": 60,
      "scope": "global",
      "skip_paths": [
        "/liveness",
        "/readiness",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
        "/startup",
        "/v1/metaserver"
      ],
      "error_message": "too many requests, please try again later",
      "error_status_code": 429,
      "max_request_body_size": 0,
      "olc_config_path": ""
    }
  }
}
```

使用 OLC 时安装库并指向规则目录：

```bash
pip install git+https://gitcode.com/openFuyao/olc-python.git@v0.1.0
```

```json
{
  "motor_coordinator_config": {
    "rate_limit_config": {
      "enable_rate_limit": true,
      "provider": "olc",
      "olc_config_path": "examples/features/http/overload_control/config"
    }
  }
}
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| enable_rate_limit | bool | `false` | 是否在启动时安装限流中间件 |
| provider | string | `simple` | `simple` 或 `olc`。`olc` 创建失败时回退 `simple` |
| max_requests | int | `1000` | 令牌桶容量，必须为正数。仅 `simple` 使用 |
| window_size | int | `60` | 时间窗口（秒），必须为正数。填充速率 = `max_requests / window_size` |
| scope | string | `global` | 当前 `simple` 固定全局桶，改该字段不改变分桶方式 |
| skip_paths | array | 见上例 | 不参与限流的路径前缀。代码默认还包含 `/v1/metaserver` |
| error_message | string | `too many requests, please try again later` | 拒绝文案 |
| error_status_code | int | `429` | 拒绝状态码，启动校验要求 `100`–`599` |
| max_request_body_size | float | `0` | 请求体上限（MB）。`0` 不限制；负数无法通过启动校验；运行时 `<= 0` 不检查 |
| olc_config_path | string | `""` | `provider=olc` 且开启限流时必填，且必须是已存在的目录 |

字段定义同时见 [配置参数说明](../configuration/config_reference.md#motor_coordinator_config) 的 **rate_limit_config字段**。Kubernetes PD 分离部署里的最小开关见 [服务限流](../deployment/k8s/pd_disaggregation_deployment.md#服务限流)。

关闭限流：删除 `rate_limit_config`，或设 `enable_rate_limit` 为 `false` 后重启。若启动时已经装上 `simple` 中间件，也可以热更新把 `enable_rate_limit` 改为 `false`。

## 常见问题

1. 改了配置但没有生效

   启动时没有创建 `simple` 限流器（未开启，或一直使用已成功加载的 `olc`）时，热更新不会补装或切换中间件，需要重启 Coordinator。

2. 实际通过量明显高于 `max_requests`

   每个推理 Worker 进程一只令牌桶。`num_workers` 大于 1 时，总通过量约等于 `max_requests × num_workers`。

3. 配置了按 IP 或按用户的 `scope`，仍然是全局限流

   `simple` 不读取 `scope` 做分桶，始终是进程内全局令牌桶。

4. 日志出现 `Using simple rate limit, Failed to create olc limit middleware`

   OLC 未安装或规则加载失败，已回退到令牌桶。检查 `pip install git+https://gitcode.com/openFuyao/olc-python.git@v0.1.0`，以及 `olc_config_path` 目录是否存在并包含规则文件。

5. 启动报错 `olc_config_path is required` 或 `does not exist`

   `provider` 为 `olc` 且开启限流时，该路径必填且必须是已存在目录。`provider` 不是 `simple`/`olc`，或 `error_status_code` 不在 `100`–`599`，也会在启动校验失败。

6. 客户端收到 `429`，响应体 `error` 为 `rate_limit_exceeded`

   当前进程的令牌已经用完。看 `details.available` 和响应头 `X-RateLimit-*`，再调大 `max_requests` 或降低客户端速率。

7. 客户端收到 `413`，响应体 `error` 为 `request_body_too_large`

   请求体超过 `max_request_body_size`（MB）。默认 `0` 不限制。该拒绝不消耗令牌。
