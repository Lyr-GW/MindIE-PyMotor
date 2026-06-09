# syntax=docker/dockerfile:1.4
#
# Self-contained Dockerfile for mindie-motor-vllm:3.0.0-800I-A3-py3.11-openEuler24.03-lts-x86_64
#
# Base image: quay.nju.edu.cn/ascend/vllm-ascend:v0.18.0-a3-openeuler
# Target platform: linux/amd64
#
# Build from the repository root:
#   docker build --network=host \
#       --platform=linux/amd64 \
#       -t mindie-motor-vllm:3.0.0-800I-A3-py3.11-openEuler24.03-lts-x86_64 \
#       -f docker/mindie-motor-vllm/3.0.0-800I-A3-py3.11-openEuler24.03-lts-x86_64/Dockerfile \
#       .

FROM quay.nju.edu.cn/ascend/vllm-ascend:v0.18.0-a3-openeuler

ARG IMAGE_VERSION=3.0.0
ARG PIP_INDEX_URL=https://repo.huaweicloud.com/repository/pypi/simple
ARG PIP_TRUSTED_HOST=repo.huaweicloud.com

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt/MindIE-PyMotor

COPY . /opt/MindIE-PyMotor/

RUN set -eux; \
    pip install --no-cache-dir -r requirements.txt; \
    bash build.sh; \
    pip install --no-cache-dir --force-reinstall dist/motor*.whl; \
    rm -rf build/ motor.egg-info/ dist/

RUN set -eux; \
    cd examples/features/observability; \
    pip install --no-cache-dir -r requirements.txt; \
    bash build.sh; \
    pip install --no-cache-dir --force-reinstall dist/ccae_reporter-*.whl; \
    rm -rf build/ dist/ ccae_reporter.egg-info/

RUN set -eux; \
    mkdir -p /tmp/motor; \
    mv /opt/MindIE-PyMotor/examples /tmp/motor/; \
    ls -l /tmp/motor/examples; \
    rm -rf /tmp/motor/examples/features/fault_tolerance/ras_monitor; \
    ls -l /tmp/motor/examples/features/fault_tolerance; \
    find /tmp -mindepth 1 -maxdepth 1 ! -name "motor" -exec rm -rf {} +

WORKDIR /workspace

COPY docker/agreement.txt /workspace/agreement.txt
RUN sed -i "1s|__VERSION__|${IMAGE_VERSION}|" /workspace/agreement.txt

COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/bin/bash"]
