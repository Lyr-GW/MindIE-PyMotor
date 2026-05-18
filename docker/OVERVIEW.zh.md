# MindIE-Motor 

> [English](./OVERVIEW.md) | 中文

## 快速参考

- MindIE-Motor 由 [MindIE community](https://www.hiascend.com/cn/developer/software/mindie) 维护

- 从哪里获取帮助

    - [MindIE 镜像仓库](https://www.hiascend.com/developer/ascendhub/detail/af85b724a7e5469ebd7ea13c3439d48f)
    - [MindIE-Motor 文档](https://gitcode.com/Ascend/MindIE-PyMotor/blob/master/docs/zh/index.md)
    - [昇腾开发者社区](https://www.hiascend.com/developer)
    - [问题反馈](https://gitcode.com/Ascend/MindIE-PyMotor/issues)

---

## MindIE-Motor

提供一键式 PD 分离部署，基于云原生插件化架构灵活适配多种推理引擎（vLLM、SGLang），结合高性能调度与负载均衡能力，构建高可用、可扩展的大规模推理服务。

---

## 支持的 Tags 及 Dockerfile 链接

### Tag 规范

Tag 遵循以下格式：

```text
<Motor版本>-<产品系列>-<python版本>-<操作系统>-<架构类型>
```

| 字段 | 示例值 | 说明 |
|---|---|---|
| `Motor版本` | `3.0.0` | Motor 版本号 |
| `产品系列` | `800I-A2`、`800I-A3`、`300I-Duo` | 目标昇腾产品系列 |
| `操作系统` | `ubuntu22.04`、`openeuler24.03` | 基础操作系统 |
| `python版本` | `py3.10`、`py3.11`、`py3.12` | Python 版本 |
| `架构类型` | `x86_64`、`aarch64` | 架构类型 |

### 镜像仓库地址

MindIE-Motor 镜像托管在华为云 SWR 镜像仓库：

```text
swr.cn-south-1.myhuaweicloud.com/
```

**完整镜像示例：**

```text
swr.cn-south-1.myhuaweicloud.com/mindie-pymotor/mindie-pymotor:3.0.0-800I-A2-ubuntu22.04-py3.11
```

### 构建参数

构建脚本通过环境变量读取以下参数，全部为可选项（均带有默认值），按需在命令行
覆盖即可。

| 变量 | 说明 | 是否必填 | 默认值 | 示例值 |
|------|------|----------|--------|--------|
| SYSTEM | 服务器操作系统及版本 | 否 | `Ubuntu24.04` | Ubuntu24.04 / openEuler24.03 |
| DEVICE | 昇腾设备型号 | 否 | `910b` | 310p / 910b / A3 |
| ARCH | 系统架构 | 否 | `$(uname -m)` | x86_64 / aarch64 |
| PYMOTOR_VERSION | MindIE-PyMotor 版本号 | 否 | `0.1.0` | 0.1.0 |
| VLLM_ASCEND_VERSION | vllm-ascend 基础镜像版本/分支 | 否 | `main` | v0.13.0 / main / v0.14.0rc1 / releases-v0.13.0 |
| IMAGE_VERSION | 最终构建镜像的版本标识 | 否 | `${PYMOTOR_VERSION}` | v1.0.0 |

---

## 快速开始

### 前置要求（可选）

#### 安装驱动

- 宿主机上已经安装好固件与驱动，具体可参考[安装驱动和固件](https://www.hiascend.com/document/detail/zh/mindie/100/envdeployment/instg/mindie_instg_0006.html)。
- 宿主机上已经安装好Docker。

---

### 构建 MindIE-Motor 镜像

镜像直接基于本地仓库源码构建：`docker/Dockerfile` 会负责安装 Python 依赖、调用
`build.sh` 编译 wheel 包，并把它安装到基础镜像中。

仓库已经提供好封装脚本 `docker/build_image.sh`，在 **仓库根目录** 直接执行即可：

```bash
# 默认参数：Ubuntu24.04 / 910b / vllm-ascend tag "main"
bash docker/build_image.sh

# 通过环境变量覆盖默认值
SYSTEM=openEuler24.03 DEVICE=A3 VLLM_ASCEND_VERSION=v0.13.0 \
    bash docker/build_image.sh
```

脚本内容如下，供参考：

```sh
#!/bin/bash
# 基于本地源码构建 MindIE-PyMotor 镜像。
# 在仓库根目录执行：
#   bash docker/build_image.sh
# 通过环境变量覆盖默认值，例如：
#   SYSTEM=openEuler24.03 DEVICE=A3 VLLM_ASCEND_VERSION=v0.13.0 \
#       bash docker/build_image.sh
set -euo pipefail

SYSTEM=${SYSTEM:-Ubuntu24.04}                       # Ubuntu24.04 / openEuler24.03
DEVICE=${DEVICE:-910b}                              # 310p / 910b / A3
ARCH=${ARCH:-$(uname -m)}                           # x86_64 / aarch64
PYMOTOR_VERSION=${PYMOTOR_VERSION:-0.1.0}           # MindIE-PyMotor 版本号
VLLM_ASCEND_VERSION=${VLLM_ASCEND_VERSION:-main}    # vllm-ascend 基础镜像 tag 前缀
IMAGE_VERSION=${IMAGE_VERSION:-${PYMOTOR_VERSION}}  # 产物镜像的版本标识

case "${DEVICE}" in
    310p) PRODUCT=300I-Duo ;;
    910b) PRODUCT=800I-A2 ;;
    A3)   PRODUCT=800I-A3 ;;
    *) echo "不支持的 DEVICE: ${DEVICE}" >&2; exit 1 ;;
esac

case "${SYSTEM}_${DEVICE}" in
    Ubuntu24.04_310p)    BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-310p ;;
    openEuler24.03_310p) BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-310p-openeuler ;;
    Ubuntu24.04_910b)    BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION} ;;
    openEuler24.03_910b) BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-openeuler ;;
    Ubuntu24.04_A3)      BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-a3 ;;
    openEuler24.03_A3)   BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-a3-openeuler ;;
    *) echo "不支持的 SYSTEM/DEVICE 组合: ${SYSTEM}/${DEVICE}" >&2; exit 1 ;;
esac

IMAGE_TAG="mindie-pymotor:${IMAGE_VERSION}-${PRODUCT}-py3.11-${SYSTEM}-${ARCH}"

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "${PROJECT_ROOT}"

echo "正在基于 quay.nju.edu.cn/ascend/vllm-ascend:${BASE_IMAGE_TAG} 构建 ${IMAGE_TAG} ..."
docker build \
    --network=host \
    --build-arg "BASE_IMAGE_TAG=${BASE_IMAGE_TAG}" \
    -t "${IMAGE_TAG}" \
    -f docker/Dockerfile \
    .

echo "构建完成，镜像 tag: ${IMAGE_TAG}"
```

构建过程依次完成：

1. 拉取基础镜像 `quay.nju.edu.cn/ascend/vllm-ascend:${BASE_IMAGE_TAG}`。
2. 把当前源码复制到镜像内的 `/opt/MindIE-PyMotor`。
3. 在镜像中执行：

    ```bash
    pip install -r requirements.txt
    bash build.sh
    cd dist && pip install motor*.whl --force-reinstall
    ```

4. 接着编译并安装 `examples/features/observability/` 下的 `ccae_reporter` 组件，
   使镜像具备对接 CCAE 集群自智引擎的能力：

    ```bash
    cd examples/features/observability
    pip install -r requirements.txt
    bash build.sh
    pip install --force-reinstall dist/ccae_reporter-*.whl
    ```

### 运行 MindIE-Motor 容器

### 如何二次开发

```bash
# 以 MindIE-PyMotor 镜像为基础镜像，叠加用户软件
FROM quay.io/ascend/mindie-pymotor:3.0.0-800I-A2-ubuntu22.04-py3.11

RUN apt update -y && \
    apt install gcc ...

...
```

---

## 支持的硬件

| 芯片系列 | 产品示例 | 架构 |
|---|---|---|
| 昇腾 910B | Atlas 800T A2、Atlas 900 A2 PoD | ARM64 / x86_64 |
| 昇腾 A3 | Atlas 800T A3 | ARM64 / x86_64 |
| 昇腾 310P | Atlas 300I Pro、Atlas 300V Pro | ARM64 / x86_64 |

---

## 镜像版本说明

| 镜像版本 | 说明 | 备注 |
| - | - | - |
| 3.0.0 | MindIE 3.0.0 Release版本 | 2026/5/6：首次发布 |
| 3.0.0b2 | MindIE 3.0.0 Beta2版本 |  2026/4/21：首次发布，MindIE Atlas 300IDUO硬件支持动态加载、卸载Lora，支持逐Tensor加载，支持Qwen3-VL 8B/30B-A3B模型 |
| 2.3.1 | MindIE 2.3.1 补丁版本 | 2026/4/16：首次发布，解决DSv3.1 w8a8c8测试BFCL-multiturn精度劣化、请求嵌套层限制10层等问题|
| 2.3.0 | MindIE 2.3.0 商用版本 | 2026/1/18：首次发布|
| 2.2.RC1 | MindIE 2.2 候选版本 | 2025/12/31：ras-restart脚本优化；2025/11/21：首次发布|
| 2.2.T32 | DeepSeek-V3.2性能优化 | 2025/12/05：性能优化，仅供DSv3.2尝鲜，不建议运行其他模型。指导文档 https://www.hiascend.com/forum/thread-0278200283718182227-1-1.html|
| 2.1.RC2 | MindIE 2.1 补丁版本 | 2025/9/21：首次发布|
| 2.1.RC1 | MindIE 2.1 候选版本 | 2025/8/15：transformers版本默认升级至4.51.0 |
| 2.0.RC2 | MindIE 2.0 候选版本 |  |
| 1.0.0 | MindIE 1.0 正式版本 | |

## 许可证

查看这些镜像中包含的 Motor 的[许可证信息](https://gitcode.com/Ascend/MindIE-PyMotor/blob/master/LICENSE.md)。

与所有容器镜像一样，预装软件包（Python、系统库等）可能受其自身许可证约束。
