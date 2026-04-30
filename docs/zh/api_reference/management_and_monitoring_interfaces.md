# 管理和监控接口

## 启动探针接口

**接口功能**

供探针查询服务启动状态。

**接口格式**

请求类型：**GET**
URL：`http(s)://{CoordinatorIP}:{管理端口}/startup`

  >[!NOTE]说明
  >
  > - `{CoordinatorIP}`：Coordinator 服务部署机器的 IP 或域名，取值来自配置 `api_config.coordinator_api_host`（默认 `127.0.0.1`），参考 `deployer/user_config.json` 取值或实际运行时节点IP。
  > - `{管理端口}`：配置项 `api_config.coordinator_api_mgmt_port`（默认 `1026`）。

**请求参数**
无

**使用样例**

```bash
curl -X GET "http://{CoordinatorIP}:{管理端口}/startup"
```

**响应示例**

```JSON
{ "status": "ok", "message": "Coordinator is starting up" }
```

---

## 存活探针接口

**接口功能**

供探针查询服务存活状态。

**接口格式**

请求类型：**GET**
URL：`http(s)://{CoordinatorIP}:{管理端口}/liveness`

  >[!NOTE]说明
  >
  > - `{CoordinatorIP}`：Coordinator 服务部署机器的 IP 或域名，取值来自配置 `api_config.coordinator_api_host`（默认 `127.0.0.1`），参考 `deployer/user_config.json` 取值或实际运行时节点IP。
  > - `{管理端口}`：配置项 `api_config.coordinator_api_mgmt_port`（默认 `1026`）。

**请求参数**
无

**使用样例**

```bash
curl -X GET "http://{CoordinatorIP}:{管理端口}/liveness"
```

**响应示例**

- 响应示例：

```JSON
{ "status": "ok", "message": "Coordinator is alive" }
```

---

## 就绪探针接口

**接口功能**

查询服务是否就绪。

**接口格式**

请求类型：**GET**
URL：`http(s)://{CoordinatorIP}:{管理端口}/readiness`

  >[!NOTE]说明
  >
  > - `{CoordinatorIP}`：Coordinator 服务部署机器的 IP 或域名，取值来自配置 `api_config.coordinator_api_host`（默认 `127.0.0.1`），参考 `deployer/user_config.json` 取值或实际运行时节点IP。
  > - `{管理端口}`：配置项 `api_config.coordinator_api_mgmt_port`（默认 `1026`）。

**请求参数**
无

**使用样例**

```bash
curl -X GET "http://{CoordinatorIP}:{管理端口}/readiness"
```

**响应示例**

```JSON
{ "status": "ok", "message": "Coordinator is ok", "ready": true }
```

>[!NOTE]说明
>若启用主备模式且当前节点非主节点，返回 `503`，并提示 `Coordinator is not master`。

---

## 指标查询接口

**接口功能**

返回Prometheus兼容的监控指标文本。

**接口格式**

请求类型：**GET**
URL：`http(s)://{CoordinatorIP}:{管理端口}/metrics`

  >[!NOTE]说明
  >
  > - `{CoordinatorIP}`：Coordinator 服务部署机器的 IP 或域名，取值来自配置 `api_config.coordinator_api_host`（默认 `127.0.0.1`），参考 `deployer/user_config.json` 取值或实际运行时节点IP。
  > - `{管理端口}`：配置项 `api_config.coordinator_api_mgmt_port`（默认 `1026`）。

**请求参数**
无

**使用样例**

```bash
curl -X GET "http://{CoordinatorIP}:{管理端口}/metrics"
```

**响应示例**

```Plain Text
# HELP python_gc_objects_collected_total Objects collected during gc
# TYPE python_gc_objects_collected_total counter
python_gc_objects_collected_total{generation="0"} 136662.0
python_gc_objects_collected_total{generation="1"} 18996.0
python_gc_objects_collected_total{generation="2"} 5696.0
# HELP python_gc_objects_uncollectable_total Uncollectable objects found during GC
# TYPE python_gc_objects_uncollectable_total counter
python_gc_objects_uncollectable_total{generation="0"} 0.0
python_gc_objects_uncollectable_total{generation="1"} 0.0
python_gc_objects_uncollectable_total{generation="2"} 0.0
# HELP python_gc_collections_total Number of times this generation was collected
# TYPE python_gc_collections_total counter
python_gc_collections_total{generation="0"} 6587.0
python_gc_collections_total{generation="1"} 596.0
python_gc_collections_total{generation="2"} 40.0
# HELP python_info Python platform information
# TYPE python_info gauge
python_info{implementation="CPython",major="3",minor="11",patchlevel="10",version="3.11.10"} 4.0
# HELP process_virtual_memory_bytes Virtual memory size in bytes.
# TYPE process_virtual_memory_bytes gauge
process_virtual_memory_bytes 46601515008.0
```

---

## 实例指标查询接口

**接口功能**

返回实例与端点维度的指标数据。

**接口格式**

请求类型：**GET**
URL：`http(s)://{CoordinatorIP}:{管理端口}/instance/metrics`

  >[!NOTE]说明
  >
  > - `{CoordinatorIP}`：Coordinator 服务部署机器的 IP 或域名，取值来自配置 `api_config.coordinator_api_host`（默认 `127.0.0.1`），参考 `deployer/user_config.json` 取值或实际运行时节点IP。
  > - `{管理端口}`：配置项 `api_config.coordinator_api_mgmt_port`（默认 `1026`）。

**请求参数**
无

**使用样例**

```bash
curl -X GET "http://{CoordinatorIP}:{管理端口}/instance/metrics"
```

**响应示例**

```JSON
{
  "1": [
    {
      "name": "process_resident_memory_bytes",
      "help": "Resident memory size in bytes.",
      "type": "gauge",
      "label": ["process_resident_memory_bytes"],
      "value": [3683950592.0]
    },
    {
      "name": "http_requests_total",
      "help": "Total number of requests by method, status and handler.",
      "type": "counter",
      "label": [
        "http_requests_total{handler=\"/v1/chat/completions\",method=\"POST\",status=\"2xx\"}",
        "http_requests_total{handler=\"/v1/completions\",method=\"POST\",status=\"2xx\"}"
      ],
      "value": [101.0, 1.0]
    }
  ],
  "2": [
    {
      "name": "python_gc_objects_collected_total",
      "help": "Objects collected during gc",
      "type": "counter",
      "label": [
        "python_gc_objects_collected_total{generation=\"0\"}",
        "python_gc_objects_collected_total{generation=\"1\"}",
        "python_gc_objects_collected_total{generation=\"2\"}"
      ],
      "value": [68146.0, 10867.0, 2848.0]
    }
  ]
}
```

**输出说明**

>[!NOTE]说明
>指标较多时仅返回结构与部分示例，具体标签维度以实际运行时为准。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| <instance_id> | object | 顶层键为实例ID，值为该实例的指标列表。 |
| <instance_id>[].name | string | 指标名称。 |
| <instance_id>[].help | string | 指标说明。 |
| <instance_id>[].type | string | 指标类型，包括以下几种：<ul><li>counter</li><li>gauge</li><li>histogram</li><li>summary</li></ul>histogram和summary类型会包含 `*_bucket`、`*_count`、`*_sum` 等label项。 |
| <instance_id>[].label | array | 标签数组，元素为 Prometheus 标签字符串。 |
| <instance_id>[].value | array | 与label一一对应的数值数组。 |

---

## 实例刷新接口

**接口功能**

刷新Coordinator中的实例列表（add/del/set）。

**接口格式**

请求类型：**POST**
URL：`http(s)://{CoordinatorIP}:{管理端口}/instances/refresh`

  >[!NOTE]说明
  >
  > - `{CoordinatorIP}`：Coordinator 服务部署机器的 IP 或域名，取值来自配置 `api_config.coordinator_api_host`（默认 `127.0.0.1`），参考 `deployer/user_config.json` 取值或实际运行时节点IP。
  > - `{管理端口}`：配置项 `api_config.coordinator_api_mgmt_port`（默认 `1026`）。

请求头：

- 必选：`Content-Type: application/json`
- 可选：无

**请求参数**

| 参数名 | 类型 | 说明 |
|---|---|---|
| event | string | 必选；事件类型：`add` / `del` / `set`。 |
| instances | array | 必选；实例列表。 |

**使用样例**

>[!NOTE]说明
>请求体必须为JSON格式，且大小不得超过10MB。

```bash
curl -X POST "http://{CoordinatorIP}:{管理端口}/instances/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "add",
    "instances": [
      {
        "job_name": "test-job",
        "model_name": "test-model",
        "id": 1,
        "role": "prefill",
        "endpoints": {
          "192.168.1.1": {
            "0": {
              "id": 0,
              "ip": "192.168.1.1",
              "business_port": "8080",
              "mgmt_port": "8081"
            }
          }
        }
      }
    ]
  }'
```

**响应示例**

```JSON
{
  "request_id": "refresh_request",
  "status": "success",
  "message": "Instance refresh completed",
  "data": {
    "timestamp": "2026-01-29T12:00:00+00:00",
    "event_type": "add",
    "instance_count": 1
  }
}
```

**输出说明**

| 参数名 | 类型 | 说明 |
|---|---|---|
| request_id | string | 请求标识。 |
| status | string | 请求状态。 |
| message | string | 响应消息。 |
| data | object | 响应数据。 |
| data.timestamp | string | 事件时间。 |
| data.event_type | string | 事件类型，与请求`event`对应。 |
| data.instance_count | integer | 实例数量。 |

---

## 根路径服务信息接口

**接口功能**

返回Coordinator服务信息与接口索引。

**接口格式**

请求类型：**GET**
URL：`http(s)://{CoordinatorIP}:{管理端口}/`

  >[!NOTE]说明
  >
  > - `{CoordinatorIP}`：Coordinator 服务部署机器的 IP 或域名，取值来自配置 `api_config.coordinator_api_host`（默认 `127.0.0.1`），参考 `deployer/user_config.json` 取值或实际运行时节点IP。
  > - `{管理端口}`：配置项 `api_config.coordinator_api_mgmt_port`（默认 `1026`）。

**请求参数**
无

**使用样例**

```bash
curl -X GET "http://{CoordinatorIP}:{管理端口}/"
```

**响应示例**

```JSON
{
  "service": "Motor Coordinator Server",
  "version": "1.0.0",
  "description": "coordinator server, management and inference APIs",
  "docs": {
    "management": [
      "/startup",
      "/liveness",
      "/readiness",
      "/metrics",
      "/instance/metrics",
      "/instances/refresh"
    ],
    "inference": [
      "/v1/models",
      "/v1/chat/completions",
      "/v1/completions",
      "/v1/metaserver"
    ]
  },
  "timestamp": "2026-01-29T12:00:00+00:00"
}
```

**输出说明**

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `service` | string | 服务名称。 |
| `version` | string | 服务版本号。 |
| `description` | string | 服务描述。 |
| `docs` | object | 接口索引信息。 |
| `docs.management` | array | 管理与监控接口列表。 |
| `docs.inference` | array | 推理接口列表。 |
| `timestamp` | string | 服务时间戳。 |
