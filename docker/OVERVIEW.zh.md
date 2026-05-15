# MindIE-PyMotor 

> [English](./OVERVIEW.md) | 中文

## 快速参考

- MindIE-PyMotor 由 [MindIE community](https://www.hiascend.com/cn/developer/software/mindie) 维护

- 从哪里获取帮助

    - [MindIE 镜像仓库](https://www.hiascend.com/developer/ascendhub/detail/af85b724a7e5469ebd7ea13c3439d48f)
    - [MindIE-PyMotor 文档](https://gitcode.com/Ascend/MindIE-PyMotor/blob/master/docs/zh/index.md)
    - [昇腾开发者社区](https://www.hiascend.com/developer)
    - [问题反馈](https://gitcode.com/Ascend/MindIE-PyMotor/issues)

---

## MindIE-PyMotor

提供一键式 PD 分离部署，基于云原生插件化架构灵活适配多种推理引擎（vLLM、SGLang），结合高性能调度与负载均衡能力，构建高可用、可扩展的大规模推理服务。

---

## 支持的 Tags 及 Dockerfile 链接

### Tag 规范

Tag 遵循以下格式：

```
<PyMotor版本>-<产品系列>-<python版本>-<操作系统>-<架构类型>
```

| 字段 | 示例值 | 说明 |
|---|---|---|
| `PyMotor版本` | `3.0.0` | PyMotor 版本号 |
| `产品系列` | `800I-A2`、`800I-A3`、`300I-Duo` | 目标昇腾产品系列 |
| `操作系统` | `ubuntu22.04`、`openeuler24.03` | 基础操作系统 |
| `python版本` | `py3.10`、`py3.11`、`py3.12` | Python 版本 |
| `架构类型` | `x86_64`、`aarch64` | 架构类型 |

### 镜像仓库地址

MindIE-PyMotor 镜像托管在华为云 SWR 镜像仓库：

```text
swr.cn-south-1.myhuaweicloud.com/
```

**完整镜像示例：**

```text
swr.cn-south-1.myhuaweicloud.com/mindie-pymotor/mindie-pymotor:3.0.0-800I-A2-ubuntu22.04-py3.11
```



### 构建参数

| 参数 | 说明 | 必填 | 参考来源 | 示例值 |
|------|------|------|----------|--------|
| SYSTEM | 服务器操作系统及版本 | 是 | 脚本参数 `$1` | Ubuntu24.04 / openEuler24.03 |
| DEVICE | 昇腾设备型号 | 是 | 脚本参数 `$2` | 310p / 910b / A3 |
| ARCH | 系统架构 | 是 | 脚本参数 `$3` | x86_64 / aarch64 |
| PYMOTOR_VERSION | MindIE-PyMotor 版本号 | 是 | 脚本参数 `$4` | 0.1.0 |
| PYMOTOR_BRANCH | PyMotor 代码分支 | 是 | 脚本参数 `$5` | master |
| VLLM_ASCEND_VERSION | vllm-ascend 基础镜像版本/分支 | 是 | 脚本参数 `$6` | v0.13.0 / main / v0.14.0rc1 / releases-v0.13.0 |
| IMAGE_VERSION | 最终构建镜像的版本标识 | 是 | 脚本参数 `$7` | v1.0.0 |
| AK | 华为云 OBS Access Key | 是 | 脚本参数 `$8` | 实际 AK 字符串 |
| SK | 华为云 OBS Secret Key | 是 | 脚本参数 `$9` | 实际 SK 字符串 |
| PYMOTOR_DIR | PyMotor 编译结果的具体日期目录（可选，默认使用最新） | 否 | 脚本参数 `${10}` | 20260114.1 |
| WORKSPACE | CI 工作空间根路径 | 是 | 环境变量 | /opt/workspace |
| BUILDNUMBER | CI 构建编号 | 是 | 环境变量 | 100 |

---

## 快速开始

### 前置要求（可选）

#### 安装驱动

- 宿主机上已经安装好固件与驱动，具体可参考[安装驱动和固件](https://www.hiascend.com/document/detail/zh/mindie/100/envdeployment/instg/mindie_instg_0006.html)。
- 宿主机上已经安装好Docker。

---

### 构建 MindIE-PyMotor 镜像

```sh
#!/bin/bash
current_date=$(date -d "now" +"%Y%m%d")
SYSTEM=$1 #Ubuntu24.04/openEuler24.03
DEVICE=$2 #310p/910b/A3
ARCH=$3 #x86_64/aarch64
PYMOTOR_VERSION=$4 #0.1.0
PYMOTOR_BRANCH=$5 #master
VLLM_ASCEND_VERSION=$6 #v0.13.0/main/v0.14.0rc1/releases-v0.13.0
IMAGE_VERSION=$7
AK=$8
SK=$9
PYMOTOR_DIR=${10}
SYSTEM_LOWER=$(echo "${SYSTEM}" | sed 's/[0-9.]//g' | tr '[:upper:]' '[:lower:]')
case $DEVICE in
  "310p")
    IMAGES_TAG=mindie-motor-vllm:${IMAGE_VERSION}-300I-Duo-py3.11-${SYSTEM}-lts-${ARCH}
        case $SYSTEM in
            Ubuntu24.04)
                IMAGES_BASE_TAG=${VLLM_ASCEND_VERSION}-310p
                ;;
            openEuler24.03)
                IMAGES_BASE_TAG=${VLLM_ASCEND_VERSION}-310p-openeuler
                ;;
            *)
                echo "不支持的服务器操作系统"
                ;;
        esac
    ;;
  "910b")
    IMAGES_TAG=mindie-motor-vllm:${IMAGE_VERSION}-800I-A2-py3.11-${SYSTEM}-lts-${ARCH}
        case $SYSTEM in
            Ubuntu24.04)
                IMAGES_BASE_TAG=${VLLM_ASCEND_VERSION}
                ;;
            openEuler24.03)
                IMAGES_BASE_TAG=${VLLM_ASCEND_VERSION}-openeuler
                ;;
            *)
                echo "不支持的服务器操作系统"
                ;;
        esac
    ;;
  "A3")
    IMAGES_TAG=mindie-motor-vllm:${IMAGE_VERSION}-800I-A3-py3.11-${SYSTEM}-lts-${ARCH}
        case $SYSTEM in
            Ubuntu24.04)
                IMAGES_BASE_TAG=${VLLM_ASCEND_VERSION}-a3
                ;;
            openEuler24.03)
                IMAGES_BASE_TAG=${VLLM_ASCEND_VERSION}-a3-openeuler
                ;;
            *)
                echo "不支持的服务器操作系统"
                ;;
        esac
    ;;
  *)
    echo "Unsupported architecture: $DEVICE"
    exit 1
    ;;
esac
################################################prepare version information#############################################################################
out_path=${WORKSPACE}/CI/docker_pymotor_image/MindIE_Motor_vLLM_version.txt
touch ${out_path}
echo "****************************************VLLM_ASCEND BASE IMAGE*************************************************" >${out_path}
echo "quay.nju.edu.cn/ascend/vllm-ascend:${VLLM_ASCEND_VERSION}" >> ${out_path}
echo "quay.nju.edu.cn/ascend/vllm-ascend:${VLLM_ASCEND_VERSION}-a3" >> ${out_path}
echo "quay.nju.edu.cn/ascend/vllm-ascend:${VLLM_ASCEND_VERSION}-openeuler" >> ${out_path}
echo "quay.nju.edu.cn/ascend/vllm-ascend:${VLLM_ASCEND_VERSION}-a3-openeuler" >> ${out_path}
function start_clean_server() {
    set +e
    serverjs_path=${WORKSPACE}/CI/docker_pymotor_image/server.js
    if [[ ! -f $serverjs_path ]]; then
      echo "File $file_path does not exist, exit"
      exit 1
    else
      pid=$(ps -ef | grep -v grep | grep "node.*/opt/.*/workspace/.*/CI/.*/server.js" | awk '{print $2}')
      if [[ -n "$pid" ]]; then
        kill -9 "$pid"
      fi
      nohup node ${serverjs_path} > server.log 2>&1 &
      echo "server.js started"
    fi
    ps -ef | grep server.js
}
function clean_server() {
    set +e
    pid=$(ps -ef | grep -v grep | grep "node.*/opt/.*/workspace/.*/CI/.*/server.js" | awk '{print $2}')
    if [[ -n "$pid" ]]; then
      kill -9 "$pid"
    fi
    ps -ef | grep server.js
}
function remove_containers_images() {
    set +e
    ps_output=$(docker ps -a -q -f status=exited)
    if [ ${#ps_output} -gt 0 ]; then
      docker rm ${ps_output}
    else
      echo "no exited container"
    fi
    images_output=$(docker images | grep "<none>")
    if [ ${#images_output} -gt 0 ]; then
      docker images | grep "<none>" | awk '{print $3}' | xargs docker rmi -f
    else
      echo "no exited images"
    fi
}
function prepare_pymotor() {
    pymotor_local_path_base="obs://mindie/artifact/gitcode/MindIE-PyMotor/${PYMOTOR_BRANCH}/daily"
    obsutil config -i=${AK} -k=${SK} -e=obs.cn-north-4.myhuaweicloud.com
    pymotor_directories=$(obsutil ls "$pymotor_local_path_base" -d -limit=2000 | grep -Eo "${current_date}\.[^/]+/" | sed 's/\///' | sort -Vr | uniq)
    if [ -z "${PYMOTOR_DIR}" ]; then
        echo "Querying today's latest compilation by default"
        pymotor_dir=$(echo "$pymotor_directories" | awk 'NR==1{print $1}')
    else
        echo -e "\033[33m[ACTION]\033[0m Using compilation results for specific date ${PYMOTOR_DIR}"
        pymotor_dir=${PYMOTOR_DIR}
    fi
    
    set +e
    echo "**************************************MindIE-pyMotor***************************************************" >>${out_path}
    mkdir -p ${WORKSPACE}/MindIE-pyMotor
    cd ${WORKSPACE}/MindIE-pyMotor
    obsutil cp ${pymotor_local_path_base}/${pymotor_dir} . -r -f
    for file in "${WORKSPACE}/MindIE-pyMotor"/$pymotor_dir/*; do
        [ -e "$file" ] || continue
        file_name=$(basename ${file})
        echo "https://mindie.obs.cn-north-4.myhuaweicloud.com/artifact/gitcode/MindIE-PyMotor/${PYMOTOR_BRANCH}/daily/$pymotor_dir/${file_name}" >> ${out_path}
    done
    ls -alR ${WORKSPACE}/MindIE-pyMotor
    mv ${WORKSPACE}/MindIE-pyMotor/$pymotor_dir/* ${WORKSPACE}/CI/docker_pymotor_image/
    json_file=${WORKSPACE}/CI/docker_pymotor_image/MindIE-pyMotor.json
    jq -r 'to_entries | map("\(.key): \(.value)") | .[]' "$json_file" >> ${out_path}
    ls -lR ${WORKSPACE}/CI/docker_pymotor_image
}
################################################prepare dockerfile#############################################################################
echo "**************prepare dockerfile********************"
cd ${WORKSPACE}/CI/docker_pymotor_image 
sed -i "s/IMAGES_BASE_TAG/${IMAGES_BASE_TAG}/g" Dockerfile.${SYSTEM_LOWER}

################################################make image#############################################################################
remove_containers_images
prepare_pymotor
cd ${WORKSPACE}/CI/docker_pymotor_image 
start_clean_server
docker build --network=host -t ${IMAGES_TAG}  -f Dockerfile.${SYSTEM_LOWER}  .
docker images
clean_server
remove_containers_images
################################################package and upload#############################################################################
echo "******************package and upload,please wait***************************************"
docker save ${IMAGES_TAG} | pigz -c > ${IMAGES_TAG}.tar.gz
docker rmi ${IMAGES_TAG} quay.nju.edu.cn/ascend/vllm-ascend:${IMAGES_BASE_TAG}
obsutil config -i=${AK} -k=${SK} -e=obs.cn-north-4.myhuaweicloud.com 
obsutil cp ${IMAGES_TAG}.tar.gz obs://mindie/artifact/gitcode/MindIE-PyMotor/docker-images/${PYMOTOR_BRANCH}/${BUILDNUMBER}/ -f -r  
obsutil cp ${out_path} obs://mindie/artifact/gitcode/MindIE-PyMotor/docker-images/${PYMOTOR_BRANCH}/${BUILDNUMBER}/ -f -r  
   
```

### 运行 MindIE-PyMotor 容器

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

## 许可证

查看这些镜像中包含的 PyMotor 的[许可证信息](https://gitcode.com/Ascend/MindIE-PyMotor/blob/master/LICENSE.md)。

与所有容器镜像一样，预装软件包（Python、系统库等）可能受其自身许可证约束。