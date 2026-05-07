# Motor Node Manager（节点管理器）

## 功能介绍

Node Manager 进程入口为 `motor/node_manager/main.py`。`init_all_modules` 依次创建：

| 对象 | 源码 | 职责摘要 |
|------|------|----------|
| `NodeManagerConfig` | `motor/config/node_manager.py` | 节点侧配置 |
| `NodeManagerAPI` | `motor/node_manager/api_server/node_manager_api.py` | 在后台线程跑 uvicorn，挂载 FastAPI 路由 |
| `Daemon` | `motor/node_manager/core/daemon.py` | 根据 Controller 下发的启动命令拉起 **`engine_server`** 子进程，或统一停止并清理 PID |
| `EngineManager` | `motor/node_manager/core/engine_manager.py` | 后台线程向 Controller **注册/重注册**；解析 `StartCmdMsg`、写 ranktable 文件等 |
| `HeartbeatManager` | `motor/node_manager/core/heartbeat_manager.py` | 向 Controller 上报心跳；按间隔请求各 endpoint 上 **engine 管理面** 的 `/status`；异常累计可触发自杀标志 |

主循环中若 `HeartbeatManager().should_suicide()` 为真，会执行 `suicide_procedure()`：停止 config watcher、停止各模块，进程以返回码 `-1` 退出（见 `main.py` 注释「-1: rescheduling」）。

## 环境准备

- 配置路径：`Env.user_config_path or Env.config_path` 传给 `NodeManagerConfig.from_json`（见 `main.py`）。
- 与 K8s 部署、挂载 `user_config`、探针等一致的信息见 [环境准备](../environment_preparation.md)。

## 配置说明

用户配置中对应块为 **`motor_nodemanger_config`**（键名与 [配置参考](../service_deployment/config_reference.md) 一致）。代码中涉及：

- `api_config.pod_ip`、`node_manager_port`：`NodeManagerAPI` 监听地址与端口。
    - 未配置 `pod_ip` 时 host 退化为 `0.0.0.0`（见 `NodeManagerAPI.__init__`）。
    - `node_manager_port` 在 `motor/config/node_manager.py` 中默认为 `1026`；仅当 `NodeManagerAPI` 未传入 `config` 实例时（仅作为兜底分支），代码内才会回落到 `8080`，正常部署不会触达此后备值。
- `mgmt_tls_config`：为真时为 Node Manager HTTP 服务启用 TLS（`CertUtil.create_ssl_context`）。
- `basic_config`：`job_name`、`heartbeat_interval_seconds`、`parallel_config`、`device_num`、`enable_multi_endpoints` 等，被 `Daemon` / `EngineManager` / `HeartbeatManager` 使用。

## Node Manager HTTP API

`node_manager_api.py` 中 FastAPI 应用注册：

| 方法 | 路径 | 行为 |
|------|------|------|
| `POST` | `/node-manager/start` | 解析 `StartCmdMsg` → `EngineManager.parse_start_cmd` → `Daemon.pull_engine` → `HeartbeatManager.update_endpoint` 与 `start()` |
| `POST` | `/node-manager/stop` | `Daemon().stop`，停止所有已拉起的 engine 进程 |
| `GET` | `/node-manager/status` | `HeartbeatManager().check_all_endpoints_normal`，返回 `{"status": bool}` |

## 使用样例

```bash
python -m motor.node_manager.main
```

亦可通过部署镜像中的入口脚本调用等价模块路径；以实际镜像与 `deployer` 模板为准。

## 报错与日志

- `/node-manager/start` 在校验失败时返回 `400`/`422`，body 解析异常或 `pull_engine` 失败时返回 `500`（文案见代码中 `HTTPException` 的 `detail`）。
- `Daemon.pull_engine` 失败会抛出 `RuntimeError`，日志中包含子进程立即退出等信息。
