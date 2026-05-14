FROM quay.nju.edu.cn/ascend/vllm-ascend:IMAGES_BASE_TAG
RUN wget http://172.17.0.1:3000/MindIE-PyMotor_all.tar.gz -P /tmp && \
    cd /tmp && tar -zxf MindIE-PyMotor_all.tar.gz && \
    yum install pciutils -y && \
    pip install -r requirements.txt -i https://repo.huaweicloud.com/repository/pypi/simple && \
    pip install --force-reinstall motor*.whl && \
    pip install -r motor/requirements.txt -i https://repo.huaweicloud.com/repository/pypi/simple && \
    pip install --force-reinstall ccae_reporter-*.whl && \
	  rm -rf motor/requirements.txt && \
    ls -l motor/examples/features/fault_tolerance/ras_monitor && \
    rm -rf motor/examples/features/fault_tolerance/ras_monitor && \
    find /tmp -mindepth 1 -maxdepth 1 ! -name "motor" -exec rm -rf {} + && \
    ls -l /tmp