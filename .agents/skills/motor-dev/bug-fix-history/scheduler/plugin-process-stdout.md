# [2026-11-12] 插件导入日志污染 JSON 通信

- **现象 (Symptom)**：真实子进程加载插件时，父进程读取首条响应出现 JSONDecodeError，插件被错误降级。
- **根因 (Root cause)**：仅在 `plugin_worker.main()` 内重定向 stdout，无法覆盖此前 Python 导入 policy 包、配置和日志组件时写出的启动日志。
- **为什么会写出 (Why)**：初版把导入阶段当成无输出操作；子进程 stdout 同时承载协议和应用日志。
- **修复 (Fix)**：`plugin_runner.py` 的固定启动代码在导入任何 Motor 或客户模块前重定向 stdout，保留原流用于协议；构造函数和 rank 的普通输出进入 stderr。
- **测试拦截 (Test interception)**：`test_real_entry_point_ranks_and_shutdown_reaps_child` 使用真实 distribution metadata 和子进程，并在客户构造函数中输出文本；加载和选点仍成功。
- **场景 (Scenario)**：插件模块、Motor 导入路径或客户构造函数有 stdout 输出。
- **关键词 (Keywords)**：scheduler, plugin, subprocess, stdout, JSONDecodeError
