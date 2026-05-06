# MindIE-PyMotor 新手任务池 🌱

> 欢迎来到 MindIE-PyMotor 新手任务池！本项目致力于帮助开源新手从零开始，循序渐进地参与 LLM 分布式推理框架的贡献。无论你是文档爱好者、Python 初学者还是分布式系统探索者，都能在这里找到适合你的任务。

---

## 📋 目录

- [任务分级体系](#任务分级体系)
- [任务提交与评审流程](#任务提交与评审流程)
- [L0 级任务（零代码任务）](#l0-级任务零代码任务)
- [L1 级任务（轻量级任务）](#l1-级任务轻量级任务)
- [L2 级任务（联创特性需求任务）](#l2-级任务联创特性需求任务)
- [学习路径推荐](#学习路径推荐)
- [参考资源](#参考资源)

---

## 任务分级体系

| 级别 | 定位 | 前置要求 | 预计耗时 | 难度系数 |
|------|------|----------|----------|----------|
| **L0** | 零代码任务 | 无编程要求，仅需阅读理解能力 | 0.5~2 小时 | ⭐ |
| **L1** | 轻量级任务 | 基础 Python 编程能力，了解 pytest | 2~6 小时 | ⭐⭐ |
| **L2** | 联创特性&需求任务 | Python 进阶能力，了解分布式系统/LLM 推理 | 1~3 天 | ⭐⭐⭐ |

### 任务模板

每个任务遵循以下标准化模板：

```
### [L{级别}] {任务编号}: {任务标题}

- **目标描述**: 明确任务要完成什么
- **所需技能**: 完成任务需要具备的能力
- **涉及模块**: 涉及的项目代码/文档路径
- **完成标准**: 可验证的完成条件
- **参考资源**: 相关文档、示例或链接
- **预计耗时**: 预估完成时间
- **难度系数**: ⭐~⭐⭐⭐
- **认领方式**: 在本 issue 下回复 "认领 T{编号}"
```

---

## 任务提交与评审流程

### 1. 认领任务

在本 issue 评论区回复 `认领 T{编号}`，维护者会在 24 小时内确认并分配任务。每位贡献者同时最多认领 2 个任务。

### 2. 开发流程

```bash
# 1. Fork 并 Clone 仓库
git clone https://gitcode.com/{your_username}/MindIE-PyMotor.git
cd MindIE-PyMotor

# 2. 创建任务分支
git checkout -b task/T{编号}-{简短描述}

# 3. 完成任务并提交
git add .
git commit -m "feat(T{编号}): {简短描述}"

# 4. 推送并发起 PR
git push origin task/T{编号}-{简短描述}
```

### 3. PR 提交规范

- PR 标题格式：`[T{编号}] {任务标题}`
- PR 描述中需包含：
  - 关联的 issue 编号
  - 任务完成情况说明
  - 自测结果（如适用）
- 在 PR 评论区回复 `compile` 触发 CI 检查

### 4. 评审标准

| 级别 | 评审重点 |
|------|----------|
| L0 | 内容准确性、格式规范性、表述清晰度 |
| L1 | 代码规范（Ruff 检查通过）、测试覆盖、功能正确性 |
| L2 | 方案合理性、设计文档完整性、代码质量、测试充分性 |

### 5. 完成激励

- ✅ 完成 1 个 L0 任务：获得「初来乍到」徽章
- ✅ 完成 2 个 L1 任务：获得「代码新秀」徽章
- ✅ 完成 1 个 L2 任务：获得「联创先锋」徽章
- ✅ 累计完成 5 个任务：加入项目 Contributors 列表

---

## L0 级任务（零代码任务）

> L0 任务无需编码能力，每个任务都列出了**具体的问题清单**，新手可以直接逐项修复。通过这些任务，你将熟悉项目结构、了解贡献流程，为后续进阶打下基础。

---

### [L0] T01: 修复文档中的拼写错误（第一批：uesr_config / moocake / histogramh）

- **目标描述**: 修复项目文档中已确认的拼写错误，每个错误都给出了具体位置和修正方式
- **所需技能**: 基本的英语拼写能力，Markdown 编辑能力
- **涉及模块**: `docs/zh/` 下多个文件
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 |
  |---|------|------|----------|--------|
  | 1 | `docs/zh/user_guide/tracing_deployment.md` | 52 | `uesr_config.json` | `user_config.json` |
  | 2 | `docs/zh/user_guide/log_config_guide.md` | 15 | `uesr_config.json` | `user_config.json` |
  | 3 | `docs/zh/user_guide/KV_pool_deployment_guide.md` | 24 | `uesr_config.json` | `user_config.json` |
  | 4 | `docs/zh/user_guide/KV_cache_affinity_deployment.md` | 89 | `uesr_config.json` | `user_config.json` |
  | 5 | `docs/zh/user_guide/KV_cache_affinity_deployment.md` | 17 | `--name moocake_patch` | `--name mooncake_patch` |
  | 6 | `docs/zh/user_guide/KV_cache_affinity_deployment.md` | 75 | `moocake_patch` | `mooncake_patch` |
  | 7 | `docs/zh/api_reference/management_and_monitoring_interfaces.md` | 234 | `histogramh和summary类型` | `histogram和summary类型` |

- **完成标准**:
  1. 修正上述 7 处拼写错误
  2. 全局搜索确认无遗漏的同类拼写错误
  3. PR 通过 CI 检查
- **参考资源**: [Markdown 语法指南](https://www.markdownguide.org/)
- **预计耗时**: 0.5~1 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T01"

---

### [L0] T02: 修复文档中的中文用词错误（显示→显式 / 已→以 / 相应→响应）

- **目标描述**: 修复项目文档中已确认的中文用词错误
- **所需技能**: 中文语言能力，Markdown 编辑能力
- **涉及模块**: `docs/zh/` 下多个文件
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 | 说明 |
  |---|------|------|----------|--------|------|
  | 1 | `docs/zh/user_guide/quick_start.md` | 209 | `建议显示指定` | `建议显式指定` | "显示"(display) ≠ "显式"(explicit) |
  | 2 | `docs/zh/user_guide/quick_start.md` | 211 | `直接已json对象形式填写` | `直接以json对象形式填写` | "已"(already) ≠ "以"(with/by) |
  | 3 | `docs/zh/api_reference/service_interface.md` | 88 | `流式相应样例` | `流式响应样例` | "相应"(corresponding) ≠ "响应"(response) |

- **完成标准**:
  1. 修正上述 3 处用词错误
  2. 在同文件中搜索是否还有同类用词错误
  3. PR 通过 CI 检查
- **参考资源**: 现代汉语词典
- **预计耗时**: 0.5 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T02"

---

### [L0] T03: 修复文档中的配置键名拼写错误和大小写错误

- **目标描述**: 修复文档中 JSON 配置键名的拼写错误，这些错误会导致用户配置无法被正确识别
- **所需技能**: 基本的 JSON 语法知识，英语拼写能力
- **涉及模块**: `docs/zh/` 下多个文件
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 | 说明 |
  |---|------|------|----------|--------|------|
  | 1 | `docs/zh/user_guide/standby_deployment.md` | 137 | `"motor_Controller_config"` | `"motor_controller_config"` | JSON 键名区分大小写，C 不应大写 |
  | 2 | `docs/zh/user_guide/standby_deployment.md` | 754 | `persistentvolume/etcd data-0 created` | `persistentvolume/etcd-data-0 created` | K8s 资源名不允许空格，且与上下文 etcd-data-1/2 不一致 |

- **完成标准**:
  1. 修正上述 2 处配置键名错误
  2. 搜索 `standby_deployment.md` 中是否还有其他 `motor_Controller` 的拼写
  3. PR 通过 CI 检查
- **参考资源**: 项目 `motor/config/` 目录下的配置类定义
- **预计耗时**: 0.5 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T03"

---

### [L0] T04: 修复示例目录中的文件名拼写错误和路径引用错误

- **目标描述**: 修复 examples 目录下的文件名拼写错误和文档中的路径引用错误
- **所需技能**: 基本的英语拼写能力，Git 操作基础
- **涉及模块**: `examples/` 目录
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 |
  |---|------|------|----------|--------|
  | 1 | `examples/features/observability/REAME.md`（文件名） | - | `REAME.md` | `README.md`（缺少字母 D） |
  | 2 | `examples/features/http/api_key/README.md` | 12,34,40,46,151 | `examples/api_key/generate_api_key.py` | `examples/features/http/api_key/generate_api_key.py` |
  | 3 | `examples/features/http/api_key/generate_api_key.py` | 10,14,17,20,106,109,112,115 | `deployer/api_key/generate_api_key.py` | `examples/features/http/api_key/generate_api_key.py` |
  | 4 | `examples/deployer/README.md` | 80 | `env_v3_1_A2_EP32.json` | `env.json`（该文件实际不存在） |
  | 5 | `examples/features/fault_tolerance/ras_starter/readme.md` | 24 | `单机[链接](...)` | `点击[链接](...)`（"单机"是"点击"的错别字） |
  | 6 | `examples/features/fault_tolerance/ras_starter/readme.md` | 24 | 链接路径 `examples/fault_tolerance/...` | `examples/features/fault_tolerance/...`（缺少 `features/`） |
  | 7 | `examples/features/fault_tolerance/ras_starter/readme.md` | 28 | `"/examples/deployer"` | `"examples/deployer"`（去掉前导 `/`） |
  | 8 | `examples/features/fault_tolerance/ras_monitor/readme.md` | 47 | `bash delete` | `bash delete.sh`（脚本名不完整） |

- **完成标准**:
  1. 修正上述 8 处错误（含文件重命名）
  2. 确认重命名后无其他文件引用旧文件名
  3. PR 通过 CI 检查
- **参考资源**: [Git 重命名操作](https://git-scm.com/docs/git-mv)
- **预计耗时**: 1~2 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T04"

---

### [L0] T05: 修复文档中的 Markdown 格式错误

- **目标描述**: 修复文档中已确认的 Markdown 格式问题，包括代码块格式错误和章节编号重复
- **所需技能**: 基本的 Markdown 语法知识
- **涉及模块**: `docs/zh/` 下多个文件
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 | 说明 |
  |---|------|------|----------|--------|------|
  | 1 | `docs/zh/user_guide/tracing_deployment.md` | 17 | ` ```json{ ` | ` ```json ` 后换行再写 `{` | 代码块开始标记后缺少换行 |
  | 2 | `docs/zh/developer_guide/docker_only/single_container_docker_only.md` | 24 | ` ```json{ ` | ` ```json ` 后换行再写 `{` | 同上 |
  | 3 | `docs/zh/developer_guide/docker_only/multi_container_docker_only.md` | 22 | ` ```json{ ` | ` ```json ` 后换行再写 `{` | 同上 |
  | 4 | `docs/zh/architecture.md` | 69 | `### 4. 周边组件` | `### 6. 周边组件` | 前面已有 1~5，此处编号重复为 4 |

- **完成标准**:
  1. 修正上述 4 处格式错误
  2. 检查修正后的 Markdown 渲染效果
  3. PR 通过 CI 检查
- **参考资源**: [Markdown 语法指南](https://www.markdownguide.org/)
- **预计耗时**: 0.5~1 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T05"

---

### [L0] T06: 修复文档中的空链接和错误链接

- **目标描述**: 修复文档中已确认的空链接（占位符未填写）和指向不存在文件的链接
- **所需技能**: Markdown 链接语法，项目文档结构了解
- **涉及模块**: `docs/zh/user_guide/`
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 |
  |---|------|------|----------|--------|
  | 1 | `docs/zh/user_guide/quick_start.md` | 11 | `[PD分离部署](https://gitcode.com/Ascend/MindIE-Motor/blob/master/docs/zh/user_guide/service_deployment/pd_separation_service_deployment.md)` | `[PD分离部署](./service_deployment/pd_disaggregation_deployment.md)`（链接文件名不存在） |
  | 2 | `docs/zh/user_guide/service_deployment/pd_disaggregation_deployment.md` | 64 | `[镜像获取地址]()` | 填入实际镜像获取地址 |
  | 3 | `docs/zh/user_guide/service_deployment/pd_disaggregation_deployment.md` | 69 | `[镜像获取地址]()` | 填入实际镜像获取地址 |
  | 4 | `docs/zh/user_guide/service_deployment/pd_disaggregation_deployment.md` | 543 | `[环境准备]()` | `[环境准备](../environment_preparation.md)` |
  | 5 | `docs/zh/user_guide/service_deployment/pd_disaggregation_deployment.md` | 675 | `[api接口介绍]()` | `[api接口介绍](../../api_reference/service_interface.md)` |

- **完成标准**:
  1. 修正上述 5 处链接问题
  2. 验证修正后的链接可正常跳转
  3. PR 通过 CI 检查
- **参考资源**: 项目 `docs/zh/` 目录结构
- **预计耗时**: 0.5~1 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T06"

---

### [L0] T07: 修复示例配置中的 TLS 字段名不一致和缺失问题

- **目标描述**: 修复示例配置文件与文档中 TLS 相关字段名不一致和缺失的问题
- **所需技能**: 基本的 JSON 语法知识，TLS/SSL 基础概念
- **涉及模块**: `examples/features/`
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 | 说明 |
  |---|------|------|----------|--------|------|
  | 1 | `examples/features/http/enable_tls/README.md` | 177 等 | `tls_crl` | `crl_file` | 与 `config_sample.json` 和代码白名单不一致 |
  | 2 | `examples/features/config_sample.json` | - | `tls_config` 中缺少 `north_tls_config` | 添加 `north_tls_config` 字段 | `observability/README.md` 和代码白名单中均需要此字段 |

- **完成标准**:
  1. 将 `enable_tls/README.md` 中所有 `tls_crl` 改为 `crl_file`
  2. 在 `config_sample.json` 的 `tls_config` 中添加 `north_tls_config` 字段
  3. PR 通过 CI 检查
- **参考资源**: `motor/common/http/cert_util.py`，`examples/features/config_sample.json`
- **预计耗时**: 0.5~1 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T07"

---

### [L0] T08: 修复示例配置中 env.json 的 OMP_PROC_BIND 类型不一致问题

- **目标描述**: 修复 env.json 配置文件中 `OMP_PROC_BIND` 字段在同一文件内类型不一致的问题（布尔值与字符串混用）
- **所需技能**: 基本的 JSON 语法知识
- **涉及模块**: `examples/infer_engines/vllm/models/`
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 | 说明 |
  |---|------|------|----------|--------|------|
  | 1 | `examples/infer_engines/vllm/models/deepseek/v3_1/env.json` | 12 | `"OMP_PROC_BIND": false` | `"OMP_PROC_BIND": "false"` | 环境变量应为字符串，布尔值 `false` 导出后变为 `"False"` |
  | 2 | `examples/infer_engines/vllm/models/qwen/3/30b/env.json` | 16 | `"OMP_PROC_BIND": false` | `"OMP_PROC_BIND": "false"` | 同上 |

- **完成标准**:
  1. 将上述 2 个文件中的 `OMP_PROC_BIND` 布尔值改为字符串
  2. 检查其他 env.json 文件是否有同类问题
  3. PR 通过 CI 检查
- **参考资源**: [JSON 数据类型](https://www.json.org/json-zh.html)
- **预计耗时**: 0.5 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T08"

---

### [L0] T09: 修复 deepseek/README.md 中的 JSON 示例问题

- **目标描述**: 修复 deepseek 模型 README 中 JSON 代码块包含 `//` 注释（不是合法 JSON）和缩进错误的问题
- **所需技能**: JSON 语法知识，Markdown 编辑能力
- **涉及模块**: `examples/infer_engines/vllm/models/deepseek/README.md`
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 |
  |---|------|------|----------|--------|
  | 1 | `examples/infer_engines/vllm/models/deepseek/README.md` | 257~266 | JSON 代码块中包含 `// Prefill 实例数` 等 `//` 注释 | 移除 JSON 代码块内的所有 `//` 注释，改用代码块外的 Markdown 表格说明 |
  | 2 | `examples/infer_engines/vllm/models/deepseek/README.md` | 207~209 | `"compilation_config"` 缩进比同级字段多了一级 | 调整缩进与同级字段一致 |

- **完成标准**:
  1. 移除 JSON 代码块中的 `//` 注释，在代码块外用表格或列表补充说明
  2. 修正缩进错误
  3. PR 通过 CI 检查
- **参考资源**: [JSON 语法规范](https://www.json.org/json-zh.html)
- **预计耗时**: 0.5~1 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T09"

---

### [L0] T10: 修复 Shell 脚本中的变量引用安全问题

- **目标描述**: 修复部署脚本中 Shell 变量未加双引号的问题，防止路径含空格时命令解析错误
- **所需技能**: 基本的 Shell/Bash 语法知识
- **涉及模块**: `examples/deployer/`
- **具体问题清单**:

  | # | 文件 | 行号 | 当前内容 | 修正为 |
  |---|------|------|----------|--------|
  | 1 | `examples/deployer/probe/probe.sh` | 27 | `python3 $CONFIGMAP_PATH/probe.py $role $probe_type` | `python3 "$CONFIGMAP_PATH/probe.py" "$role" "$probe_type"` |
  | 2 | `examples/deployer/startup/roles/all_combine_in_single_container.sh` | 41 | `--config $USER_CONFIG_PATH` | `--config "$USER_CONFIG_PATH"` |
  | 3 | `examples/deployer/startup/roles/controller.sh` | 22 | `--config $USER_CONFIG_PATH` | `--config "$USER_CONFIG_PATH"` |
  | 4 | `examples/deployer/startup/common.sh` | 206 | `export MOONCAKE_CONFIG_PATH=$CONFIG_PATH/kv_cache_pool_config.json` | `export MOONCAKE_CONFIG_PATH="$CONFIG_PATH/kv_cache_pool_config.json"` |
  | 5 | `examples/deployer/startup/common.sh` | 142 | `mkdir "$CONFIG_PATH" -p` | `mkdir -p "$CONFIG_PATH"`（选项应在路径前） |

- **完成标准**:
  1. 修正上述 5 处 Shell 变量引用问题
  2. 检查同目录下其他脚本是否有同类问题
  3. PR 通过 CI 检查
- **参考资源**: [Shell 变量引用最佳实践](https://www.shellcheck.net/)
- **预计耗时**: 0.5~1 小时
- **难度系数**: ⭐
- **认领方式**: 回复 "认领 T10"

---

## L1 级任务（轻量级任务）

> L1 任务需要基础 Python 编程能力，是代码贡献的起点。通过这些任务，你将熟悉项目代码风格、测试框架和开发流程。

---

### [L1] T11: 修复代码中的拼写错误

- **目标描述**: 修复项目源码中已知的拼写错误，包括变量名、注释和字符串中的错误
- **所需技能**: 基础 Python 编程能力，英语拼写能力
- **涉及模块**:
  - `motor/controller/core/instance_assembler.py`（`_start_commmand_sender` → `_start_command_sender`）
  - `motor/common/standby/standby_manager.py`（`stanyby_loop_thread` → `standby_loop_thread`，共 4 处）
  - `motor/node_manager/api_server/node_manager_api.py`（`"stated"` → `"started"`）
  - `motor/engine_server/core/vllm/vllm_config.py`（`"at least have"` → `"must have at least"`）
- **完成标准**:
  1. 修正上述所有拼写错误
  2. 确保修改后所有引用处同步更新
  3. 通过 `ruff check` 和项目测试
- **参考资源**: [Ruff Linter](https://docs.astral.sh/ruff/)，项目 `.pre-commit-config.yaml`
- **预计耗时**: 1~2 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T11"

---

### [L1] T12: 修正错误的 Docstring

- **目标描述**: 修复代码中与实际功能不符的 docstring，确保文档描述准确
- **所需技能**: 基础 Python 编程能力，代码阅读理解能力
- **涉及模块**:
  - `motor/common/resources/http_msg_spec.py` 第 97 行：`TerminateInstanceMsg` 的 docstring 写的是 "Heartbeat message"，应修正为 "Terminate instance message"
  - `motor/coordinator/scheduler/policy/kv_cache_affinity.py` 第 120 行：`TokenizerManager` 的 docstring 写的是 "Tracer Manager class"，应修正为 "Tokenizer Manager class"
- **完成标准**:
  1. 修正上述 2 处 docstring
  2. 检查同文件中其他 docstring 是否存在类似问题
  3. 通过 `ruff check` 检查
- **参考资源**: [Python Docstring 规范（PEP 257）](https://peps.python.org/pep-0257/)
- **预计耗时**: 1~2 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T12"

---

### [L1] T13: 为 motor/common/resources/instance.py 添加类型注解

- **目标描述**: 为 `Instance` 类中缺少返回类型注解的方法添加类型提示
- **所需技能**: Python 类型注解语法（Type Hints），基础 Python 编程能力
- **涉及模块**: `motor/common/resources/instance.py`
- **完成标准**:
  1. 为以下方法添加返回类型注解：`del_endpoints()` → `None`，`get_endpoints_num()` → `int`，`get_node_managers_num()` → `int`，`get_node_managers()` → `list`，`update_instance_status()` → `None`，`update_heartbeat()` → `None`
  2. 为 `Record.update_time()` 添加 `-> None`，`Record.format()` 添加 `-> dict`
  3. 通过 `ruff check` 和 `mypy`（如有配置）检查
  4. 不改变任何方法的行为逻辑
- **参考资源**: [Python Type Hints 指南](https://docs.python.org/3/library/typing.html)，项目中已有类型注解的代码作为风格参考
- **预计耗时**: 1~2 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T13"

---

### [L1] T14: 为 motor/common/utils/ 模块添加类型注解

- **目标描述**: 为 `motor/common/utils/` 下的工具类添加缺失的类型注解
- **所需技能**: Python 类型注解语法，理解 `property`、`__new__` 等特殊方法的类型标注
- **涉及模块**:
  - `motor/common/utils/singleton.py`：为 `ThreadSafeSingleton.__new__()` 添加返回类型
  - `motor/common/utils/env.py`：为 `Env` 类所有 property 添加返回类型注解（`str | None`）
  - `motor/common/utils/patch_check.py`：为 `safe_open()` 和 `PathCheck` 所有方法添加参数和返回类型注解
- **完成标准**:
  1. 为上述所有方法添加完整的类型注解
  2. 通过 `ruff check` 检查
  3. 不改变任何方法的行为逻辑
- **参考资源**: [Python Type Hints 指南](https://docs.python.org/3/library/typing.html)
- **预计耗时**: 2~3 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T14"

---

### [L1] T15: 为 motor/common/resources/instance.py 核心类添加 Docstring

- **目标描述**: 为 `instance.py` 中的枚举类和核心方法添加 docstring，提升代码可读性
- **所需技能**: Python 编程基础，代码阅读理解能力，技术文档写作能力
- **涉及模块**: `motor/common/resources/instance.py`
- **完成标准**:
  1. 为以下枚举类添加 docstring：`InsStatus`、`PDRole`、`InsConditionEvent`、`NodeManagerInfo`、`ParallelConfig`
  2. 为以下方法添加 docstring（含参数和返回值说明）：`add_node_mgr()`、`del_node_mgr()`、`has_node_mgr()`、`add_endpoints()`、`del_endpoints()`、`is_all_endpoints_alive()`、`is_all_endpoints_ready()`、`update_heartbeat()`
  3. Docstring 采用 Google 风格（与项目现有风格一致）
  4. 通过 `ruff check` 检查
- **参考资源**: [Google Style Python Docstrings](https://google.github.io/styleguide/pyguide.html#384-classes)，项目中已有 docstring 的代码作为风格参考
- **预计耗时**: 2~3 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T15"

---

### [L1] T16: 为 motor/common/resources/endpoint.py 添加 Docstring 和类型注解

- **目标描述**: 为 `endpoint.py` 中的枚举类和方法添加 docstring 和类型注解
- **所需技能**: Python 编程基础，代码阅读理解能力
- **涉及模块**: `motor/common/resources/endpoint.py`
- **完成标准**:
  1. 为 `WorkloadAction`、`DeviceInfo`、`EndpointStatus` 枚举类添加 docstring
  2. 为 `Endpoint.add_device()`、`Endpoint.del_device()`、`Endpoint.is_alive()` 添加 docstring
  3. 补充缺失的类型注解
  4. 通过 `ruff check` 检查
- **参考资源**: [Google Style Python Docstrings](https://google.github.io/styleguide/pyguide.html#384-classes)
- **预计耗时**: 1~2 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T16"

---

### [L1] T17: 为 motor/common/http/security_utils.py 编写单元测试

- **目标描述**: 为安全工具模块 `security_utils.py` 编写单元测试，覆盖敏感信息过滤和路径校验等核心功能
- **所需技能**: Python 编程能力，pytest 测试框架基础，了解 HTTP 安全概念
- **涉及模块**: `motor/common/http/security_utils.py`，`tests/common/`
- **完成标准**:
  1. 在 `tests/common/` 下创建 `test_security_utils.py`
  2. 测试覆盖 `filter_sensitive_headers()` 函数：验证 Authorization/Cookie 等敏感头被脱敏
  3. 测试覆盖路径校验函数：验证合法路径通过、非法路径被拒绝
  4. 测试覆盖 `log_audit_event()` 函数：验证审计日志正确生成
  5. 通过 `pytest tests/common/test_security_utils.py` 全部用例
- **参考资源**: 项目 `tests/` 目录下已有测试文件作为风格参考，[pytest 文档](https://docs.pytest.org/)
- **预计耗时**: 3~4 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T17"

---

### [L1] T18: 为 motor/common/utils/singleton.py 编写单元测试

- **目标描述**: 为单例模式工具类编写单元测试，验证线程安全和单例约束
- **所需技能**: Python 编程能力，pytest 基础，多线程编程基础
- **涉及模块**: `motor/common/utils/singleton.py`，`tests/common/`
- **完成标准**:
  1. 在 `tests/common/` 下创建 `test_singleton.py`
  2. 测试单例约束：同一类多次实例化返回同一对象
  3. 测试线程安全：多线程并发实例化仍保持单例
  4. 测试不同子类产生不同实例
  5. 通过 `pytest tests/common/test_singleton.py` 全部用例
- **参考资源**: 项目 `tests/common/` 下已有测试文件，[pytest 文档](https://docs.pytest.org/)
- **预计耗时**: 2~3 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T18"

---

### [L1] T19: 为 motor/common/resources/ 核心模型编写单元测试

- **目标描述**: 为 `instance.py` 和 `endpoint.py` 中的核心数据模型编写单元测试
- **所需技能**: Python 编程能力，pytest 基础，面向对象编程
- **涉及模块**: `motor/common/resources/instance.py`，`motor/common/resources/endpoint.py`，`tests/common/`
- **完成标准**:
  1. 在 `tests/common/` 下创建 `test_instance.py`
  2. 测试 `Instance` 类核心方法：`add_node_mgr()`、`del_node_mgr()`、`add_endpoints()`、`del_endpoints()`、`is_all_endpoints_alive()`、`is_all_endpoints_ready()`、`update_heartbeat()`
  3. 测试 `Instance` 状态转换逻辑
  4. 在 `tests/common/` 下创建 `test_endpoint.py`
  5. 测试 `Endpoint` 类核心方法：`add_device()`、`del_device()`、`is_alive()`
  6. 通过 `pytest tests/common/test_instance.py tests/common/test_endpoint.py` 全部用例
- **参考资源**: 项目 `tests/` 目录下已有测试文件，[pytest 文档](https://docs.pytest.org/)
- **预计耗时**: 4~6 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T19"

---

### [L1] T20: 改进错误消息的可操作性

- **目标描述**: 改进项目中的错误消息，使其包含更多上下文信息和解决建议，降低用户排查问题的难度
- **所需技能**: Python 编程基础，英语技术写作能力，错误处理设计
- **涉及模块**:
  - `motor/engine_server/utils/aicore.py`：环境变量未设置时提示如何设置
  - `motor/engine_server/core/vllm/vllm_endpoint.py`：engine_client 未找到时说明原因
  - `motor/common/http/cert_util.py`：SSL 权限错误时包含当前权限值
  - `motor/node_manager/core/daemon.py`：端点参数无效时说明哪些参数无效
- **完成标准**:
  1. 改进至少 5 处错误消息
  2. 每处改进包含：错误上下文（当前值/状态）、原因说明、解决建议
  3. 不改变错误处理的逻辑流程
  4. 通过 `ruff check` 和相关模块测试
- **参考资源**: [Python 异常设计最佳实践](https://docs.python.org/3/tutorial/errors.html)，项目中已有良好错误消息的代码作为参考
- **预计耗时**: 2~4 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T20"

---

### [L1] T21: 修正 logger_handler.py 中的 logging.error 调用错误

- **目标描述**: 修正 `logger_handler.py` 中多处 `logging.error()` 参数传递错误，确保异常信息正确输出
- **所需技能**: Python 编程基础，了解 Python logging 模块的格式化规则
- **涉及模块**: `motor/common/logger/logger_handler.py`
- **完成标准**:
  1. 修正第 103 行：`logging.error("Failed to compress %s", file_path, e)` → `logging.error("Failed to compress %s: %s", file_path, e)`
  2. 修正第 127 行：`logging.error("Failed to compress", e)` → `logging.error("Failed to compress: %s", e)`
  3. 修正第 143 行：`logging.error("Failed to cleanup", e)` → `logging.error("Failed to cleanup: %s", e)`
  4. 修正第 187 行：同第 103 行的问题
  5. 通过 `ruff check` 和相关测试
- **参考资源**: [Python logging 模块文档](https://docs.python.org/3/library/logging.html)，注意 logging 使用 `%` 格式化而非 f-string
- **预计耗时**: 1~2 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T21"

---

### [L1] T22: 为 motor/coordinator/models/ 编写单元测试

- **目标描述**: 为 Coordinator 的请求和响应模型编写单元测试
- **所需技能**: Python 编程能力，pytest 基础，Pydantic 模型基础
- **涉及模块**: `motor/coordinator/models/request.py`，`motor/coordinator/models/response.py`，`tests/coordinator/`
- **完成标准**:
  1. 在 `tests/coordinator/` 下创建 `test_request_models.py`
  2. 测试 `RequestType` 和 `ReqState` 枚举值
  3. 测试 `RequestInfo` 的状态转换方法：`update_state()`、`update_prompt_tokens_details()`、`set_cancel_scope()`
  4. 在 `tests/coordinator/` 下创建 `test_response_models.py`
  5. 测试 `RequestResponse` 和 `ErrorResponse` 的序列化/反序列化
  6. 通过全部测试用例
- **参考资源**: 项目 `tests/coordinator/` 下已有测试文件，[Pydantic 文档](https://docs.pydantic.dev/)
- **预计耗时**: 3~4 小时
- **难度系数**: ⭐⭐
- **认领方式**: 回复 "认领 T22"

---

## L2 级任务（联创特性&需求任务）

> L2 任务需要一定的专业知识和系统设计能力，适合有一定经验的贡献者。通过这些任务，你将深入理解项目架构，参与功能设计与实现。

---

### [L2] T23: 设计并实现限流配置示例

- **目标描述**: 为 Coordinator 的限流功能设计完整的配置示例，包括 JSON 配置文件和使用文档
- **所需技能**: Python 进阶能力，FastAPI 中间件理解，限流算法基础
- **涉及模块**: `motor/coordinator/middleware/rate_limiter.py`，`motor/coordinator/middleware/fastapi_middleware.py`，`examples/`
- **完成标准**:
  1. 在 `examples/features/` 下创建 `rate_limiting/` 目录
  2. 提供至少 2 种限流场景的 JSON 配置示例（全局限流、按路径限流）
  3. 编写 README.md 说明限流配置的字段含义和使用方法
  4. 编写简单的验证脚本或测试用例，证明配置可被正确加载
  5. 提交设计文档，说明限流策略的选择依据
- **参考资源**: `motor/coordinator/middleware/rate_limiter.py` 源码，`motor/coordinator/middleware/fastapi_middleware.py` 源码，[FastAPI 中间件文档](https://fastapi.tiangolo.com/tutorial/middleware/)
- **预计耗时**: 1~2 天
- **难度系数**: ⭐⭐⭐
- **认领方式**: 回复 "认领 T23"

---

### [L2] T24: 设计 TLS 双向认证完整配置示例

- **目标描述**: 为项目的 TLS 双向认证功能设计完整的端到端配置示例，覆盖证书生成、配置加载、服务启动全流程
- **所需技能**: TLS/SSL 协议理解，证书管理经验，Python 安全编程
- **涉及模块**: `motor/common/http/cert_util.py`，`motor/common/http/key_encryption.py`，`motor/config/tls.py`，`examples/features/http/tls/`
- **完成标准**:
  1. 完善 `examples/features/http/tls/` 目录下的配置示例
  2. 提供证书生成脚本（含 CA、服务端证书、客户端证书、CRL）
  3. 提供完整的 `user_config.json` TLS 配置示例
  4. 编写 README.md 说明 TLS 双向认证的配置步骤和注意事项
  5. 说明证书权限要求（700）和大小限制（10MB）等安全约束
- **参考资源**: `motor/common/http/cert_util.py` 源码，`examples/features/http/tls/` 现有示例，[OpenSSL 文档](https://www.openssl.org/docs/)
- **预计耗时**: 1~2 天
- **难度系数**: ⭐⭐⭐
- **认领方式**: 回复 "认领 T24"

---

### [L2] T25: 设计 KV Cache 亲和性调度配置示例与优化提案

- **目标描述**: 为 KV Cache 亲和性调度功能设计配置示例，并撰写优化提案文档
- **所需技能**: LLM 推理基础，KV Cache 原理理解，调度算法基础
- **涉及模块**: `motor/coordinator/scheduler/policy/kv_cache_affinity.py`，`motor/coordinator/scheduler/`，`examples/`
- **完成标准**:
  1. 在 `examples/features/` 下创建 `kv_cache_affinity/` 目录
  2. 提供 KV Cache 亲和性调度的 JSON 配置示例
  3. 编写 README.md 说明配置字段含义、适用场景和调优建议
  4. 撰写优化提案文档，分析当前调度策略的优缺点
  5. 提出至少 2 个优化方向及可行性分析
- **参考资源**: `motor/coordinator/scheduler/policy/kv_cache_affinity.py` 源码，`motor/coordinator/scheduler/policy/load_balance.py` 对比参考，[vLLM KV Cache 文档](https://docs.vllm.ai/)
- **预计耗时**: 2~3 天
- **难度系数**: ⭐⭐⭐
- **认领方式**: 回复 "认领 T25"

---

### [L2] T26: 设计主备模式配置示例与高可用方案文档

- **目标描述**: 为 Controller 主备模式设计完整配置示例，并撰写高可用方案文档
- **所需技能**: 分布式系统基础，etcd 选主机制理解，高可用设计经验
- **涉及模块**: `motor/common/standby/standby_manager.py`，`motor/controller/`，`examples/`
- **完成标准**:
  1. 在 `examples/features/` 下创建 `standby/` 目录
  2. 提供主备模式的完整配置示例（含 etcd 配置）
  3. 编写 README.md 说明主备切换流程和配置要点
  4. 撰写高可用方案文档，覆盖：选主机制、故障检测、切换流程、脑裂防护
  5. 分析当前实现的局限性并提出改进建议
- **参考资源**: `motor/common/standby/standby_manager.py` 源码，`motor/common/etcd/` 模块，[etcd 文档](https://etcd.io/docs/)
- **预计耗时**: 2~3 天
- **难度系数**: ⭐⭐⭐
- **认领方式**: 回复 "认领 T26"

---

### [L2] T27: 为 motor/common/alarm/ 告警模块编写单元测试

- **目标描述**: 为整个告警模块编写完整的单元测试，覆盖告警触发、清除、事件记录等核心流程
- **所需技能**: Python 进阶能力，pytest 进阶（mock、fixture），了解告警系统设计
- **涉及模块**: `motor/common/alarm/`（alarm.py, event.py, record.py, enums.py 及所有具体告警类），`tests/common/`
- **完成标准**:
  1. 在 `tests/common/` 下创建 `test_alarm/` 目录
  2. 为 `enums.py` 中所有枚举类编写值验证测试
  3. 为 `event.py` 编写事件创建和属性测试
  4. 为 `record.py` 编写记录生命周期测试（创建、更新、清除）
  5. 为 `alarm.py` 编写告警管理器测试（触发、清除、查询）
  6. 为至少 3 个具体告警类编写测试
  7. 通过 `pytest tests/common/test_alarm/` 全部用例
  8. 测试覆盖率达到 80% 以上
- **参考资源**: 项目 `tests/` 目录下已有测试文件，[pytest 文档](https://docs.pytest.org/)
- **预计耗时**: 1~2 天
- **难度系数**: ⭐⭐⭐
- **认领方式**: 回复 "认领 T27"

---

### [L2] T28: 设计并实现 Coordinator 请求追踪可视化方案

- **目标描述**: 基于 OpenTelemetry 追踪数据，设计并实现请求在 Coordinator 内部流转的可视化方案
- **所需技能**: Python 进阶能力，OpenTelemetry 基础，分布式追踪原理，数据可视化经验
- **涉及模块**: `motor/coordinator/tracer/`，`motor/coordinator/router/`，`motor/coordinator/scheduler/`
- **完成标准**:
  1. 撰写设计提案文档，分析当前追踪数据的结构和覆盖范围
  2. 设计可视化方案：数据采集 → 聚合 → 展示
  3. 实现一个最小可行的追踪数据导出工具（如导出为 Jaeger/Zipkin 兼容格式）
  4. 提供使用示例和配置说明
  5. 分析性能开销并提出优化建议
- **参考资源**: `motor/coordinator/tracer/` 源码，[OpenTelemetry Python 文档](https://opentelemetry.io/docs/instrumentation/python/)，[Jaeger 文档](https://www.jaegertracing.io/docs/)
- **预计耗时**: 2~3 天
- **难度系数**: ⭐⭐⭐
- **认领方式**: 回复 "认领 T28"

---

### [L2] T29: 设计 SGLang 引擎适配层增强方案

- **目标描述**: 分析当前 SGLang 引擎适配层的实现，设计增强方案以提升兼容性和可维护性
- **所需技能**: Python 进阶能力，LLM 推理引擎理解，设计模式应用
- **涉及模块**: `motor/engine_server/core/sglang/`，`motor/engine_server/core/vllm/`（对比参考），`motor/engine_server/factory/`
- **完成标准**:
  1. 撰写分析报告，对比 vLLM 和 SGLang 适配层的实现差异
  2. 识别 SGLang 适配层中的技术债务和改进空间
  3. 设计增强方案，包括：错误处理增强、配置校验完善、健康检查机制
  4. 提供方案实现的伪代码或原型
  5. 评估方案对现有功能的影响
- **参考资源**: `motor/engine_server/core/sglang/` 源码，`motor/engine_server/core/vllm/` 源码，`motor/engine_server/factory/` 源码，[SGLang 文档](https://github.com/sgl-project/sglang)
- **预计耗时**: 2~3 天
- **难度系数**: ⭐⭐⭐
- **认领方式**: 回复 "认领 T29"

---

### [L2] T30: 设计配置热更新机制增强方案

- **目标描述**: 分析当前配置热更新机制（`ConfigWatcher`）的实现，设计增强方案以支持更细粒度的配置更新和回滚
- **所需技能**: Python 进阶能力，配置管理经验，文件监控机制理解
- **涉及模块**: `motor/common/utils/config_watcher.py`，`motor/config/`，`motor/common/etcd/`
- **完成标准**:
  1. 撰写分析报告，梳理当前配置热更新的实现机制和限制
  2. 分析配置白名单机制的安全性和灵活性
  3. 设计增强方案：支持配置版本管理、灰度更新、自动回滚
  4. 评估 etcd 分布式配置与本地文件配置的协同方案
  5. 提供方案的原型实现或详细设计文档
- **参考资源**: `motor/common/utils/config_watcher.py` 源码，`motor/config/` 各配置类，`motor/common/etcd/` 模块，[watchdog 文档](https://python-watchdog.readthedocs.io/)
- **预计耗时**: 2~3 天
- **难度系数**: ⭐⭐⭐
- **认领方式**: 回复 "认领 T30"

---

## 学习路径推荐

### 路径一：文档修复入门（零代码，问题明确可直接执行）

```
T01（修复英文拼写）→ T02（修复中文用词）→ T03（修复配置键名）→ T05（修复 Markdown 格式）→ T06（修复空链接）→ T04（修复示例路径）→ T07（修复 TLS 配置）→ T08（修复 JSON 类型）→ T09（修复 JSON 示例）→ T10（修复 Shell 脚本）
```

### 路径二：代码贡献者（Python 入门）

```
T11（修复拼写）→ T12（修正 Docstring）→ T13/T14（添加类型注解）→ T15/T16（添加 Docstring）→ T21（修正 logging 调用）→ T20（改进错误消息）→ T18（编写单元测试）→ T17（安全工具测试）→ T19（核心模型测试）→ T22（模型测试）
```

### 路径三：架构探索者（进阶联创）

```
T23（限流配置）→ T24（TLS 配置）→ T25（KV Cache 方案）→ T26（高可用方案）→ T27（告警测试）→ T28（追踪可视化）→ T29（SGLang 增强）→ T30（配置热更新）
```

### 混合路径推荐

```
L0: T01 → T04 → T06
L1: T11 → T13 → T17 → T19
L2: T23 → T25 → T28
```

---

## 参考资源

### 社区新手任务池案例

| 项目 | 特色 | 链接 |
|------|------|------|
| PyTorch | `good first issue` 标签体系，贡献指南完善 | [pytorch/pytorch](https://github.com/pytorch/pytorch/contribute) |
| up-for-grabs.net | 专门的新手任务聚合平台 | [up-for-grabs.net](https://up-for-grabs.net/) |
| First Timers Only | 专为首次贡献者设计的任务 | [firsttimersonly.com](https://www.firsttimersonly.com/) |
| Good First Issue | CLI 工具快速查找新手任务 | [good-first-issue.dev](https://good-first-issue.dev/) |

### PyMotor 项目资源

| 资源 | 路径 |
|------|------|
| 项目说明 | [README.md](README.md) |
| 贡献指南 | [contributing.md](contributing.md) |
| 架构文档 | [docs/zh/architecture.md](docs/zh/architecture.md) |
| 快速入门 | [docs/zh/user_guide/quick_start.md](docs/zh/user_guide/quick_start.md) |
| 开发者指南 | [docs/zh/developer_guide/](docs/zh/developer_guide/) |
| 测试运行 | [tests/run_tests.sh](tests/run_tests.sh) |
| 构建脚本 | [build.sh](build.sh) |

### 技术学习资源

| 领域 | 推荐 |
|------|------|
| Python 类型注解 | [PEP 484](https://peps.python.org/pep-0484/) |
| Python Docstring | [PEP 257](https://peps.python.org/pep-0257/)，[Google Style Guide](https://google.github.io/styleguide/pyguide.html) |
| pytest 测试 | [pytest 官方文档](https://docs.pytest.org/) |
| FastAPI | [FastAPI 官方文档](https://fastapi.tiangolo.com/) |
| OpenTelemetry | [OTel Python 文档](https://opentelemetry.io/docs/instrumentation/python/) |
| etcd | [etcd 官方文档](https://etcd.io/docs/) |
| vLLM | [vLLM 文档](https://docs.vllm.ai/) |
| LLM 推理 | [KV Cache 优化综述](https://arxiv.org/abs/2406.07483) |

---

## 任务状态总览

| 编号 | 级别 | 任务标题 | 状态 | 认领人 |
|------|------|----------|------|--------|
| T01 | L0 | 修复文档中的拼写错误（第一批：uesr_config / moocake / histogramh） | 🟢 待认领 | - |
| T02 | L0 | 修复文档中的中文用词错误（显示→显式 / 已→以 / 相应→响应） | 🟢 待认领 | - |
| T03 | L0 | 修复文档中的配置键名拼写错误和大小写错误 | 🟢 待认领 | - |
| T04 | L0 | 修复示例目录中的文件名拼写错误和路径引用错误 | 🟢 待认领 | - |
| T05 | L0 | 修复文档中的 Markdown 格式错误 | 🟢 待认领 | - |
| T06 | L0 | 修复文档中的空链接和错误链接 | 🟢 待认领 | - |
| T07 | L0 | 修复示例配置中的 TLS 字段名不一致和缺失问题 | 🟢 待认领 | - |
| T08 | L0 | 修复示例配置中 env.json 的 OMP_PROC_BIND 类型不一致问题 | 🟢 待认领 | - |
| T09 | L0 | 修复 deepseek/README.md 中的 JSON 示例问题 | 🟢 待认领 | - |
| T10 | L0 | 修复 Shell 脚本中的变量引用安全问题 | 🟢 待认领 | - |
| T11 | L1 | 修复代码中的拼写错误 | 🟢 待认领 | - |
| T12 | L1 | 修正错误的 Docstring | 🟢 待认领 | - |
| T13 | L1 | 为 instance.py 添加类型注解 | 🟢 待认领 | - |
| T14 | L1 | 为 utils/ 模块添加类型注解 | 🟢 待认领 | - |
| T15 | L1 | 为 instance.py 核心类添加 Docstring | 🟢 待认领 | - |
| T16 | L1 | 为 endpoint.py 添加 Docstring 和类型注解 | 🟢 待认领 | - |
| T17 | L1 | 为 security_utils.py 编写单元测试 | 🟢 待认领 | - |
| T18 | L1 | 为 singleton.py 编写单元测试 | 🟢 待认领 | - |
| T19 | L1 | 为核心模型编写单元测试 | 🟢 待认领 | - |
| T20 | L1 | 改进错误消息的可操作性 | 🟢 待认领 | - |
| T21 | L1 | 修正 logger_handler.py 中的 logging.error 调用错误 | 🟢 待认领 | - |
| T22 | L1 | 为 coordinator/models/ 编写单元测试 | 🟢 待认领 | - |
| T23 | L2 | 设计并实现限流配置示例 | 🟢 待认领 | - |
| T24 | L2 | 设计 TLS 双向认证完整配置示例 | 🟢 待认领 | - |
| T25 | L2 | 设计 KV Cache 亲和性调度配置示例与优化提案 | 🟢 待认领 | - |
| T26 | L2 | 设计主备模式配置示例与高可用方案文档 | 🟢 待认领 | - |
| T27 | L2 | 为告警模块编写单元测试 | 🟢 待认领 | - |
| T28 | L2 | 设计并实现请求追踪可视化方案 | 🟢 待认领 | - |
| T29 | L2 | 设计 SGLang 引擎适配层增强方案 | 🟢 待认领 | - |
| T30 | L2 | 设计配置热更新机制增强方案 | 🟢 待认领 | - |

---

> 💡 **提示**: 如果你不确定从哪个任务开始，推荐从 **T01**（修复文档拼写错误）或 **T02**（修复中文用词错误）入手——每个 L0 任务都列出了具体的问题清单和修正方式，你可以直接逐项修复，无需自行发现问题。完成第一个任务后，你会对项目有更深入的理解，后续任务也会更加得心应手。
>
> 🤝 **需要帮助?** 在本 Issue 下留言，或参考 [contributing.md](contributing.md) 中的社区沟通渠道。我们期待你的贡献！
