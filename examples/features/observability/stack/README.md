# pyMotor 可观测性一键栈

本目录提供 Prometheus、Grafana、Tempo、OTel Collector 等组件的一键发现与拉起能力。

## 文档导航

| 文档 | 说明 |
|------|------|
| [SERVICE_GUIDE.md](SERVICE_GUIDE.md) | 前提条件、镜像准备、`launch.sh` 拉起与停止、常见问题 |
| [GRAFANA_GUIDE.md](GRAFANA_GUIDE.md) | Grafana 页面、数据源、看板设计与新增指标步骤 |
| [archive/](archive/) | 历史合入 / 联调记录（只读归档，不再维护） |

## 快速开始

```bash
cd examples/features/observability/stack
MOTOR_NAMESPACE=<namespace> ./launch.sh --minimal
```

Grafana 默认：<http://localhost:3000>（`motor` / `motor`）。
