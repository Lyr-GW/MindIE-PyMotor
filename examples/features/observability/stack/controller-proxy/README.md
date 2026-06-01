# controller-metrics-proxy

把 pyMotor **Controller** 的可观测性指标接口接入 Prometheus / Grafana 的轻量适配器。

## 为什么需要它

Controller 通过 `GET /observability/metrics`（默认端口 `1027`）暴露指标，但返回的
**不是**原生 Prometheus exposition 文本，而是一层 JSON 信封：

```json
{ "code": 200, "message": "Success", "data": "# HELP ...\n# TYPE ...\n..." }
```

真正的 Prometheus 文本在 `data` 字段里。Prometheus 直接抓取该端点会解析失败：

```
Invalid labels: "code":200,"message":"Success","data":"# HELP ...
```

并把 target 标记为 **DOWN**。因此 Grafana 无法直接接入 Controller 指标接口。

> 对比：Coordinator 的 `:1026/metrics` 和 Engine 的 `mgmt_port/metrics` 都是原生
> Prometheus 文本，可被 Prometheus 直接抓取；只有 Controller 套了 JSON 信封。

## 它做什么

`controller-metrics-proxy` 是一个仅依赖 Python 标准库的 sidecar exporter：

1. 请求 Controller 的 `/observability/metrics`；
2. 解析 JSON，取出 `data` 字段中的 Prometheus 文本；
3. 在 `:9106/metrics` 以标准 `text/plain; version=0.0.4` 重新暴露，供 Prometheus 抓取；
4. 额外暴露两个自监控指标：
   - `motor_controller_proxy_up{controller_url=...}`：上次抓取是否成功（1/0）；
   - `motor_controller_proxy_scrape_duration_seconds{controller_url=...}`：抓取耗时。

若上游返回纯文本（例如直接指向 Coordinator `/metrics`），proxy 会原样透传，因此
它也可作为通用的「JSON→Prometheus」解包器使用。

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CONTROLLER_METRICS_URL` | `http://host.docker.internal:1027/observability/metrics` | Controller 指标接口地址 |
| `PROXY_PORT` | `9106` | 本 exporter 监听端口 |
| `CONTROLLER_TIMEOUT` | `5` | 抓取超时（秒） |
| `JSON_DATA_KEY` | `data` | JSON 信封中承载 Prometheus 文本的字段名 |
| `INSECURE_SKIP_VERIFY` | `true` | https 时是否跳过证书校验（自签名场景） |
| `CA_FILE` / `CERT_FILE` / `KEY_FILE` | 空 | 访问启用 TLS 的 Controller 时的 mTLS 证书 |
| `PROXY_LOG_LEVEL` | `INFO` | 日志级别 |

## 在观测栈中的接入方式

- `docker-compose.yml` 中已加入 `controller-metrics-proxy` service（默认随栈启动）。
- `prometheus/prometheus.yml` 的 `motor-controller` job 抓取的是 `controller-metrics-proxy:9106`
  （**而非**直接抓 `1027`）。

接入真实 Controller：编辑 `.env` 中的 `CONTROLLER_METRICS_URL` 指向你的 Controller
observability 地址，然后 `docker compose up -d controller-metrics-proxy`。

## 本地离线联调（无需完整集群）

`dev_stub_controller.py` 在 `:1027/observability/metrics` 返回与真实 Controller 完全
相同的 JSON 信封，`data` 取自真实样本 `tests/coordinator/core/metrics_example.txt`，
计数器随时间递增、gauge 抖动，便于在没有集群时验证 proxy + Grafana 面板：

```bash
# 1) 启动桩 Controller（宿主机）
python dev_stub_controller.py            # :1027/observability/metrics

# 2) 启动观测栈（proxy 默认指向 host.docker.internal:1027）
cd .. && ./start.sh

# 3) 验证
curl -s localhost:1027/observability/metrics | head -c 80      # JSON 信封
curl -s localhost:9106/metrics | grep motor_controller_proxy_up # proxy 解包后 + up 1
```

随后访问 Grafana（http://localhost:3000 ，motor/motor），即可看到来自 Controller
接口的指标。
