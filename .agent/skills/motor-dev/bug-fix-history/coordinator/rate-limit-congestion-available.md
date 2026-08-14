# [2026-08-14] 令牌桶空载满桶误报 Coordinator 拥堵告警

- **现象 (Symptom)**：服务刚启动或流量很低时上报 `Coordinator Request Congestion Alarm`（`alarm_id=0xFC001005`）。告警文案把剩余令牌数写成 “current number of inference requests”。
- **根因 (Root cause)**：`motor/coordinator/middleware/rate_limiter.py` 的 `is_allowed()` 用 `available`（剩余令牌）与 `max_requests * 85%` 比较。桶初始为满，`available` 接近容量，空载即满足触发条件。
- **为什么会写出 (Why)**：把 `available` 当成在途请求数。告警文案写的是 request count，比较的却是剩余配额，判定方向与语义相反。
- **修复 (Fix)**：改为 `used = max_requests - available`；`used >= 85%` 告警，`used < 75%` 恢复。文档同步为已用额度口径。
- **测试拦截 (Test interception)**：`tests/coordinator/middleware/test_rate_limiter.py` — 空载不满报、消耗至 85% 才告警且不重复、回落到 75% 以下恢复、上报失败 fail-open。
- **场景 (Scenario)**：`provider=simple` 且已创建令牌桶；空载/低流量，或突发打满后再回落。
- **关键词 (Keywords)**：rate_limiter, congestion, available, used, ReqCongestionEvent
