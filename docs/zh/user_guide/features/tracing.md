# Tracing特性说明

---

## 功能介绍

MindIE Motor Tracing能力基于三方件`OpenTelemetry`实现，通过OTLP协议将一次请求在Coordinator、Prefill实例、Decode实例间的完整调用链路（各阶段耗时、TTFT/TTOT等关键指标）上报至链路追踪后端（如Jaeger），帮助开发者在PD分离等复杂拓扑下定位性能瓶颈与异常请求。`OpenTelemetry`相关资料可参考[OpenTelemetry文档](https://opentelemetry.io/zh/docs/)。

---

## 前置说明

- 已参考[快速开始](../quick_start.md)完成一次基础服务部署，具备可正常运行的 `env.json` 和 `user_config.json` 配置文件。
- 需额外准备一个支持接收OTLP协议的链路追踪后端（如Jaeger），用于接收、存储与展示上报的调用链数据。
- Tracing能力目前仅对`motor_coordinator`、`motor_engine_prefill`、`motor_engine_decode`三个模块生效，暂时不支持`motor_controller`模块。
- 各模块的追踪数据上报地址（`endpoint`/`otlp-traces-endpoint`）与上报协议（`OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`）需保持一致，否则会上报失败。
- 生产环境建议将 `OTEL_EXPORTER_OTLP_TRACES_INSECURE` 设置为 `false`，开启安全传输协议。

---

## 原理说明

### 上报开关与采样策略

MindIE Motor各模块基于`OpenTelemetry`的`TracerProvider`实现链路追踪，是否开启由该模块的`endpoint`（Coordinator）/`otlp-traces-endpoint`（Prefill、Decode引擎）配置项决定：地址非空时开启上报，否则退化为NoOp（不产生任何开销）。

采样策略采用`ParentBased`组合采样器，按当前Span的父Span来源与采样状态分为四种场景（远程/本地、已采样/未采样），并叠加根采样率共5个可调参数，均基于`TraceIdRatioBased`按比例采样。

- 无父Span（请求入口）：命中`root_sampling_rate`。
- 父Span来自远程调用：命中`remote_parent_sampled`（父已采样）或`remote_parent_not_sampled`（父未采样）。
- 父Span来自本地调用：命中`local_parent_sampled`（父已采样）或`local_parent_not_sampled`（父未采样）。

将全部参数保持默认值`1.0`即可全量采集调用链路，便于问题定位；如链路数据量过大影响后端存储或性能，可结合业务场景适当调低采样率。

### 链路可视化

服务侧上报的追踪数据以Span形式通过OTLP协议发送至链路追踪后端，各Span间通过`traceparent`/`tracestate`请求头串联，从而在Coordinator转发请求至Prefill/Decode实例的过程中保持同一条调用链路。以Jaeger为例，部署完成后通过浏览器访问`http://<jaeger所在IP>:16686`，即可按服务名称（对应`OTEL_SERVICE_NAME`）查询调用链路，页面效果如下。

![Snipaste_2026-03-31_20-59-16.jpg](https://raw.gitcode.com/user-images/assets/9428015/e2338b5c-646f-4349-b62b-1dae9c95b217/Snipaste_2026-03-31_20-59-16.jpg 'Snipaste_2026-03-31_20-59-16.jpg')

---

![Snipaste_2026-03-31_20-59-24.jpg](https://raw.gitcode.com/user-images/assets/9428015/85f73899-a6cd-4667-837d-300b432d2e2a/Snipaste_2026-03-31_20-59-24.jpg 'Snipaste_2026-03-31_20-59-24.jpg')

单条链路中可查看请求在各阶段（Coordinator调度、Prefill/Decode推理）的耗时，以及TTFT（首Token时延）、TTOT（单Token平均时延）等关键指标，用于辅助性能调优与问题定位。

---

## 快速实践

1. 在`examples/deployer`目录下执行以下命令，打开`env.json`文件。

   ```bash
   vim ../infer_engines/vllm/env.json
   ```

2. 在`motor_coordinator_env`、`motor_engine_prefill_env`、`motor_engine_decode_env`三个配置项下新增以下环境变量，修改完成后保存文件。

   ```json
   {
     "version": "2.0.0",
     "motor_common_env": {},
     "motor_controller_env": {},
     "motor_coordinator_env": {
       "OTEL_SERVICE_NAME": "mindie-motor",
       "OTEL_EXPORTER_OTLP_TRACES_INSECURE": "true",
       "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf"
     },
     "motor_engine_prefill_env": {
       "OTEL_SERVICE_NAME": "vllm-server-p",
       "OTEL_EXPORTER_OTLP_TRACES_INSECURE": "true",
       "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf"
     },
     "motor_engine_decode_env": {
       "OTEL_SERVICE_NAME": "vllm-server-d",
       "OTEL_EXPORTER_OTLP_TRACES_INSECURE": "true",
       "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf"
     },
     "motor_kv_cache_store_env": {}
   }
   ```

3. 在`examples/deployer`目录下执行以下命令，打开`user_config.json`文件。

   ```bash
   vim ../infer_engines/vllm/user_config.json
   ```

4. 在`motor_coordinator_config`下新增`tracer_config`，并在`motor_engine_prefill_config`、`motor_engine_decode_config`的`engine_config`下新增`otlp-traces-endpoint`，修改完成后保存文件。

   ```json
   {
     "motor_coordinator_config": {
       "tracer_config": {
         "endpoint": "http://xx.xx.xx.xx:4318/v1/traces",
         "root_sampling_rate": 1.0,
         "remote_parent_sampled": 1.0,
         "remote_parent_not_sampled": 1.0,
         "local_parent_sampled": 1.0,
         "local_parent_not_sampled": 1.0
       }
     },
     "motor_engine_prefill_config": {
       "engine_config": {
         "otlp-traces-endpoint": "http://xx.xx.xx.xx:4318/v1/traces"
       }
     },
     "motor_engine_decode_config": {
       "engine_config": {
         "otlp-traces-endpoint": "http://xx.xx.xx.xx:4318/v1/traces"
       }
     }
   }
   ```

   `endpoint`/`otlp-traces-endpoint` 均需填写为链路追踪后端的OTLP接入地址，格式需与`OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`匹配，可选 `http://xx.xx.xx.xx:4318/v1/traces`（http/protobuf）或 `grpc://xx.xx.xx.xx:4317`（grpc）。

5. 在`examples/deployer`目录下执行部署命令。

   ```bash
   cd examples/deployer
   # 方式一：指定配置目录（推荐）
   python3 deploy.py --config_dir ../infer_engines/vllm

   # 方式二：单独指定配置文件
   python3 deploy.py --user_config_path ../infer_engines/vllm/user_config.json --env_config_path ../infer_engines/vllm/env.json
   ```

6. 部署一个链路追踪后端接收上报数据，以Jaeger为例（详见[Jaeger官方文档](https://www.jaegertracing.io/docs/2.14/)）。

   ```bash
   ./jaeger --set receivers.otlp.protocols.http.endpoint=0.0.0.0:4318 --set receivers.otlp.protocols.grpc.endpoint=0.0.0.0:4317 &
   ```

   启动后通过浏览器访问 `http://<jaeger所在IP>:16686`，发起一次推理请求后即可在页面查询到对应的调用链路。

---

## 典型配置

1. 配置示例。

   以下为可直接使用的推荐配置，仅需将`xx.xx.xx.xx`替换为实际链路追踪后端（如Jaeger）所在地址，其余字段可直接沿用。

   `env.json`需在`motor_coordinator_env`、`motor_engine_prefill_env`、`motor_engine_decode_env`下新增。

   ```json
   {
     "OTEL_SERVICE_NAME": "mindie-motor",
     "OTEL_EXPORTER_OTLP_TRACES_INSECURE": "true",
     "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf"
   }
   ```

   `motor_engine_prefill_env`、`motor_engine_decode_env`下的`OTEL_SERVICE_NAME`建议分别设置为`vllm-server-p`、`vllm-server-d`以区分模块，其余两项与上述保持一致。

   `user_config.json`需在`motor_coordinator_config`下新增`tracer_config`，并在`motor_engine_prefill_config`、`motor_engine_decode_config`的`engine_config`下新增`otlp-traces-endpoint`。

   ```json
   {
     "motor_coordinator_config": {
       "tracer_config": {
         "endpoint": "http://xx.xx.xx.xx:4318/v1/traces",
         "root_sampling_rate": 1.0,
         "remote_parent_sampled": 1.0,
         "remote_parent_not_sampled": 1.0,
         "local_parent_sampled": 1.0,
         "local_parent_not_sampled": 1.0
       }
     },
     "motor_engine_prefill_config": {
       "engine_config": {
         "otlp-traces-endpoint": "http://xx.xx.xx.xx:4318/v1/traces"
       }
     },
     "motor_engine_decode_config": {
       "engine_config": {
         "otlp-traces-endpoint": "http://xx.xx.xx.xx:4318/v1/traces"
       }
     }
   }
   ```

   若`OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`设置为`grpc`，上述三处地址需相应改为`grpc://xx.xx.xx.xx:4317`格式。

2. 参数说明。

   各项参数功能说明（加粗部分为重点关注项）。

   | 配置项 | 所属文件 | 取值类型 | 配置说明 |
   | --- | --- | --- | --- |
   | **OTEL_SERVICE_NAME** | env.json | string | 上报数据的服务名称，用于在链路追踪后端区分不同模块，建议按模块命名，如`mindie-motor`、`vllm-server-p`、`vllm-server-d`。 |
   | OTEL_EXPORTER_OTLP_TRACES_INSECURE | env.json | string(bool) | 是否开启非安全协议，取值`true`/`false`，生产环境建议设置为`false`。 |
   | **OTEL_EXPORTER_OTLP_TRACES_PROTOCOL** | env.json | string | 上报数据协议，可选`grpc`或`http/protobuf`，缺省默认为`grpc`，需与`endpoint`/`otlp-traces-endpoint`地址格式保持一致。 |
   | **endpoint** | user_config.json（`motor_coordinator_config.tracer_config`） | string | Coordinator侧链路追踪数据的上报地址，开启Tracing能力必填，为空时Coordinator不上报追踪数据。 |
   | otlp-traces-endpoint | user_config.json（engine的`engine_config`） | string | Prefill/Decode引擎侧链路追踪数据的上报地址，填写方法与`endpoint`一致。 |
   | root_sampling_rate | user_config.json（`tracer_config`） | float | 根采样率，即没有父Span（如请求入口的第一次调用）的采样概率，默认值：`1.0`，表示所有根请求都会被记录，`0.5`表示约半数根请求被记录。 |
   | remote_parent_sampled | user_config.json（`tracer_config`） | float | 当前Span的父Span来自远程服务且父Span已被采样时，当前Span的采样概率，默认值：`1.0`。 |
   | remote_parent_not_sampled | user_config.json（`tracer_config`） | float | 当前Span的父Span来自远程服务但父Span未被采样时，当前Span的采样概率，默认值：`1.0`。 |
   | local_parent_sampled | user_config.json（`tracer_config`） | float | 当前Span的父Span来自本地服务实例且父Span已被采样时，当前Span的采样概率，默认值：`1.0`。 |
   | local_parent_not_sampled | user_config.json（`tracer_config`） | float | 当前Span的父Span来自本地服务实例但父Span未被采样时，当前Span的采样概率，默认值：`1.0`。 |

---

## 常见问题

1. 链路追踪后端查询不到任何调用链路数据

   请依次排查。
   - Coordinator的`endpoint`（或引擎的`otlp-traces-endpoint`）是否已正确配置且不为空，为空时该模块不会上报数据。
   - `env.json`中`OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`是否与`endpoint`地址的协议格式一致（`http/protobuf`对应`http://xxx:4318/v1/traces`，`grpc`对应`grpc://xxx:4317`）。
   - 服务器与链路追踪后端之间的网络端口（`4318`/`4317`）是否可达。

2. 报错：`env OTEL_EXPORTER_OTLP_TRACES_PROTOCOL:'xxx' is invalid`

   表示`OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`取值非法，请检查`env.json`中该环境变量的取值，仅支持`grpc`或`http/protobuf`。

3. 只需要部分模块开启Tracing能力

   Tracing能力按模块独立开关，仅需在需要观测的模块（Coordinator、Prefill、Decode）配置对应的`endpoint`/`otlp-traces-endpoint`，未配置的模块不会上报数据，互不影响。
