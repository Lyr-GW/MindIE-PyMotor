# PD 实例按节点亲和部署操作指导

本文说明如何在 **multi_deployment** 模式下，通过 K8s 节点标签 `mindie-role`，将不同 P/D 实例的 engine Pod 固定调度到指定物理节点上。

## 1. 适用场景与前提

| 项目 | 说明 |
|------|------|
| 部署模式 | 必须使用 `motor_deploy_config.deploy_mode: "multi_deployment"`（默认 CRD 方式 `infer_service_set` 暂不支持按实例自动写入 `mindie-role`） |
| 功能开关 | `motor_deploy_config.enable_mindie_role_node_selector: true` |
| 集群准备 | 各目标节点已具备与 `hardware_type` 一致的标签（如 `accelerator-type: module-a3-16`），由 MindCluster 环境准备流程完成 |
| 节点命名 | `kubectl label` 使用 `kubectl get nodes` 输出中 **NAME 列的完整名称**（如 `node-97-36`），不是 IP 简写 |

## 2. 工作原理

1. 在物理节点上打标签：`mindie-role=prefill0` / `prefill1` / `decode0` 等。
2. `deploy.py` 为每个 P/D 实例生成独立 engine Deployment YAML（如 `vllm_p0.yaml`、`vllm_d0.yaml`）。
3. 当 `enable_mindie_role_node_selector` 为 `true` 时，自动在 `spec.template.spec.nodeSelector` 中写入：
   - P 实例 `index=N` → `mindie-role: prefillN`
   - D 实例 `index=N` → `mindie-role: decodeN`
4. 与原有 `accelerator-type` **并存**，不会覆盖硬件选择器。

无需在 `deploy.py` 执行后再手改 `output_yamls/`。

## 3. 配置示例

### 3.1 公共配置（motor_deploy_config）

```json
{
  "motor_deploy_config": {
    "deploy_mode": "multi_deployment",
    "enable_mindie_role_node_selector": true,
    "p_instances_num": 1,
    "d_instances_num": 1,
    "single_p_instance_pod_num": 1,
    "single_d_instance_pod_num": 1,
    "p_pod_npu_num": 16,
    "d_pod_npu_num": 16,
    "job_id": "mindie-motor",
    "hardware_type": "800I_A3",
    "image_name": "<你的镜像名>",
    "weight_mount_path": "/mnt/weight/"
  }
}
```

### 3.2 拓扑与标签对应关系

| 拓扑 | p_instances_num | d_instances_num | single_*_instance_pod_num | 最少节点数 | 标签示例 |
|------|-----------------|-----------------|---------------------------|------------|----------|
| 1P1D，每实例 1 机 | 1 | 1 | 均为 1 | 2 | `prefill0`、`decode0` |
| 2P1D，每实例 1 机 | 2 | 1 | 均为 1 | 3 | `prefill0`、`prefill1`、`decode0` |
| 2P2D，每实例 1 机 | 2 | 2 | 均为 1 | 4 | 依此类推 |

**规则**：P 实例序号从 0 开始对应 `prefill0`、`prefill1`…；D 实例对应 `decode0`、`decode1`…。每个实例若 `single_*_instance_pod_num > 1`，需保证该 `mindie-role` 下**有足够多台**已打相同标签的节点。

## 4. 操作步骤

### 4.1 查看节点

```bash
kubectl get nodes
```

示例：

```text
NAME         STATUS                     ROLES
node-97-36   Ready                      worker
node-97-37   Ready                      worker
node-97-40   Ready,SchedulingDisabled   control-plane,master,worker
node-97-42   Ready                      worker
```

- P/D engine 请打在 **Ready 且可调度** 的 worker 上（如 `node-97-36`、`node-97-37`、`node-97-42`）。
- `SchedulingDisabled` 的 master（如 `node-97-40`）**不要**作为 P/D 目标，否则 Pod 可能长期 Pending。

### 4.2 打节点标签

**1P1D 示例**（P0 → 36，D0 → 37）：

```bash
kubectl label node node-97-36 mindie-role=prefill0 --overwrite
kubectl label node node-97-37 mindie-role=decode0 --overwrite
```

**2P1D 示例**（P0 → 36，P1 → 37，D0 → 42）：

```bash
kubectl label node node-97-36 mindie-role=prefill0 --overwrite
kubectl label node node-97-37 mindie-role=prefill1 --overwrite
kubectl label node node-97-42 mindie-role=decode0 --overwrite
```

验证：

```bash
kubectl get nodes --show-labels | grep mindie-role
```

### 4.3 部署服务

在 `examples/deployer` 目录执行（按实际配置目录调整）：

```bash
cd examples/deployer
python3 deploy.py --config_dir ../infer_engines/vllm
```

`deploy.py` 会生成 YAML 到 `output_yamls/` 并自动 `kubectl apply`。生成的 engine 文件示例：

- `vllm_p0.yaml`、`vllm_p1.yaml`（P 实例）
- `vllm_d0.yaml`（D 实例）

其中 `nodeSelector` 应类似：

```yaml
nodeSelector:
  accelerator-type: module-a3-16
  mindie-role: prefill0
```

### 4.4 验证调度结果

将 `<job_id>` 换为 `user_config.json` 中的命名空间（如 `mindie-motor`）：

```bash
kubectl get pod -n <job_id> -owide
```

期望：每个 P/D engine Pod 的 **NODE** 列落在打了对应 `mindie-role` 的节点上。

排查 Pending：

```bash
kubectl describe pod <pod名> -n <job_id>
```

常见原因：节点无对应 `mindie-role`、无 `accelerator-type`、节点不可调度或 NPU 资源不足。

## 5. 对他人使用「原始拉起脚本」的影响

| 问题 | 结论 |
|------|------|
| 只打节点标签是否影响他人 | **一般不影响**。标签本身不禁止其他 Pod 调度到该节点。 |
| 何时会受影响 | 仅当对方的 Pod **也要求** `nodeSelector.mindie-role=xxx` 时（例如旧版 MindIE 脚本或手改 YAML）。 |
| 原始 deploy.py（未开开关） | 只匹配 `accelerator-type`，**不要求** `mindie-role`，仍可在任意满足硬件标签的节点调度。 |

## 6. 清除标签与关闭功能

### 6.1 删除节点上的 mindie-role 标签

键名后加 `-` 表示删除该标签：

```bash
kubectl label node node-97-36 mindie-role-
kubectl label node node-97-37 mindie-role-
kubectl label node node-97-42 mindie-role-
```

查看仍带该标签的节点：

```bash
kubectl get nodes -l mindie-role
```

### 6.2 关闭自动生成 nodeSelector

在 `user_config.json` 中设置：

```json
"enable_mindie_role_node_selector": false
```

或删除该字段（默认为不启用）。然后重新执行 `deploy.py`，新生成的 YAML 将不再包含 `mindie-role`。

> 已运行的 Deployment 需 `kubectl apply` 更新后才会去掉选择器；必要时删除旧 Pod 触发重建。

## 7. 常见问题

| 现象 | 处理建议 |
|------|----------|
| Pod 一直 Pending | 检查节点是否有匹配的 `mindie-role` 与 `accelerator-type`；`kubectl describe pod` 查看 Events |
| 再次 deploy 后绑节点失效 | 确认 `enable_mindie_role_node_selector` 仍为 `true`，且未回退为手改 `output_yamls` 又被覆盖 |
| 想临时改绑节点 | 修改节点标签或改 `user_config` 实例数后重新 `deploy.py`；勿只改本地 YAML 不 apply |
| master 节点 SchedulingDisabled | 不要给 master 打 P/D 用的 `mindie-role`；除非 `kubectl uncordon` 且确认可调度 |
| 切换 deploy_mode | 修改 `deploy_mode` 需先删除当前部署再全量部署，见 [部署模式指南](../deploy_mode_guide.md) |

## 8. 相关文档

- [PD 分离服务部署](./pd_disaggregation_deployment.md)
- [部署模式指南](../deploy_mode_guide.md)
- [user_config 配置参考](./config_reference.md)（`enable_mindie_role_node_selector` 字段说明）
- [deploy.py 使用说明](../../../examples/deployer/README.md)
