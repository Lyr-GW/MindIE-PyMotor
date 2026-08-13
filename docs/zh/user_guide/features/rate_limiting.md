# 服务限流特性说明

---

## 功能介绍

MindIE Motor 支持在 Coordinator 推理面（`/v1/completions`、`/v1/chat/completions`、`/v1/messages`、`/v1/messages/count_tokens`、`/v1/models` 等推理接口）上开启服务限流，通过 FastAPI 中间件对进入的请求进行拦截控制，避免瞬时流量过大导致服务过载。内置基于令牌桶（Token Bucket）算法的 `simple` 限流器实现全局限流，也可切换为三方过载控制库 [OLC](https://gitcode.com/openFuyao/olc-python) 实现按 URL、Method、IP 等标签维度的细粒度限流。

除限流外，`rate_limit_config` 还支持配置请求体大小限制（`max_request_body_size`），超限请求直接以 HTTP `413` 拒绝，可用于防范超大请求体导致的资源占用。

---

## 前置说明

- 已参考[快速开始](../quick_start_motor.md)完成一次基础服务部署，具备可正常运行的 `env.json` 和 `user_config.json` 配置文件。
- 限流能力仅对 **Coordinator 推理面 API** 生效，不作用于管理面、Controller、Engine 内部处理流程，也不影响 NodeManager。
- 限流配置属于 `motor_coordinator_config.rate_limit_config`。
- 若选择 `provider: "olc"`，需提前在镜像/环境中安装 OLC 三方库（以 OLC 库官方安装方式为准）：

  ```bash
  pip install git+https://gitcode.com/openFuyao/olc-python.git@v0.1.0
  ```

  并准备好 OLC 规则配置目录（OLC 库要求目录中包含 `overload-config.properties` 与 `olc.json` 等规则文件）。若 OLC 库未安装或规则加载失败，Coordinator 会记录错误日志并自动降级为内置的令牌桶限流，不会导致服务启动失败。
- Coordinator 推理面支持多进程推理 Worker（`inference_workers_config.num_workers`，默认 `4`），**每个 Worker 进程各自维护独立的令牌桶**，配置限流阈值时需考虑这一点（详见下文「原理说明」）。

---

## 快速实践

1. 在 `user_config.json` 的 `motor_coordinator_config` 下新增 `rate_limit_config`，修改完成后保存文件。

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

   以上配置表示：Coordinator 推理面按全局维度限流，60 秒时间窗口内最多允许 1000 次请求（等效平均 QPS ≈ 16.7），超出部分直接拒绝。

2. 按常规流程重新部署/重启 Coordinator 推理服务使配置生效（若启动时已开启 `simple` 限流，后续修改配置文件可直接依赖配置热更新机制自动生效，见「原理说明」）。

3. 发起推理请求验证限流是否生效。正常情况下响应头会携带以下限流相关信息：

   ```text
   X-RateLimit-Remaining: 999
   X-RateLimit-Limit: 1000
   X-RateLimit-Window: 60
   ```

   当短时间内请求数超过 `max_requests` 时，被拒绝的请求会收到 HTTP `429` 响应，响应体如下：

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

---

## 典型配置

### 1. 配置示例

`user_config.json` 需在 `motor_coordinator_config` 下新增 `rate_limit_config`：

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
        "/startup"
      ],
      "error_message": "too many requests, please try again later",
      "error_status_code": 429,
      "max_request_body_size": 0,
      "olc_config_path": ""
    }
  }
}
```

若选用 `provider: "olc"`，还需将 `olc_config_path` 指向规则配置目录（须为真实存在的目录）：

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

### 2. 参数说明

各项参数功能说明（加粗部分为重点关注项）。字段定义也可对照[配置参数说明](../configuration/config_reference.md#motor_coordinator_config)中的 **rate_limit_config 字段**。

| 配置项 | 取值类型 | 配置说明 |
| --- | --- | --- |
| **enable_rate_limit** | bool | 是否开启限流，默认值：`false`（关闭）。 |
| **provider** | string | 限流提供者，可选 `simple`（内置令牌桶，默认值）或 `olc`（三方过载控制库）。`olc` 加载失败时会自动降级为 `simple`。 |
| **max_requests** | int | 限流时间窗口内允许的最大请求数（即令牌桶容量），默认值：`1000`，必须为正数。仅 `provider: "simple"` 时生效。 |
| **window_size** | int | 限流统计的时间窗口长度，单位秒，默认值：`60`，必须为正数。令牌填充速率 = `max_requests / window_size`。仅 `provider: "simple"` 时生效。 |
| scope | string | 限流生效范围，默认值：`"global"`。当前 `simple` 实现固定使用全局令牌桶，该字段暂不区分 `per_ip`/`per_user`。 |
| skip_paths | array | 不参与限流统计的路径**前缀**列表（匹配命中即跳过），默认包含 `/liveness`、`/readiness`、`/metrics`、`/docs`、`/redoc`、`/openapi.json`、`/favicon.ico`、`/startup` 等健康检查与文档类接口，可自定义追加。 |
| error_message | string | 触发限流时返回给客户端的提示文案，默认值：`"too many requests, please try again later"`。 |
| error_status_code | int | 触发限流时返回的 HTTP 状态码，取值范围 `100`-`599`，默认值：`429`。 |
| max_request_body_size | float | 请求体大小上限，单位 MB（1 MB = 1024×1024 字节），支持小数（如 `0.5` 表示 0.5 MB），默认值：`0`，即不限制。配置为负数会触发部署校验报错。 |
| olc_config_path | string | `provider: "olc"` 时的规则配置目录路径（绝对路径或相对路径）。`provider` 为 `olc` 且开启限流时必填，且目录必须真实存在，否则部署校验会报错。 |

---

## 原理说明

### 内容一：令牌桶限流（provider: simple）

`simple` 限流基于经典的**令牌桶算法**实现：桶容量为 `max_requests`，按 `max_requests / window_size`（令牌/秒）的速率持续填充，每个 HTTP 请求到达时尝试消耗 1 个令牌，桶内令牌充足则放行，否则直接拒绝，**不会排队等待**。令牌桶初始为满桶状态。该限流器为**全局单桶**，所有客户端、所有路径（`skip_paths` 列表除外）共享同一个令牌桶。

需要特别注意：Coordinator 推理面支持以 `inference_workers_config.num_workers`（默认 `4`）启动多个推理 Worker 进程，每个 Worker 进程独立运行推理服务并各自持有独立的令牌桶，互不共享状态。因此集群实际可承受的总吞吐上限约为 `max_requests × num_workers`，而非单一的 `max_requests`，配置阈值时应结合部署的 Worker 进程数一并考虑。

限流器内置请求拥堵告警，判定依据为限流检查时返回的 `available`（当前剩余令牌数）字段，并与 `max_requests` 的比例阈值比较：

- 当 `available ≥ int(max_requests × 85%)` 时，上报一次拥堵告警事件（`ReqCongestionEvent`，`alarm_id=0xFC001005`，名称 `Coordinator Request Congestion Alarm`，级别 MAJOR，`reason_id=DEALING_WITH_CONGESTION`），告警通过 Controller 接口上报；
- 当 `available < int(max_requests × 75%)` 时，上报一次恢复事件并复位告警状态。

告警状态在单次限流器生命周期内仅记录一次（触发后不会重复上报，需回落到恢复阈值下方后才可再次触发）。

限流检查逻辑内置了失败兜底（fail-open）：若限流器本身发生异常（`is_allowed` 抛错或中间件处理异常），请求会被默认放行，不会因限流模块故障导致服务整体不可用。

### 内容二：过载控制（provider: olc）

`olc` 通过外部库 [OLC](https://gitcode.com/openFuyao/olc-python) 提供更丰富的限流能力。启动时 Coordinator 会将 `olc_config_path` 写入 `OLC_CONFIG_PATH` 环境变量，并从 `olc.adapters.fastapi` 加载 `OlcFastAPIAdapter` 作为 FastAPI 中间件；请求标签提取器会从每个请求中提取 `URL`（请求路径）、`Method`（请求方法）、`IP`（客户端 IP）三个维度，OLC 依据这些标签在 `olc_config_path` 指向目录下的规则文件（如 `overload-config.properties`、`olc.json`）中定义的规则进行分组限流（配额/并发等模式由 OLC 库决定，具体配置方式请参考 OLC 库文档）。

当以 `provider: "olc"` 启动失败（如未安装 OLC 库、规则目录缺失或加载异常）时，Coordinator 会记录错误日志（`Using simple rate limit, Failed to create olc limit middleware`）并自动回退为内置的 `simple` 令牌桶限流，保证服务仍可正常提供限流保护。

### 内容三：请求体大小限制（max_request_body_size）

`max_request_body_size`（单位 MB，`<= 0` 表示不限制）用于限制请求体大小，该检查在限流检查**之前**执行，被拒绝的请求不会消耗令牌。判定逻辑分两种路径：

- 请求带 `Content-Length` 头：直接依据该头判定，超限即拒绝，不预读请求体；
- 请求无 `Content-Length` 头（如 chunked 传输）：先预读实际请求体并累计字节数，超限即拒绝；未超限时将预读的请求体重放给下游应用。

超限请求返回 HTTP `413`，响应体示例：

```json
{
  "error": "request_body_too_large",
  "message": "Request body size (52428800 bytes) exceeds maximum"
}
```

### 内容四：超限行为与响应头

请求被限流拒绝时不会进入后续的推理调度流程，而是由中间件直接返回 HTTP 响应，默认状态码为 `error_status_code`（默认 `429`），响应体固定包含 `error: "rate_limit_exceeded"` 与 `message` 字段，并携带 `details`（`available` 剩余令牌数、`limit` 桶容量、`window_size` 时间窗口秒数）。`simple` 限流器在**放行与拒绝**的响应中都会携带 `X-RateLimit-Remaining`（剩余令牌数）、`X-RateLimit-Limit`（桶容量）、`X-RateLimit-Window`（时间窗口秒数）响应头，便于客户端感知当前限流状态并做退避重试。

### 内容五：配置热更新

Coordinator 支持配置热更新：配置文件变更被监听后，运行中的推理服务会实时应用新的 `rate_limit_config`，包括 `skip_paths`、`error_message`、`error_status_code`、`enable_rate_limit`、`max_request_body_size`，并同步更新令牌桶参数 `max_requests` 与 `window_size`。热更新配置项清单也可参见[热更新配置项说明](../configuration/update_config_whitelist.md)。

热更新注意事项：

- **仅当服务启动时已成功创建 `simple` 限流器时生效**（即启动时 `enable_rate_limit=true` 且 `provider` 为 `simple`，或 `olc` 加载失败已降级为 `simple`）。若启动时未开启限流或使用 `olc`，运行中修改配置不会自动创建/切换限流器，需按常规流程重启或重新部署。
- 热更新对参数做合法性校验：`max_requests` 必须 `>= 0`，`window_size` 必须 `> 0`，非法值会被拒绝并保持原值，同时记录告警日志。
- 令牌桶参数更新时，若新容量小于当前令牌数则截断；若扩容，则立即将差额补入令牌（扩容后额度立即可用）。

---

## 常见问题

1. 修改 `rate_limit_config` 后，未重启服务但配置未生效

   热更新仅对**启动时已创建 `simple` 限流器**的场景生效（见「原理说明」内容五）。若启动时未开启限流（`enable_rate_limit=false`）或使用 `provider: "olc"`，运行中修改配置不会生效，请按正常流程重启或重新部署。

2. 已配置 `max_requests`，但实测集群能承受的请求量明显高于配置值

   `simple` 限流器按**每个推理 Worker 进程**独立维护令牌桶，若 `inference_workers_config.num_workers` 大于 1，集群实际吞吐上限近似为 `max_requests × num_workers`，并非单一阈值，请结合 Worker 进程数评估。

3. 配置了 `scope: "per_ip"` 或 `"per_user"`，但观察到限流仍按全局维度生效

   当前 `simple` 限流器的实现固定使用全局令牌桶，`scope` 字段暂不区分客户端 IP 或用户，配置该字段不会改变实际限流行为。

4. `provider` 配置为 `"olc"`，但日志中提示 `Using simple rate limit, Failed to create olc limit middleware`

   表示 OLC 三方库未安装或规则加载失败，Coordinator 已自动降级为内置 `simple` 限流以保证服务可用。请检查是否已安装 OLC 库（`pip install git+https://gitcode.com/openFuyao/olc-python.git@v0.1.0`），以及 `olc_config_path` 指向的目录是否存在且包含 OLC 库所需的规则文件。

5. 部署时报错：`rate_limit_config.olc_config_path is required when provider is 'olc'` 或 `rate_limit_config.olc_config_path does not exist: xxx`

   表示 `provider` 为 `olc` 且 `enable_rate_limit` 为 `true` 时未填写 `olc_config_path`，或填写的目录不存在。请检查路径是否正确（支持绝对路径或相对路径）。另外，`provider` 取值非法会报错 `rate_limit_config.provider must be 'simple' or 'olc'`，`error_status_code` 超出 `100`-`599` 会报错 `error_status_code must be in range 100-599`。

6. 正常请求偶发收到 `429 rate_limit_exceeded`

   属于预期行为：说明当前请求速率已达到或超过配置的 `max_requests`/`window_size` 阈值。可参考响应体中的 `details.available`/`details.limit` 判断当前余量，适当调大限流阈值或降低客户端请求速率后重试。

7. 请求被返回 `413 request_body_too_large`

   表示请求体大小超过了 `max_request_body_size`（单位 MB，`<= 0` 表示不限制）配置的上限。请调大该配置或精简请求内容。

8. 服务刚启动、流量很小时就出现拥堵告警事件

   当前实现以限流检查时的剩余令牌数 `available` 为判定依据：令牌桶初始为满桶，只要 `available` 不低于 `max_requests × 85%` 即满足拥堵告警的上报条件，因此低流量或空载时反而容易触发。若观察到的告警行为与预期不符，请结合 `available`/`max_requests` 的实际数值与监控告警确认，并可在反馈问题时附上报障信息。
