# GLM 5.3 · A5 · W8A8C8 PD 分离

来源：Wiki《A5 性能基线复现指导（GLM5.3）》“1、W8A8C8 低时延、高吞吐”。该典配对应 1P1D：Prefill 使用 2 个 Pod、每 Pod 8 卡，DP1×TP8×PP2；Decode 使用 2 个 Pod、每 Pod 8 卡，DP16×TP1。

Motor 的 `hardware_type` 使用代码支持的 `Ascend950`。部署前填写镜像和模型权重路径；Prefill 与 Decode 的模型路径应指向同一份权重。

配置按提供的性能基线参数整理，未执行 A5 实机启动、精度或性能验证。
