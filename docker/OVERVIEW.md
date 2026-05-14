# MindIE-PyMotor 

> [English](./OVERVIEW.md) | 中文

## Quick Reference

- MindIE-PyMotor is maintained by the [MindIE community](https://www.hiascend.com/cn/developer/software/mindie)

- Where to get help

    - [MindIE Image Registry](https://www.hiascend.com/developer/ascendhub/detail/af85b724a7e5469ebd7ea13c3439d48f)
    - [MindIE-PyMotor Documentation](https://gitcode.com/Ascend/MindIE-PyMotor/blob/master/docs/zh/index.md)
    - [Atlas Developer Community](https://www.hiascend.com/developer)
    - [Report an Issue](https://gitcode.com/Ascend/MindIE-PyMotor/issues)

---

## MindIE-PyMotor

Provides one‑click PD-separated deployment, flexibly adapts to multiple inference engines (vLLM, SGLang) through a cloud‑native plug‑in architecture, and combines high‑performance scheduling with load balancing capabilities to build highly available, scalable large‑scale inference services.

---

## Supported Tags and Dockerfile Links

### Tag Specification

Tags follow the format:

```
<PyMotorVersion>-<ProductSeries>-<PythonVersion>-<OperatingSystem>-<Architecture>
```

| Field | Example Value | Description |
|---|---|---|
| `PyMotorVersion` | `3.0.0` | PyMotor version number |
| `ProductSeries` | `800I-A2`, `800I-A3`, `300I-Duo` | Target Atlas product series |
| `OperatingSystem` | `ubuntu22.04`, `openeuler24.03` | Base operating system |
| `PythonVersion` | `py3.10`, `py3.11`, `py3.12` | Python version |
| `Architecture` | `x86_64`, `aarch64` | Architecture type |

### Image Registry Address

MindIE-PyMotor images are hosted on Huawei Cloud SWR:

```text
swr.cn-south-1.myhuaweicloud.com/
```

**Full image example:**

```text
swr.cn-south-1.myhuaweicloud.com/mindie-pymotor/mindie-pymotor:3.0.0-800I-A2-ubuntu22.04-py3.11
```

### Build Parameters


| Parameter | Description | Required | Reference | Example Value |
|---|---|---|---|---|
| SYSTEM | Server OS and version | Yes | Script parameter `$1` | Ubuntu24.04 / openEuler24.03 |
| DEVICE | Atlas device model | Yes | Script parameter `$2` | 310p / 910b / A3 |
| ARCH | System architecture | Yes | Script parameter `$3` | x86_64 / aarch64 |
| PYMOTOR_VERSION | MindIE-PyMotor version number | Yes | Script parameter `$4` | 0.1.0 |
| PYMOTOR_BRANCH | PyMotor code branch | Yes | Script parameter `$5` | master |
| VLLM_ASCEND_VERSION | vllm-ascend base image version/branch | Yes | Script parameter `$6` | v0.13.0 / main / v0.14.0rc1 / releases-v0.13.0 |
| IMAGE_VERSION | Version tag for the final built image | Yes | Script parameter `$7` | v1.0.0 |
| AK | Huawei Cloud OBS Access Key | Yes | Script parameter `$8` | actual AK string |
| SK | Huawei Cloud OBS Secret Key | Yes | Script parameter `$9` | actual SK string |
| PYMOTOR_DIR | Specific date directory of PyMotor build artifacts (optional, latest used by default) | No | Script parameter `${10}` | 20260114.1 |
| WORKSPACE | CI workspace root path | Yes | Environment variable | /opt/workspace |
| BUILDNUMBER | CI build number | Yes | Environment variable | 100 |

---

## Quick Start

### Prerequisites (Optional)

#### Install Drivers

- Firmware and drivers have been installed on the host. Refer to [Install Drivers and Firmware](https://www.hiascend.com/document/detail/zh/mindie/100/envdeployment/instg/mindie_instg_0006.html) for details.
- Docker is installed on the host.

---

### Build MindIE-PyMotor Image

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
                echo "Unsupported server OS"
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
                echo "Unsupported server OS"
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
                echo "Unsupported server OS"
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

### Run MindIE-PyMotor Container

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
| Atlas 910B | Atlas 800T A2, Atlas 900 A2 PoD | ARM64 / x86_64 |
| Atlas A3 | Atlas 800T A3 | ARM64 / x86_64 |
| Atlas 310P | Atlas 300I Pro, Atlas 300V Pro | ARM64 / x86_64 |

---

## License

See the [license information of PyMotor](https://www.hiascend.com/cn/developer/software/mindie) included in these images.

As with all container images, pre‑installed software packages (Python, system libraries, etc.) may be subject to their own licenses.