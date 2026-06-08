# MindIE-Motor 

> English | [中文](./OVERVIEW.zh.md)

## Quick Reference

- MindIE-Motor is maintained by the [MindIE community](https://www.hiascend.com/cn/developer/software/mindie)

- Where to get help

    - [MindIE Image Registry](https://www.hiascend.com/developer/ascendhub/detail/af85b724a7e5469ebd7ea13c3439d48f)
    - [MindIE-Motor Documentation](https://gitcode.com/Ascend/MindIE-PyMotor/blob/master/docs/zh/index.md)
    - [Atlas Developer Community](https://www.hiascend.com/developer)
    - [Report an Issue](https://gitcode.com/Ascend/MindIE-PyMotor/issues)

---

## MindIE-Motor

Provides one‑click PD-separated deployment, flexibly adapts to multiple inference engines (vLLM, SGLang) through a cloud‑native plug‑in architecture, and combines high‑performance scheduling with load balancing capabilities to build highly available, scalable large‑scale inference services.

---

## Supported Tags and Dockerfile Links

### Tag Specification

Tags follow the format:

```text
<MotorVersion>-<ProductSeries>-<PythonVersion>-<OperatingSystem>-<Architecture>
```

| Field | Example Value | Description |
|---|---|---|
| `MotorVersion` | `3.0.0` | Motor version number |
| `ProductSeries` | `800I-A2`, `800I-A3`, `300I-Duo` | Target Atlas product series |
| `OperatingSystem` | `ubuntu22.04`, `openeuler24.03` | Base operating system |
| `PythonVersion` | `py3.10`, `py3.11`, `py3.12` | Python version |
| `Architecture` | `x86_64`, `aarch64` | Architecture type |

### Image Registry Address

MindIE-Motor images are hosted on Huawei Cloud SWR:

```text
swr.cn-south-1.myhuaweicloud.com/
```

**Full image example:**

```text
swr.cn-south-1.myhuaweicloud.com/mindie-pymotor/mindie-pymotor:3.0.0-800I-A2-ubuntu22.04-py3.11
```

### Build Parameters

The build script reads the following environment variables (all optional, with
sensible defaults). Override them on the command line as needed.

| Variable | Description | Required | Default | Example Value |
|---|---|---|---|---|
| SYSTEM | Server OS and version | No | `Ubuntu24.04` | Ubuntu24.04 / openEuler24.03 |
| DEVICE | Atlas device model | No | `910` | 310 / 910 / A3 |
| ARCH | System architecture | No | `$(uname -m)` | x86_64 / aarch64 |
| PYMOTOR_VERSION | MindIE-PyMotor version number | No | `0.1.0` | 0.1.0 |
| VLLM_ASCEND_VERSION | vllm-ascend base image version/branch | No | `main` | v0.13.0 / main / v0.14.0rc1 / releases-v0.13.0 |
| IMAGE_VERSION | Version tag for the final built image | No | `${PYMOTOR_VERSION}` | v1.0.0 |

---

## Quick Start

### Prerequisites (Optional)

#### Install Drivers

- Firmware and drivers have been installed on the host. Refer to [Install Drivers and Firmware](https://www.hiascend.com/document/detail/zh/mindie/100/envdeployment/instg/mindie_instg_0006.html) for details.
- Docker is installed on the host.

---

### Build MindIE-Motor Image

The image is built directly from the local repository: `docker/Dockerfile`
takes care of installing Python dependencies, compiling the wheel via
`build.sh`, and installing it into the base image.

A ready-to-use helper script is provided at `docker/build_image.sh`. From the
**repository root** simply run:

```bash
# Default: Ubuntu24.04 / 910b / vllm-ascend tag "main"
bash docker/build_image.sh

# Override defaults via environment variables
SYSTEM=openEuler24.03 DEVICE=910c VLLM_ASCEND_VERSION=v0.13.0 \
    bash docker/build_image.sh
```

The script's contents are reproduced below for reference:

```sh
#!/bin/bash
# Build a MindIE-PyMotor image from the local source tree.
# Run from the repository root:
#   bash docker/build_image.sh
# Override defaults via environment variables, e.g.:
#   SYSTEM=openEuler24.03 DEVICE=910c VLLM_ASCEND_VERSION=v0.13.0 \
#       bash docker/build_image.sh
set -euo pipefail

SYSTEM=${SYSTEM:-Ubuntu24.04}                       # Ubuntu24.04 / openEuler24.03
DEVICE=${DEVICE:-910b}                              # 310p / 910b / 910c
ARCH=${ARCH:-$(uname -m)}                           # x86_64 / aarch64
PYMOTOR_VERSION=${PYMOTOR_VERSION:-0.1.0}           # MindIE-PyMotor version
VLLM_ASCEND_VERSION=${VLLM_ASCEND_VERSION:-main}    # vllm-ascend base image tag prefix
IMAGE_VERSION=${IMAGE_VERSION:-${PYMOTOR_VERSION}}  # Tag of the produced image

case "${DEVICE}" in
    310p) PRODUCT=300I-Duo ;;
    910b) PRODUCT=800I-A2 ;;
    910c) PRODUCT=800I-A3 ;;
    *) echo "Unsupported DEVICE: ${DEVICE}" >&2; exit 1 ;;
esac

case "${SYSTEM}_${DEVICE}" in
    Ubuntu24.04_310p)    BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-310p ;;
    openEuler24.03_310p) BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-310p-openeuler ;;
    Ubuntu24.04_910b)    BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION} ;;
    openEuler24.03_910b) BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-openeuler ;;
    Ubuntu24.04_910c)    BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-a3 ;;
    openEuler24.03_910c) BASE_IMAGE_TAG=${VLLM_ASCEND_VERSION}-a3-openeuler ;;
    *) echo "Unsupported SYSTEM/DEVICE combo: ${SYSTEM}/${DEVICE}" >&2; exit 1 ;;
esac

IMAGE_TAG="mindie-pymotor:${IMAGE_VERSION}-${PRODUCT}-py3.11-${SYSTEM}-${ARCH}"

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "${PROJECT_ROOT}"

echo "Building ${IMAGE_TAG} from quay.nju.edu.cn/ascend/vllm-ascend:${BASE_IMAGE_TAG} ..."
docker build \
    --network=host \
    --build-arg "BASE_IMAGE_TAG=${BASE_IMAGE_TAG}" \
    -t "${IMAGE_TAG}" \
    -f docker/Dockerfile \
    .

echo "Done. Image tag: ${IMAGE_TAG}"
```

What the build does, in order:

1. Pull the base image `quay.nju.edu.cn/ascend/vllm-ascend:${BASE_IMAGE_TAG}`.
2. Copy the current source tree into `/opt/MindIE-PyMotor` inside the image.
3. Inside the image, run:

    ```bash
    pip install -r requirements.txt
    bash build.sh
    cd dist && pip install motor*.whl --force-reinstall
    ```

4. Then build and install the `ccae_reporter` helper from
   `examples/features/observability/`, which lets the image integrate with
   the CCAE cluster autonomous engine:

    ```bash
    cd examples/features/observability
    pip install -r requirements.txt
    bash build.sh
    pip install --force-reinstall dist/ccae_reporter-*.whl
    ```

### Run MindIE-Motor Container

### How to Extend

```bash
# Use MindIE-PyMotor image as base, add user software
FROM quay.io/ascend/mindie-pymotor:3.0.0-800I-A2-ubuntu22.04-py3.11

RUN apt update -y && \
    apt install gcc ...

...
```

---

## Supported Hardware

| Chip Series | Product Example | Architecture |
|---|---|---|
| Atlas 910 | Atlas 800T A2, Atlas 900 A2 PoD | ARM64 / x86_64 |
| Atlas A3 | Atlas 800T A3 | ARM64 / x86_64 |
| Atlas 310 | Atlas 300I Pro, Atlas 300V Pro | ARM64 / x86_64 |

---

## Image Version Notes

| Image Version | Description | Notes |
| - | - | - |
| 3.0.0 | MindIE 3.0.0 Release | 2026/5/6: Initial release |
| 3.0.0b2 | MindIE 3.0.0 Beta2 | 2026/4/21: Initial release; MindIE Atlas 300I DUO hardware supports dynamic LoRA load/unload, per-tensor loading, and Qwen3-VL 8B/30B-A3B models |
| 2.3.1 | MindIE 2.3.1 patch release | 2026/4/16: Initial release; fixes DSv3.1 w8a8c8 BFCL-multiturn accuracy degradation, request nesting layer limit of 10 layers, and related issues |
| 2.3.0 | MindIE 2.3.0 commercial release | 2026/1/18: Initial release |
| 2.2.RC1 | MindIE 2.2 release candidate | 2025/12/31: ras-restart script optimization; 2025/11/21: Initial release |
| 2.2.T32 | DeepSeek-V3.2 performance optimization | 2025/12/05: Performance optimization; for DSv3.2 trial only, not recommended for other models. Guide: https://www.hiascend.com/forum/thread-0278200283718182227-1-1.html |
| 2.1.RC2 | MindIE 2.1 patch release | 2025/9/21: Initial release |
| 2.1.RC1 | MindIE 2.1 release candidate | 2025/8/15: Default transformers version upgraded to 4.51.0 |
| 2.0.RC2 | MindIE 2.0 release candidate |  |
| 1.0.0 | MindIE 1.0 official release |  |

## License

See the [license information of Motor](https://gitcode.com/Ascend/MindIE-PyMotor/blob/master/LICENSE.md) included in these images.

As with all container images, pre‑installed software packages (Python, system libraries, etc.) may be subject to their own licenses.
