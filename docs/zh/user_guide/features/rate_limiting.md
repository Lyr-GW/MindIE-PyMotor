# 服务限流特性说明

---

## 功能介绍

pyMotor 支持在 Coordinator 推理面（`/v1/completions`、`/v1/chat/completions` 等推理接口）上开启服务限流，通过 FastAPI 中间件对进入的请求进行拦截控制，避免瞬时流量过大导致服务过载；默认基于内置令牌桶（Token Bucket）算法实现全局限流，也可切换为三方过载控制库 [OLC](https://gitcode.com/openFuyao/olc-python) 实现更细粒度（按 URL 等标签）的 QPS/配额/并发限流。

---

## 前置说明

- 已参考[快速开始](../quick_start.md)完成一次基础服务部署，具备可正常运行的 `env.json` 和 `user_config.json` 配置文件。
- 限流能力仅对 **Coordinator 推理面 API** 生效，不作用于 Controller、Engine 内部处理流程，也不影响 NodeManager。
- 限流配置属于 `motor_coordinator_config.rate_limit_config`，**不在 `--update_config` 白名单内**（详见[更新配置白名单](../deployment/k8s/update_config_whitelist.md)），修改后需按正常流程重新执行部署才能生效。
- 若选择 `provider: "olc"`，需提前在镜像/环境中安装 OLC 三方库：

  ```bash
  pip install git+https://gitcode.com/openFuyao/olc-python.git@v0.1.0
  ```

  并准备好 OLC 规则配置目录（须包含 `overload-config.properties` 与 `olc.json` 两个文件）。若安装或规则加载失败，Coordinator 会自动降级为内置的令牌桶限流，不会导致服务启动失败。
- Coordinator 支持多进程推理 Worker（`inference_workers_config.num_workers`，默认 `4`），**每个 Worker 进程各自维护独立的令牌桶**，配置限流阈值时需考虑这一点（详见下文「原理说明」）。

---

## 快速实践

1. 已预先参考[快速开始](../quick_start.md)完成一次基础服务部署，且该服务正常运行。

2. 修改 `user_config.json` 文件，在 `motor_coordinator_config` 下新增 `rate_limit_config`：

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

3. 在 `examples/deployer` 目录下执行部署命令：

   ```bash
   cd examples/deployer
   # 方式一：指定配置目录（推荐）
   python3 deploy.py --config_dir ../infer_engines/vllm

   # 方式二：单独指定配置文件
   python3 deploy.py --user_config_path ../infer_engines/vllm/user_config.json --env_config_path ../infer_engines/vllm/env.json
   ```

4. 发起推理请求验证限流是否生效。正常情况下响应头会携带以下限流相关信息：

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

1. 配置示例

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
         "olc_config_path": ""
       }
     }
   }
   ```

   若选用 `provider: "olc"`，还需将 `olc_config_path` 指向规则配置目录，例如仓库自带的示例目录（详见 [OLC 示例说明](https://gitcode.com/Ascend/MindIE-PyMotor/blob/master/examples/features/http/overload_control/README.md)）：

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

2. 参数说明

   各项参数功能说明（加粗部分为重点关注项）

   | 配置项 | 取值类型 | 配置说明 |
   | --- | --- | --- |
   | **enable_rate_limit** | bool | 是否开启限流，默认值：`false`（关闭）。 |
   | **provider** | string | 限流提供者，可选 `simple`（内置令牌桶，默认值）或 `olc`（三方过载控制库）。`olc` 加载失败时会自动降级为 `simple`。 |
   | **max_requests** | int | 限流时间窗口内允许的最大请求数（即令牌桶容量），默认值：`1000`。仅 `provider: "simple"` 时生效。 |
   | **window_size** | int | 限流统计的时间窗口长度，单位秒，默认值：`60`。令牌填充速率 = `max_requests / window_size`。仅 `provider: "simple"` 时生效。 |
   | scope | string | 限流生效范围，默认值：`"global"`。当前 `simple` 实现固定使用全局令牌桶，该字段暂不区分 `per_ip`/`per_user`。 |
   | skip_paths | array | 不参与限流统计的路径前缀列表，默认包含 `/liveness`、`/readiness`、`/metrics` 等健康检查与文档类接口，可自定义追加。 |
   | error_message | string | 触发限流时返回给客户端的提示文案，默认值：`"too many requests, please try again later"`。 |
   | error_status_code | int | 触发限流时返回的 HTTP 状态码，取值范围 `100`-`599`，默认值：`429`。 |
   | olc_config_path | string | `provider: "olc"` 时的规则配置目录路径，目录下需包含 `overload-config.properties` 和 `olc.json`。`provider` 为 `olc` 且开启限流时必填，且目录必须真实存在，否则部署校验会报错。 |

---

## 原理说明

### 内容一：令牌桶限流（provider: simple）

`simple` 限流基于经典的**令牌桶算法**实现：桶容量为 `max_requests`，按 `max_requests / window_size`（令牌/秒）的速率持续填充，每个 HTTP 请求到达时尝试消耗 1 个令牌，桶内令牌充足则放行，否则直接拒绝，**不会排队等待**。该限流器为**全局单桶**，所有客户端、所有路径（`skip_paths` 列表除外）共享同一个令牌桶。

需要特别注意：Coordinator 推理面支持以 `inference_workers_config.num_workers`（默认 `4`）启动多个推理 Worker 进程，**每个 Worker 进程各自持有独立的令牌桶**，互不共享状态。因此集群实际可承受的总吞吐上限约为 `max_requests × num_workers`，而非单一的 `max_requests`，配置阈值时应结合部署的 Worker 进程数一并考虑。

当令牌桶已用额度（`max_requests - 剩余令牌`）升至 `max_requests` 的 85% 及以上时，会上报一次拥堵告警事件（`ReqCongestionEvent`，`reason_id=DEALING_WITH_CONGESTION`）；待已用额度回落到 75% 以下时会上报一次恢复事件，可结合监控告警观察系统的限流触发情况。

限流检查逻辑内置了失败兜底（fail-open）：若限流器本身发生异常，请求会被默认放行，不会因限流模块故障导致服务整体不可用。

### 内容二：过载控制（provider: olc）

`olc` 通过外部库 [OLC](https://gitcode.com/openFuyao/olc-python) 提供更丰富的限流能力：以请求的 URL、Method 等标签维度进行分组匹配，每个分组可配置 `quota`（固定时间窗口内的配额限流，等效 QPS）或 `concurrent`（并发数限流）等模式，规则定义在 `olc_config_path` 指向目录下的 `olc.json` 中，开关与规则来源等属性由 `overload-config.properties` 控制。

当以 `provider: "olc"` 启动失败（如未安装 OLC 库、规则目录缺失或加载异常）时，Coordinator 会记录错误日志并自动回退为内置的 `simple` 令牌桶限流，保证服务仍可正常提供限流保护。

### 内容三：超限行为与响应头

无论使用哪种 `provider`，请求被限流拒绝时均不会进入后续的推理调度流程，而是由中间件直接返回 HTTP 响应，默认状态码为 `error_status_code`（默认 `429`），响应体固定包含 `error: "rate_limit_exceeded"` 与 `message` 字段。`simple` 限流器额外会在响应头中携带 `X-RateLimit-Remaining`（剩余令牌数）、`X-RateLimit-Limit`（桶容量）、`X-RateLimit-Window`（时间窗口秒数），便于客户端感知当前限流状态并做退避重试。

---

## 常见问题

1. 修改 `rate_limit_config` 后，重新执行 `deploy.py --update_config` 未生效或报错

   限流相关配置**不在 `--update_config` 白名单内**（详见[更新配置白名单](../deployment/k8s/update_config_whitelist.md)），无法通过增量更新方式生效，请按正常流程重新执行完整部署。

2. 已配置 `max_requests`，但实测集群能承受的请求量明显高于配置值

   `simple` 限流器按**每个推理 Worker 进程**独立维护令牌桶，若 `inference_workers_config.num_workers` 大于 1，集群实际吞吐上限近似为 `max_requests × num_workers`，并非单一阈值，请结合 Worker 进程数评估。

3. 配置了 `scope: "per_ip"` 或 `"per_user"`，但观察到限流仍按全局维度生效

   当前 `simple` 限流器的实现固定使用全局令牌桶，`scope` 字段暂不区分客户端 IP 或用户，配置该字段不会改变实际限流行为。

4. `provider` 配置为 `"olc"`，但日志中提示 `Using simple rate limit, Failed to create olc limit middleware`

   表示 OLC 三方库未安装或规则加载失败，Coordinator 已自动降级为内置 `simple` 限流以保证服务可用。请检查是否已执行 `pip install git+https://gitcode.com/openFuyao/olc-python.git@v0.1.0`，以及 `olc_config_path` 指向的目录下是否存在 `overload-config.properties` 与 `olc.json`。

5. 部署时报错：`rate_limit_config.olc_config_path is required when provider is 'olc'` 或 `rate_limit_config.olc_config_path does not exist: xxx`

   表示 `provider` 为 `olc` 且 `enable_rate_limit` 为 `true` 时未填写 `olc_config_path`，或填写的目录不存在。请检查路径是否正确（支持绝对路径或相对于服务启动目录的相对路径）。

6. 正常请求偶发收到 `429 rate_limit_exceeded`

   属于预期行为：说明当前请求速率已达到或超过配置的 `max_requests`/`window_size` 阈值。可参考响应体中的 `details.available`/`details.limit` 判断当前余量，适当调大限流阈值或降低客户端请求速率后重试。
