# [2026-10-29] Observability stack did not discover KV pool metrics

- **现象 (Symptom)**：Prometheus discovered Coordinator and engine targets but did not scrape the selected namespace's MemCache or Mooncake pool Service, leaving pool dashboard panels without data.
- **根因 (Root cause)**：`examples/features/observability/stack/scripts/discover-targets.py` only generated Coordinator and engine scrape targets; it did not find a namespace-local KV pool Service or add a target to the runtime configuration.
- **为什么会写出 (Why)**：The observability discovery flow treated Motor services as the complete target set and did not include the independently deployed KV pool endpoint.
- **修复 (Fix)**：Discover one Service matching the `mindie-motor-kvs-master` prefix with a ClusterIP and unique `metrics` port. Generate `motor-kv-pool` with namespace/component/service labels, bridge the Service address to Docker through the existing host TCP forwarder, and format IPv6 targets with brackets. Added the shared backend dashboard and operator documentation.
- **测试拦截 (Test interception)**：`tests/examples/observability/test_pool_discovery.py` covers namespace labels, Docker forwarding, no pool Service, multiple valid Services, and IPv6 target formatting. Manual discovery assertions passed; the repository test runner could not execute because this host has no pytest/pip command.
- **场景 (Scenario)**：A stack is launched for a namespace containing one MemCache or Mooncake KV pool Service exposing a named metrics port; invalid or multiple pool Services must not yield an ambiguous scrape target.
- **关键词 (Keywords)**：observability, KV pool, Prometheus, Service discovery, namespace
