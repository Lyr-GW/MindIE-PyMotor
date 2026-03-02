# PyMotor

## 🔥Latest News

[2026/1] PyMotor正式开源。

## 🚀简介

PyMotor是面向通用模型场景的推理服务化框架，通过开放、可扩展的推理服务化平台架构提供推理服务化能力，支持对接业界主流推理框架接口，满足大语言模型的高性能推理需求。

PyMotor的组件包括Controller、Coordinator、NodeManger、EngineServer，通过对接业界主流推理加速引擎带来大模型在昇腾环境中的性能提升，并逐渐以高性能和易用性提升用户使用昇腾设备进行推理的便利性和可靠性。

**PyMotor 是面向通用模型场景的推理服务化框架，通过开放、可扩展的推理服务化平台架构提供推理服务化能力，支持对接业界主流推理框架接口，满足大语言模型的高性能推理需求**。

PyMotor 的组件包括：

- Controller：提供实例管理和RAS能力。
- Coordinator：提供推理请求调度能力
- NodeManger：提供实例信息收集上报能力。
- EngineServer：通过对推理加速引擎的包装，对上层服务屏蔽不同引擎的差异。

## 🔍目录结构

| 目录结构 | 说明 |
| --- | --- |
| deployer | 部署脚本目录，里面存放一键拉起PD分离部署的脚本程序 |
| docs | 特性文档 |
| motor | 业务程序主目录，pyMotor程序各个模块的根目录 |
| patch | 补丁目录，用于存放解决社区尚未解决的问题的补丁代码目录 |
| scripts | 脚本目录，用于存放编译过程或测试运行过程的一些公共逻辑的脚本 |
| README.md | 项目说明文档 |
| build.sh | 编译入口脚本 |
| pytest.ini | pytest的配置文件 |
| requirements.txt | 项目依赖说明 |
| setup.py | 编译过程中执行的逻辑代码 |
| contributing.md | 贡献指南 |
| security.md | 安全声明 |
| LICENSE.md | LICENSE |

## ⚡️版本说明

|vLLM软件版本|vLLM Ascend版本兼容性|
|:---|:---|
|0.13.0|0.13.0|

## ⚡️环境部署

PyMotor安装前的相关软硬件环境准备，以及安装步骤，请参见[安装指南](./docs/zh/user_guide/installation_guide.md)。

## ⚡️快速入门

快速体验启动服务、接口调用、精度&性能测试和停止服务全流程，请参见[快速入门](./docs/zh/user_guide/quick_start.md)。

## 📝学习文档

- [集群服务部署](./docs/zh/user_guide/service_deployment/)：介绍PyMotor集群服务部署方式，包括单机（非分布式）服务部署和PD分离单、多机服务部署。
- [集群管理组件](./docs/zh/user_guide/cluster_management_component/)：介绍PyMotor集群管理组件，包括Controller和Coordinator。
- [服务化接口](./docs/zh/user_guide/service_oriented_interface/)：介绍PyMotor提供的用户侧接口和集群内通信接口。
- [配套工具](./docs/zh/user_guide/service_oriented_optimization_tool.md)：介绍PyMotor提供的配套工具，包括性能/精度测试工具、PyMotor探针工具。

## 📝免责声明

版权所有© 2026 PyMotor Project.

您对"本文档"的复制、使用、修改及分发受知识共享（Creative Commmons）署名——相同方式共享4.0国际公共许可协议（以下简称"CC BY-SA 4.0"）的约束。为了方便用户理解，您可以通过访问https://creativecommons.org/licenses/by-sa/4.0/了解CC BY-SA 4.0的概要（但不是替代）。CC BY-SA 4.0的完整协议内容您可以访问如下网址获取：https://creativecommons.org/licenses/by-sa/4.0/legalcode。

## 📝贡献指南

1. 提交错误报错：如果您在PyMotor中发现了一个不存在安全问题的漏洞，请在PyMotor仓库中的Issues中搜索，以防该漏洞被重复提交，如果找不到漏洞可以创建一个新的Issues。如果发现了一个安全问题请不要将其公开，请参阅安全问题处理方式。提交错误报告时应该包含完整信息。
2. 安全问题处理：本项目中对安全问题处理的形式，请通过邮箱通知项目核心人员确认编辑。
3. 解决现有问题：通过查看仓库的Issues列表可以发现需要处理的问题信息，可以尝试解决其中的某个问题。
4. 如何提供新功能：请使用Issues的Feature标签进行标记，我们会定期处理和确认开发。
5. 开始贡献：
   1. Fork本项目的仓库。
   2. Clone到本地。
   3. 创建开发分支。
   4. 本地测试：提交前请通过所有单元测试，包括新增的测试用例。
   5. 提交代码。
   6. 新建Pull Request。
   7. 代码检视：您需要根据评审意见修改代码，并重新提交更新。此流程可能涉及多轮迭代。
   8. 当您的PR获得足够数量的检视者批准后，Committer会进行最终审核。
   9. 审核和测试通过后，CI会将您的PR合并到项目的主干分支。

更多贡献相关文档请参见[贡献指南](./contributing.md)。

## 📝相关信息

- [安全声明](./security.md)
- [LICENSE](./LICENSE.md)
