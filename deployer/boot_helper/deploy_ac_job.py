#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import argparse
import os
import json
import subprocess
import logging
import sys
import shlex
import copy
from datetime import datetime
from zoneinfo import ZoneInfo
from ruamel.yaml import YAML, scalarstring
import yaml as ym
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from ruamel.yaml.comments import CommentedMap, CommentedSeq

sys.path.append(os.getcwd())

from utils.validate_config import validate_user_config

# 配置日志格式和级别
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # 同时输出到控制台
    ]
)

# 创建一个YAML处理器，使用RoundTripLoader和RoundTripDumper
yaml = YAML(typ='rt')  # RoundTrip模式
yaml.preserve_quotes = True  # 保留原有引号
MAX_P_INSTANCES_NUM = 1024
MAX_D_INSTANCES_NUM = 1024
MAX_SINGER_P_INSTANCES_NODE_NUM = 1024
MAX_SINGER_D_INSTANCES_NODE_NUM = 1024
WORKER_REPLICAS_OFFSET = 1
JOB_ID = "jobID"
LABELS = "labels"
METADATA = "metadata"
SPEC = "spec"
TEMPLATE = "template"
CONTAINERS = "containers"
IMAGE = "image"
NAME = "name"
MASTER = "Master"
WORKER = "Worker"
REPLICA_SPECS = "replicaSpecs"
RUN_POLICY = "runPolicy"
SCHEDULING_POLICY = "schedulingPolicy"
REPLICAS = "replicas"
MIN_AVAILABLE = "minAvailable"
P_INSTANCES_NUM = "p_instances_num"
D_INSTANCES_NUM = "d_instances_num"
CONFIG_JOB_ID = "job_id"
IMAGE_NAME = "image_name"
SINGER_P_INSTANCES_NUM = "single_p_instance_pod_num"
SINGER_D_INSTANCES_NUM = "single_d_instance_pod_num"
SERVER_GROUP_LIST = "server_group_list"
SERVER_ID = "server_id"
DEVICE = "device"
SERVER_COUNT = "server_count"
SERVER_IP = "server_ip"
GROUP_ID = "group_id"
SERVER_LIST = 'server_list'
GROUP_LIST = "group_list"
HARDWARE_TYPE = 'hardware_type'
CONTAINER_IP = 'container_ip'
DEVICE_LOGICAL_ID = "device_logical_id"
PATH = "path"
HOST_PATH = "hostPath"
MINDIE_HOST_LOG_PATH = "mindie_host_log_path"
MODEL_NAME = "model_name"
MODEL_ID = "model_id"
CONTAINER_LOG_PATH = "mindie_container_log_path"
VALUE = "value"
VOLUME_MOUNTS = "volumeMounts"
VOLUMES = "volumes"
ENV = "env"
MOUNT_PATH = "mountPath"
MINDIE_SERVER = "mindie-server-"
ASCEND_910_CONFIG = "ascend-910-config"
CONFIG_MAP = "configMap"
CONFIG = "-config"
RINGS_CONFIG_MINDIE_SERVER = "rings-config-mindie-server-"
ASCEND_910_NPU_NUM = "huawei.com/Ascend910"
POD_NPU_NUM = "_pod_npu_num"
REQUESTS = "requests"
RESOURCES = "resources"
LIMITS = "limits"
CONFIG_MODEL_NAME = ""
YAML = ".yaml"
DEPLOY_SERVER_NUM = "grt-group/deploy-server"
INIT_PORT = 10000
MIND_CLUSTER_SCALING_RULE = "mind-cluster/scaling-rule"
MIND_CLUSTER_GROUP_NAME = "mind-cluster/group-name"
PRIORITY_CLASS = "priorityClass"
LOW_PRIORITY = "low-priority"
HIGH_PRIORITY = "high-priority"
P_DEPLOY_SERVER = 'p_deploy_server'
D_DEPLOY_SERVER = 'd_deploy_server'
WEIGHT_MOUNT_PATH = "weight_mount_path"
NODE_SELECTOR = "nodeSelector"
MINDIE_ROLE = "mindie-role"
NAME_FLAG = " -n "
SERVER_CONFIG = "ServerConfig"
NAMESPACE = "namespace"
TP = "tp"
DP = "dp"
SP = "sp"
CP = "cp"
DIST_DP_SERVER_ENABLED = "distDPServerEnabled"
NAME_MOUNT = 'mount'
NAME_KEY = 'name'
MODEL_CONFIG = "ModelConfig"
MODEL_DEPLOY_CONFIG = "ModelDeployConfig"
BACKEND_CONFIG = "BackendConfig"
FROM_FILE_CONFIG_JSON_C = "-config --from-file=config.json="
APPLY_F_D = "kubectl apply -f "
TLS_ENABLE = "tls_enable"
TLS_CONFIG = "tls_config"
TLS_KEY = "tls_key"
TLS_PASSWD = "tls_passwd"
TLS_CRL = "tls_crl"
KMC_KSF_STANDBY = "kmc_ksf_standby"
KMC_KSF_MASTER = "kmc_ksf_master"
MANAGEMENT_TLS_ITEMS = "management_tls_items"
TLS_CERT = "tls_cert"
MANAGEMENT = "management"
TLS_PATH_SEPARATOR = "/"
CA_CERT = "ca_cert"
CCAE_TLS_ITEMS = "ccae_tls_items"
CONTROLLER_BACKUP_CFG = "controller_backup_cfg"
CONTROLLER_BACKUP_SW = "function_sw"
POD_NUM_ZERO = 0
DEPLOY_CONFIG = "deploy_config"
DELETE_F_D = "kubectl delete -f "
ELASTIC_P_CHANGE = "p_instances_scale_num"
ELASTIC_D_CHANGE = "d_instances_scale_num"
MIN_ELASTIC_NUM = -96
MAX_ELASTIC_NUM = 96
INSTANCE_NUM_ZERO = 0
ANNOTATIONS = "annotations"
SP_BLOCK = "sp-block"
P_POD_NPU_NUM = "p_pod_npu_num"
D_POD_NPU_NUM = "d_pod_npu_num"
BOOT_SHELL_PATH = "./boot_helper/boot.sh"
ETCD_TLS_ITEMS = "etcd_server_tls_items"
MAX_ITER_TIMES = "maxIterTimes"

context = dict()


def process_yaml(data):
    """
    遍历YAML数据，处理以0开头的数字，并修改指定内容。
    """
    if isinstance(data, dict):
        for key, value in data.items():
            # 处理以0开头的数字
            if isinstance(value, str) and value.startswith('0') and value.isdigit():
                # 将其转换为带双引号的字符串
                data[key] = scalarstring.DoubleQuotedScalarString(value)
            else:
                process_yaml(value)  # 递归处理子节点

            # 示例：修改特定键的值
            if key == 'target_key':
                data[key] = 'new_value'

    elif isinstance(data, list):
        for item in data:
            process_yaml(item)


def read_json(json_path):
    with open(json_path, "r", encoding='utf-8') as json_file:
        return json.load(json_file)


def get_key_loc(data, namespace, key):
    loc = -1
    for item in data:
        loc = loc + 1
        if item[NAME] == key:
            context[namespace + "_" + key] = int(loc)
            return int(loc)
    return int(loc)


def write_yaml(data, output_file, single_doc=False):
    with open(output_file, 'w', encoding="utf-8") as f:
        if single_doc:
            yaml.dump(data, f)
        else:
            yaml.dump_all(data, f)


def exec_cmd(command, print_log=True):
    cmd_args = shlex.split(command)
    child = subprocess.Popen(cmd_args, stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
    stdout, stderr = child.communicate(timeout=60)

    if print_log:
        logging.info(f"Output from command:\n {command} \n is: {stdout}, {stderr} .")
    return stdout


def modify_controller_yaml(data, config, env_config):
    data[METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[METADATA][NAME] = config[CONFIG_JOB_ID] + "-controller"
    data[METADATA][NAMESPACE] = config[CONFIG_JOB_ID]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][IMAGE] = config[IMAGE_NAME]


def modify_controller_replicas(data, config):
    if CONTROLLER_BACKUP_CFG in deploy_config and CONTROLLER_BACKUP_SW in deploy_config[CONTROLLER_BACKUP_CFG]:
        backup_switch = config[CONTROLLER_BACKUP_CFG][CONTROLLER_BACKUP_SW]
        master_cnt = data[SPEC][REPLICA_SPECS][MASTER][REPLICAS]
        worker_cnt = POD_NUM_ZERO
        if backup_switch is True or str(backup_switch).lower() == "true":
            data[SPEC][REPLICA_SPECS][WORKER] = copy.deepcopy(data[SPEC][REPLICA_SPECS][MASTER])
            worker_cnt = data[SPEC][REPLICA_SPECS][WORKER][REPLICAS]
        data[SPEC][RUN_POLICY][SCHEDULING_POLICY][MIN_AVAILABLE] = master_cnt + worker_cnt


def modify_coordinator_yaml_app_v1(data, config):
    data[METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[METADATA][NAME] = config[CONFIG_JOB_ID] + "-coordinator"
    data[METADATA][NAMESPACE] = config[CONFIG_JOB_ID]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][IMAGE] = config[IMAGE_NAME]


def modify_coordinator_yaml_v1(data, config):
    data[METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[METADATA][NAMESPACE] = config[CONFIG_JOB_ID]


def modify_server_yaml_v1(data, config, index, pd_flag):
    data[METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[METADATA][NAMESPACE] = config[CONFIG_JOB_ID]
    data[METADATA][NAME] = RINGS_CONFIG_MINDIE_SERVER + pd_flag + str(index)
    data[METADATA][LABELS][MIND_CLUSTER_SCALING_RULE] = "scaling-rule"
    if pd_flag == "p":
        data[METADATA][LABELS][DEPLOY_SERVER_NUM] = DoubleQuotedScalarString(str(config["prefill_distribute_enable"]))
        data[METADATA][LABELS][MIND_CLUSTER_GROUP_NAME] = "group0"
    else:
        data[METADATA][LABELS][DEPLOY_SERVER_NUM] = DoubleQuotedScalarString(str(config["decode_distribute_enable"]))
        data[METADATA][LABELS][MIND_CLUSTER_GROUP_NAME] = "group1"


def modify_server_yaml_priority(priority_data, data, pd_flag, deploy_config, index):
    job_id = deploy_config[CONFIG_JOB_ID]
    if pd_flag == "p":
        priority_data[METADATA][NAME] = f"{job_id}-{LOW_PRIORITY}-{pd_flag}{index}"
        priority_data[VALUE] = 1
        data[SPEC][RUN_POLICY][SCHEDULING_POLICY][PRIORITY_CLASS] = f"{job_id}-{LOW_PRIORITY}-{pd_flag}{index}"
    else:
        priority_data[METADATA][NAME] = f"{job_id}-{HIGH_PRIORITY}-{pd_flag}{index}"
        priority_data[VALUE] = 100
        data[SPEC][RUN_POLICY][SCHEDULING_POLICY][PRIORITY_CLASS] = f"{job_id}-{HIGH_PRIORITY}-{pd_flag}{index}"


def modify_server_yaml_mind_v1(data, config, index, pd_flag, ext):
    modify_server_yaml_common(config, data, ext["env_config"], pd_flag)
    modify_npu_num(data, config, pd_flag)
    modify_name_labels(config, data, index, pd_flag)
    modify_ascend_config(data, index, pd_flag)
    modify_server_config(data, index, pd_flag)
    modify_weight_mount_path(config, data)
    modify_replica_num(data, ext["single_instance_pod_num"])


def modify_name_labels(config, data, index, pd_flag):
    data[METADATA][NAME] = MINDIE_SERVER + pd_flag + str(index)
    data[METADATA][LABELS][MIND_CLUSTER_SCALING_RULE] = "scaling-rule"
    if pd_flag == "p":
        data[METADATA][LABELS][DEPLOY_SERVER_NUM] = DoubleQuotedScalarString(str(config["prefill_distribute_enable"]))
        data[METADATA][LABELS][MIND_CLUSTER_GROUP_NAME] = "group0"
    else:
        data[METADATA][LABELS][DEPLOY_SERVER_NUM] = DoubleQuotedScalarString(str(config["decode_distribute_enable"]))
        data[METADATA][LABELS][MIND_CLUSTER_GROUP_NAME] = "group1"


def modify_replica_num(data, singer_instances_node_num):
    data[SPEC][RUN_POLICY][SCHEDULING_POLICY][MIN_AVAILABLE] = singer_instances_node_num
    data[SPEC][REPLICA_SPECS][WORKER][REPLICAS] = singer_instances_node_num - WORKER_REPLICAS_OFFSET


def modify_ascend_config(data, index, pd_flag):
    config_loc = get_key_loc(data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS],
                             VOLUME_MOUNTS, ASCEND_910_CONFIG)
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS][config_loc][NAME] \
        = ASCEND_910_CONFIG + "-" + pd_flag + str(index)
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS][config_loc][NAME] \
        = ASCEND_910_CONFIG + "-" + pd_flag + str(index)
    volumes_config_loc = get_key_loc(data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][VOLUMES], VOLUMES,
                                     ASCEND_910_CONFIG)
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][VOLUMES][volumes_config_loc][NAME] \
        = ASCEND_910_CONFIG + "-" + pd_flag + str(index)
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][VOLUMES][volumes_config_loc][NAME] \
        = ASCEND_910_CONFIG + "-" + pd_flag + str(index)
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][VOLUMES][volumes_config_loc][CONFIG_MAP][NAME] \
        = RINGS_CONFIG_MINDIE_SERVER + pd_flag + str(index)
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][VOLUMES][volumes_config_loc][CONFIG_MAP][NAME] \
        = RINGS_CONFIG_MINDIE_SERVER + pd_flag + str(index)


def modify_server_config(data, index, pd_flag):
    server_config_loc = get_key_loc(data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS],
                                    VOLUME_MOUNTS, "mindie-server-config")
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS][server_config_loc][NAME] \
        = MINDIE_SERVER + pd_flag + str(index) + CONFIG
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS][server_config_loc][NAME] \
        = MINDIE_SERVER + pd_flag + str(index) + CONFIG
    volumes_server_config_loc = get_key_loc(data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][VOLUMES],
                                            VOLUMES, "mindie-server-config")
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][VOLUMES][volumes_server_config_loc][NAME] = (
            MINDIE_SERVER + pd_flag + str(index) + CONFIG)
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][VOLUMES][volumes_server_config_loc][CONFIG_MAP][NAME] = (
            MINDIE_SERVER + pd_flag + str(index) + CONFIG)
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][VOLUMES][volumes_server_config_loc][NAME] = (
            MINDIE_SERVER + pd_flag + str(index) + CONFIG)
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][VOLUMES][volumes_server_config_loc][CONFIG_MAP][NAME] = (
            MINDIE_SERVER + pd_flag + str(index) + CONFIG)


def modify_weight_mount_path(config, data):
    mindie_log_path_loc = get_key_loc(data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS],
                                      VOLUME_MOUNTS, "weight-mount-path")
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS][mindie_log_path_loc][MOUNT_PATH] \
        = config[WEIGHT_MOUNT_PATH]
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][CONTAINERS][0][VOLUME_MOUNTS][mindie_log_path_loc][MOUNT_PATH] \
        = config[WEIGHT_MOUNT_PATH]
    host_log_path_loc = get_key_loc(data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][VOLUMES],
                                    VOLUMES, "weight-mount-path")
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][VOLUMES][host_log_path_loc][HOST_PATH][PATH] = (
        config)[WEIGHT_MOUNT_PATH]
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][VOLUMES][host_log_path_loc][HOST_PATH][PATH] = (
        config)[WEIGHT_MOUNT_PATH]


def modify_server_yaml_common(config, data, env_config, pd_flag):
    data[METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[METADATA][NAMESPACE] = config[CONFIG_JOB_ID]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][IMAGE] = config[IMAGE_NAME]
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][CONTAINERS][0][IMAGE] = config[IMAGE_NAME]
    if HARDWARE_TYPE in config and config["hardware_type"] == "800I_A3":
        data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC]["nodeSelector"]["accelerator-type"] = "module-a3-16"
        data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC]["nodeSelector"]["accelerator-type"] = "module-a3-16"


def modify_server_yaml_singer_v1(data, config):
    data[METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]


def modify_server_yaml_singer_apps_v1(data, config):
    data[METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][IMAGE] = config[IMAGE_NAME]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][METADATA][LABELS][JOB_ID] = config[CONFIG_JOB_ID]


def modify_npu_num(data, config, pd_flag):
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][RESOURCES][REQUESTS][ASCEND_910_NPU_NUM] \
        = config[pd_flag + POD_NPU_NUM]
    data[SPEC][REPLICA_SPECS][MASTER][TEMPLATE][SPEC][CONTAINERS][0][RESOURCES][LIMITS][ASCEND_910_NPU_NUM] \
        = config[pd_flag + POD_NPU_NUM]
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][CONTAINERS][0][RESOURCES][REQUESTS][ASCEND_910_NPU_NUM] \
        = config[pd_flag + POD_NPU_NUM]
    data[SPEC][REPLICA_SPECS][WORKER][TEMPLATE][SPEC][CONTAINERS][0][RESOURCES][LIMITS][ASCEND_910_NPU_NUM] \
        = config[pd_flag + POD_NPU_NUM]


def obtain_server_instance_total(deploy_config):
    p_base, d_base = obtain_server_instance_base_config(deploy_config)
    return p_base, d_base


def obtain_server_instance_base_config(deploy_config):
    p_base = int(deploy_config[P_INSTANCES_NUM])
    d_base = int(deploy_config[D_INSTANCES_NUM])
    if p_base <= INSTANCE_NUM_ZERO or p_base > MAX_P_INSTANCES_NUM:
        raise ValueError(f"{P_INSTANCES_NUM} must between ({INSTANCE_NUM_ZERO}, {MAX_P_INSTANCES_NUM}]")
    if d_base <= INSTANCE_NUM_ZERO or d_base > MAX_D_INSTANCES_NUM:
        raise ValueError(f"{D_INSTANCES_NUM} must between ({INSTANCE_NUM_ZERO}, {MAX_D_INSTANCES_NUM}]")
    return p_base, d_base


def generator_yaml(input_yaml, output_file, json_path, single_doc=False, env_config=None):
    """
    主函数，读取YAML文件，处理数据，然后写入新文件。
    """

    # 读取用户配置
    json_config = read_json(json_path)
    json_config = json_config["deploy_config"]
    ext = dict()
    if "controller" in input_yaml:
        data = load_yaml(input_yaml, single_doc)
        modify_controller_yaml(data, json_config, env_config)
        modify_controller_replicas(data, json_config)
        write_yaml(data, output_file, single_doc)
    elif "coordinator" in input_yaml:
        data = load_yaml(input_yaml, single_doc)
        modify_coordinator_yaml_app_v1(data[0], json_config)
        modify_coordinator_yaml_v1(data[1], json_config)
        write_yaml(data, output_file, single_doc)
    elif "server" in input_yaml:
        p_total, d_total = obtain_server_instance_total(json_config)
        p_base, d_base = obtain_server_instance_base_config(json_config)
        p_max = max(p_total, p_base)
        d_max = max(d_total, d_base)
        for p_index in range(p_max):
            data = load_yaml(input_yaml, single_doc)
            modify_server_yaml_v1(data[0], json_config, p_index, "p")

            ext["env_config"] = env_config
            ext["single_instance_pod_num"] = json_config[SINGER_P_INSTANCES_NUM]
            modify_server_yaml_mind_v1(data[2], json_config, p_index, "p", ext)
            modify_server_yaml_priority(data[1], data[2], "p", json_config, p_index)
            last_output_file = output_file + "_p" + str(p_index) + ".yaml"
            write_yaml(data, last_output_file)
        for d_index in range(d_max):
            data = load_yaml(input_yaml, single_doc)
            modify_server_yaml_v1(data[0], json_config, d_index, "d")
            ext["env_config"] = env_config
            ext["single_instance_pod_num"] = json_config[SINGER_D_INSTANCES_NUM]
            modify_server_yaml_mind_v1(data[2], json_config, d_index, "d", ext)
            modify_server_yaml_priority(data[1], data[2], "d", json_config, d_index)
            last_output_file = output_file + "_d" + str(d_index) + ".yaml"
            write_yaml(data, last_output_file)
    elif "single" in input_yaml:
        data = load_yaml(input_yaml, single_doc)
        modify_server_yaml_singer_v1(data[0], json_config)
        modify_server_yaml_singer_apps_v1(data[1], json_config)
        write_yaml(data, output_file, single_doc)


def load_yaml(input_yaml, single_doc):
    # 打开原始yaml文件
    with open(input_yaml, 'r', encoding="utf-8") as f:
        if single_doc:
            data = ym.safe_load(f)
        else:
            data = list(ym.safe_load_all(f))
    process_yaml(data)
    return data


def update_json_value(data, path, new_value, delimiter="/"):
    """
    修改JSON数据中指定路径的值
    :param data: dict类型，原始JSON数据（字典格式）
    :param path: str类型，目标路径（例如："user/address/street"）
    :param new_value: 要设置的新值
    :param delimiter: 路径分隔符，默认为/
    :return: 修改后的字典
    """
    keys = path.split(delimiter)
    current = data
    # 逐层遍历到目标父节点
    for key in keys[:-1]:
        current = current[key]
    # 修改最终键的值
    current[keys[-1]] = new_value
    return data


def update_dict(original, modified):
    """
    递归更新原始字典，新增修改字典中存在但原始字典没有的字段
    :param original: 将被修改的原始字典
    :param modified: 包含修改内容的字典
    """
    for key in modified:
        # 处理已存在的键
        if key in original:
            # 递归处理嵌套字典
            if isinstance(modified[key], dict) and isinstance(original[key], dict):
                update_dict(original[key], modified[key])
            # 直接更新非字典值
            elif original[key] != modified[key]:
                original[key] = modified[key]
        # 添加新增键（包含嵌套结构）
        else:
            # 递归创建嵌套字典结构
            if isinstance(modified[key], dict):
                original[key] = {}
                update_dict(original[key], modified[key])
            # 直接添加普通值
            else:
                original[key] = modified[key]
    return original


def write_json_data(data, json_path):
    with open(json_path, 'w') as r:
        json.dump(data, r, indent=4, ensure_ascii=False)


def exec_cm_create_kubectl_multi(deploy_config, out_path):
    out_conf_path = os.path.join(out_path, 'conf')
    logging.info("Starting to execute kubectl create configmap multi")
    exec_cmd("kubectl create configmap common-env --from-literal=MINDIE_USER_HOME_PATH=/usr/local -n " +
             deploy_config[CONFIG_JOB_ID])
    exec_cmd("kubectl create configmap boot-bash-script --from-file=./boot_helper/boot.sh -n " +
             deploy_config[CONFIG_JOB_ID])
    exec_cmd("kubectl create configmap server-prestop-bash-script --from-file=./boot_helper/server_prestop.sh -n " +
             deploy_config[CONFIG_JOB_ID])
    exec_cmd("kubectl create configmap python-script-get-group-id --from-file=./boot_helper/get_group_id.py -n " +
             deploy_config[CONFIG_JOB_ID])
    exec_cmd(
        "kubectl create configmap python-script-update-server-conf "
        "--from-file=./boot_helper/update_mindie_server_config.py -n " +
        deploy_config[CONFIG_JOB_ID])
    exec_cmd(
        "kubectl create configmap global-ranktable --from-file=./gen_ranktable_helper/global_ranktable.json -n " +
        deploy_config[CONFIG_JOB_ID])

    exec_cmd("kubectl create configmap mindie-ms-coordinator-config --from-file=" +
             os.path.join(out_conf_path, "ms_coordinator.json" + NAME_FLAG + deploy_config[CONFIG_JOB_ID]))
    exec_cmd("kubectl create configmap mindie-ms-controller-config --from-file=" +
             os.path.join(out_conf_path, "ms_controller.json" + NAME_FLAG + deploy_config[CONFIG_JOB_ID]))
    exec_cmd("kubectl create configmap mindie-http-client-ctl-config --from-file=" +
             os.path.join(out_conf_path, "http_client_ctl.json" + NAME_FLAG + deploy_config[CONFIG_JOB_ID]))
    exec_cmd("kubectl create configmap scaling-rule --from-file=" +
             os.path.join(str(out_path), "elastic_scaling.json" + NAME_FLAG + deploy_config[CONFIG_JOB_ID]))
    exec_cmd("kubectl create configmap python-script-gen-config-single-container "
             "--from-file=./boot_helper/gen_config_single_container.py -n " + deploy_config[CONFIG_JOB_ID])


def exec_cm_elastic_kubectl(deploy_config, out_path):
    logging.info("Starting to execute kubectl update configmap elastic")
    exec_cmd("kubectl delete configmap scaling-rule" + NAME_FLAG + deploy_config[CONFIG_JOB_ID])
    exec_cmd("kubectl create configmap scaling-rule --from-file=" +
             os.path.join(str(out_path), "elastic_scaling.json" + NAME_FLAG + deploy_config[CONFIG_JOB_ID]))


def distributed_server_deploy(config_dict, out_conf_path, out_deploy_yaml_path):
    for index in range(config_dict[P_INSTANCES_NUM]):
        exec_cmd("kubectl delete configmap mindie-server-p" + str(index) + "-config -n " + config_dict[CONFIG_JOB_ID])
        cmd = ("kubectl create configmap mindie-server-p" + str(index) + FROM_FILE_CONFIG_JSON_C +
               os.path.join(out_conf_path, "config_p.json") + NAME_FLAG + config_dict[CONFIG_JOB_ID])
        logging.info("##############")
        logging.info(cmd)
        exec_cmd(cmd)
        exec_cmd(APPLY_F_D + os.path.join(out_deploy_yaml_path, "mindie_server_p" + str(index) + YAML))
    for index in range(config_dict[D_INSTANCES_NUM]):
        exec_cmd("kubectl delete configmap mindie-server-d" + str(index) + "-config -n " + config_dict[CONFIG_JOB_ID])
        cmd = ("kubectl create configmap mindie-server-d" + str(index) +
               FROM_FILE_CONFIG_JSON_C + os.path.join(out_conf_path, "config_d.json") + NAME_FLAG +
               config_dict[CONFIG_JOB_ID])
        logging.info("##############")
        logging.info(cmd)
        exec_cmd(cmd)
        exec_cmd(APPLY_F_D + os.path.join(out_deploy_yaml_path, "mindie_server_d" + str(index) + YAML))


def exec_all_kubectl_singer(config_dict, out_path):
    out_conf_path = os.path.join(out_path, 'conf')
    exec_cmd("kubectl create configmap common-env --from-literal=MINDIE_USER_HOME_PATH=/usr/local -n " +
             config_dict[CONFIG_JOB_ID])
    exec_cmd("kubectl create configmap boot-bash-script --from-file=./boot_helper/boot.sh -n " +
             config_dict[CONFIG_JOB_ID])
    exec_cmd("kubectl create configmap config-file-path --from-file=" + out_conf_path + NAME_FLAG +
             config_dict[CONFIG_JOB_ID])
    exec_cmd(
        "kubectl create configmap python-script-gen-config-single-container "
        "--from-file=./boot_helper/gen_config_single_container.py -n " + config_dict[CONFIG_JOB_ID])
    exec_cmd("kubectl apply -f " + os.path.join(out_conf_path, "deployment", "mindie_service_single_container.yaml"))


def assign_cert_files(ms_tls_config, deploy_config_tls_config, cert_type, is_controller=True):
    """
    assign cert file config by deploy_config
    :param ms_tls_config: ms config dict
    :param deploy_config_tls_config:  deploy_config
    :param cert_type: "infer"/"management"
    :param is_controller: controller format, kmc_ksf_master, kmc_ksf_standby. coordinator, kmcKsfMaster, kmcKsfStandby
    :return: none
    """
    enable = deploy_config_tls_config[TLS_ENABLE]
    if cert_type not in ['infer', 'management', 'ccae', 'cluster', 'etcd_server']:
        logging.info("Unsupported cert type, only 'infer', 'management', 'ccae', 'clusterd', 'etcd_server' supported")
    type_key = cert_type + '_tls_items'
    if enable:
        ms_tls_config[CA_CERT] = deploy_config_tls_config[type_key][CA_CERT]
        ms_tls_config[TLS_CERT] = deploy_config_tls_config[type_key][TLS_CERT]
        ms_tls_config[TLS_KEY] = deploy_config_tls_config[type_key][TLS_KEY]
        ms_tls_config[TLS_PASSWD] = deploy_config_tls_config[type_key][TLS_PASSWD]
        ms_tls_config[TLS_CRL] = deploy_config_tls_config[type_key][TLS_CRL]
        if is_controller:
            ms_tls_config[KMC_KSF_MASTER] = deploy_config_tls_config[KMC_KSF_MASTER]
            ms_tls_config[KMC_KSF_STANDBY] = deploy_config_tls_config[KMC_KSF_STANDBY]
        else:
            ms_tls_config["kmcKsfMaster"] = deploy_config_tls_config[KMC_KSF_MASTER]
            ms_tls_config["kmcKsfStandby"] = deploy_config_tls_config[KMC_KSF_STANDBY]


def update_controller_tls_info(modify_result_dict, deploy_config):
    # assign request coordinator TLS
    assign_cert_files(modify_result_dict[TLS_CONFIG]["request_coordinator_tls_items"],
                      deploy_config[TLS_CONFIG], MANAGEMENT)
    modify_result_dict[TLS_CONFIG]["request_coordinator_tls_enable"] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    # assign request server TLS
    assign_cert_files(modify_result_dict[TLS_CONFIG]["request_server_tls_items"],
                      deploy_config[TLS_CONFIG], MANAGEMENT)
    modify_result_dict[TLS_CONFIG]["request_server_tls_enable"] = deploy_config[TLS_CONFIG][TLS_ENABLE]

    # assign request http
    assign_cert_files(modify_result_dict[TLS_CONFIG]["http_server_tls_items"],
                      deploy_config[TLS_CONFIG], MANAGEMENT)
    modify_result_dict[TLS_CONFIG]["http_server_tls_enable"] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    # assign clusterD tls
    assign_cert_files(modify_result_dict[TLS_CONFIG]["cluster_tls_items"],
                      deploy_config[TLS_CONFIG], "cluster")
    modify_result_dict[TLS_CONFIG]["cluster_tls_enable"] = deploy_config[TLS_CONFIG]['cluster_tls_enable']
    # assign ccae tls
    if CCAE_TLS_ITEMS in deploy_config[TLS_CONFIG]:
        modify_result_dict[TLS_CONFIG][CCAE_TLS_ITEMS] = deploy_config[TLS_CONFIG][CCAE_TLS_ITEMS]
        modify_result_dict[TLS_CONFIG]["ccae_tls_enable"] = deploy_config[TLS_CONFIG]['ccae_tls_enable']
        assign_cert_files(modify_result_dict[TLS_CONFIG][CCAE_TLS_ITEMS],
                          deploy_config[TLS_CONFIG], "ccae")
    if ETCD_TLS_ITEMS in deploy_config[TLS_CONFIG]:
        assign_cert_files(modify_result_dict[TLS_CONFIG][ETCD_TLS_ITEMS],
                          deploy_config[TLS_CONFIG], "etcd_server")
        modify_result_dict[TLS_CONFIG]["etcd_server_tls_enable"] = deploy_config[TLS_CONFIG]['etcd_server_tls_enable']
    return modify_result_dict


def modify_controller_json(modify_config, ms_controller_json, out_json, deploy_config):
    original_config = read_json(ms_controller_json)
    modify_result_dict = update_dict(original_config, modify_config)
    modify_result_dict = update_controller_tls_info(modify_result_dict, deploy_config)
    write_json_data(modify_result_dict, out_json)


def update_coordinator_tls_info(modify_result_dict, deploy_config):
    # assign request controller TLS
    assign_cert_files(modify_result_dict[TLS_CONFIG]["controller_server_tls_items"],
                      deploy_config[TLS_CONFIG], "management", is_controller=False)
    modify_result_dict[TLS_CONFIG]["controller_server_tls_enable"] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    # assign request server TLS
    assign_cert_files(modify_result_dict[TLS_CONFIG]["request_server_tls_items"],
                      deploy_config[TLS_CONFIG], "infer", is_controller=False)
    modify_result_dict[TLS_CONFIG]["request_server_tls_enable"] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    # assign client tls
    assign_cert_files(modify_result_dict[TLS_CONFIG]["mindie_client_tls_items"],
                      deploy_config[TLS_CONFIG], "infer", is_controller=False)
    modify_result_dict[TLS_CONFIG]["mindie_client_tls_enable"] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    # assign management tls
    assign_cert_files(modify_result_dict[TLS_CONFIG]["mindie_mangment_tls_items"],
                      deploy_config[TLS_CONFIG], "management", is_controller=False)
    modify_result_dict[TLS_CONFIG]["mindie_mangment_tls_enable"] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    return modify_result_dict


def modify_coordinator_json(modify_config, ms_coordinator_json, out_json, deploy_config):
    original_config = read_json(ms_coordinator_json)
    modify_result_dict = update_dict(original_config, modify_config)
    modify_result_dict = update_coordinator_tls_info(modify_result_dict, deploy_config)
    if "coordinator_backup_cfg" in deploy_config:
        modify_result_dict["backup_config"] = deploy_config["coordinator_backup_cfg"]
    write_json_data(modify_result_dict, out_json)


def get_path_with_separator(path):
    dirname = os.path.dirname(path)
    return dirname + TLS_PATH_SEPARATOR if dirname else ""


def update_server_tls_info(modify_result_dict, deploy_config):
    # assign infer TLS
    key = "infer_tls_items"
    modify_result_dict[SERVER_CONFIG]["tlsCaPath"] = get_path_with_separator(deploy_config[TLS_CONFIG][key][CA_CERT])
    modify_result_dict[SERVER_CONFIG]["tlsCaFile"] = [os.path.basename(deploy_config[TLS_CONFIG][key][CA_CERT])]
    modify_result_dict[SERVER_CONFIG]["tlsCert"] = deploy_config[TLS_CONFIG][key][TLS_CERT]
    modify_result_dict[SERVER_CONFIG]["tlsPk"] = deploy_config[TLS_CONFIG][key][TLS_KEY]
    modify_result_dict[SERVER_CONFIG]["tlsPkPwd"] = deploy_config[TLS_CONFIG][key][TLS_PASSWD]
    modify_result_dict[SERVER_CONFIG]["tlsCrlPath"] = get_path_with_separator(deploy_config[TLS_CONFIG][key][TLS_CRL])
    modify_result_dict[SERVER_CONFIG]["tlsCrlFiles"] = [os.path.basename(deploy_config[TLS_CONFIG][key][TLS_CRL])]
    modify_result_dict[SERVER_CONFIG]["kmcKsfMaster"] = deploy_config[TLS_CONFIG]["kmc_ksf_master"]
    modify_result_dict[SERVER_CONFIG]["kmcKsfStandby"] = deploy_config[TLS_CONFIG]["kmc_ksf_standby"]
    modify_result_dict[SERVER_CONFIG]["httpsEnabled"] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    # assign management TLS
    key = MANAGEMENT_TLS_ITEMS
    modify_result_dict[SERVER_CONFIG]["managementTlsCaPath"] = get_path_with_separator(
        deploy_config[TLS_CONFIG][key][CA_CERT])
    modify_result_dict[SERVER_CONFIG]["managementTlsCaFile"] = [
        os.path.basename(deploy_config[TLS_CONFIG][key][CA_CERT])]
    modify_result_dict[SERVER_CONFIG]["managementTlsCert"] = deploy_config[TLS_CONFIG][key][TLS_CERT]
    modify_result_dict[SERVER_CONFIG]["managementTlsPk"] = deploy_config[TLS_CONFIG][key][TLS_KEY]
    modify_result_dict[SERVER_CONFIG]["managementTlsPkPwd"] = deploy_config[TLS_CONFIG][key][TLS_PASSWD]
    modify_result_dict[SERVER_CONFIG]["managementTlsCrlPath"] = get_path_with_separator(
        deploy_config[TLS_CONFIG][key][TLS_CRL])
    modify_result_dict[SERVER_CONFIG]["managementTlsCrlFiles"] = [
        os.path.basename(deploy_config[TLS_CONFIG][key][TLS_CRL])]
    # internal tls
    key = MANAGEMENT_TLS_ITEMS
    modify_result_dict[SERVER_CONFIG]["interCommTlsCaPath"] = get_path_with_separator(
        deploy_config[TLS_CONFIG][key][CA_CERT])
    modify_result_dict[SERVER_CONFIG]["interCommTlsCaFiles"] = [
        os.path.basename(deploy_config[TLS_CONFIG][key][CA_CERT])]
    modify_result_dict[SERVER_CONFIG]["interCommTlsCert"] = deploy_config[TLS_CONFIG][key][TLS_CERT]
    modify_result_dict[SERVER_CONFIG]["interCommPk"] = deploy_config[TLS_CONFIG][key][TLS_KEY]
    modify_result_dict[SERVER_CONFIG]["interCommPkPwd"] = deploy_config[TLS_CONFIG][key][TLS_PASSWD]
    modify_result_dict[SERVER_CONFIG]["interCommTlsCrlPath"] = get_path_with_separator(
        deploy_config[TLS_CONFIG][key][TLS_CRL])
    modify_result_dict[SERVER_CONFIG]["interCommTlsCrlFiles"] = [
        os.path.basename(deploy_config[TLS_CONFIG][key][TLS_CRL])]
    modify_result_dict[SERVER_CONFIG]["interCommTLSEnabled"] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    # grpc
    key = MANAGEMENT_TLS_ITEMS
    modify_result_dict[BACKEND_CONFIG]["interNodeTlsCaPath"] = get_path_with_separator(
        deploy_config[TLS_CONFIG][key][CA_CERT])
    modify_result_dict[BACKEND_CONFIG]["interNodeTlsCaFiles"] = [
        os.path.basename(deploy_config[TLS_CONFIG][key][CA_CERT])]
    modify_result_dict[BACKEND_CONFIG]["interNodeTlsCert"] = deploy_config[TLS_CONFIG][key][TLS_CERT]
    modify_result_dict[BACKEND_CONFIG]["interNodeTlsPk"] = deploy_config[TLS_CONFIG][key][TLS_KEY]
    modify_result_dict[BACKEND_CONFIG]["interNodeTlsPkPwd"] = deploy_config[TLS_CONFIG][key][TLS_PASSWD]
    modify_result_dict[BACKEND_CONFIG]["interNodeTlsCrlPath"] = get_path_with_separator(
        deploy_config[TLS_CONFIG][key][TLS_CRL])
    modify_result_dict[BACKEND_CONFIG]["interNodeTlsCrlFiles"] = [
        os.path.basename(deploy_config[TLS_CONFIG][key][TLS_CRL])]
    modify_result_dict[BACKEND_CONFIG]["interNodeKmcKsfMaster"] = deploy_config[TLS_CONFIG]["kmc_ksf_master"]
    modify_result_dict[BACKEND_CONFIG]["interNodeKmcKsfStandby"] = deploy_config[TLS_CONFIG]["kmc_ksf_standby"]
    modify_result_dict[BACKEND_CONFIG]["interNodeTLSEnabled"] = deploy_config[TLS_CONFIG][TLS_ENABLE]


def modify_http_client_json(modify_config, ms_client_ctl_json, out_json, deploy_config):
    original_config = read_json(ms_client_ctl_json)
    modify_result_dict = update_dict(original_config, modify_config)
    assign_cert_files(modify_result_dict["cert"],
                      deploy_config[TLS_CONFIG], "management")
    modify_result_dict[TLS_ENABLE] = deploy_config[TLS_CONFIG][TLS_ENABLE]
    write_json_data(modify_result_dict, out_json)


def get_config_model_name(server_config_path, singer_server_config_path):
    try:
        server_config = read_json(server_config_path)
    except OSError as reason:
        logging.info(str(reason))
        server_config = read_json(singer_server_config_path)
    return server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0]["modelName"]


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user_config_path",
        type=str,
        default="./user_config.json",
        help="Path of user config"
    )
    parser.add_argument('--conf_path', type=str, default='./conf', help="Path of conf")
    parser.add_argument("--deploy_yaml_path", type=str, default='./deployment', help="Path of yaml")
    parser.add_argument("--output_path", type=str, default="./output", help="Path of output")
    return parser.parse_args()


def update_ms_controller_config(controller_config, p_server_config, d_server_config, deploy_config):
    temp_updated = update_json_value(controller_config, "multi_node_infer_config/p_node_config/tp_size",
                                     p_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][TP])
    temp_updated = update_json_value(temp_updated, "multi_node_infer_config/p_node_config/dp_size",
                                     p_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][DP])
    temp_updated = update_json_value(controller_config, "multi_node_infer_config/p_node_config/sp_size",
                                     p_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][SP])
    temp_updated = update_json_value(controller_config, "multi_node_infer_config/p_node_config/cp_size",
                                     p_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][CP])
    temp_updated = update_json_value(temp_updated, "multi_node_infer_config/p_node_config/node_machine_num",
                                     deploy_config["single_p_instance_pod_num"])
    temp_updated = update_json_value(temp_updated, "multi_node_infer_config/p_node_config/enable_dist_dp_server",
                                     p_server_config[SERVER_CONFIG][DIST_DP_SERVER_ENABLED])

    temp_updated = update_json_value(temp_updated, "multi_node_infer_config/d_node_config/tp_size",
                                     d_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][TP])
    temp_updated = update_json_value(temp_updated, "multi_node_infer_config/d_node_config/dp_size",
                                     d_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][DP])
    temp_updated = update_json_value(controller_config, "multi_node_infer_config/d_node_config/sp_size",
                                     d_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][SP])
    temp_updated = update_json_value(controller_config, "multi_node_infer_config/d_node_config/cp_size",
                                     d_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][CP])
    temp_updated = update_json_value(temp_updated, "multi_node_infer_config/d_node_config/enable_dist_dp_server",
                                     d_server_config[SERVER_CONFIG][DIST_DP_SERVER_ENABLED])
    if d_server_config[SERVER_CONFIG][DIST_DP_SERVER_ENABLED]:
        temp_updated = update_json_value(temp_updated, "multi_node_infer_config/d_node_config/node_machine_num",
                                         d_server_config[BACKEND_CONFIG][MODEL_DEPLOY_CONFIG][MODEL_CONFIG][0][DP])
    else:
        temp_updated = update_json_value(temp_updated, "multi_node_infer_config/d_node_config/node_machine_num",
                                         deploy_config["single_d_instance_pod_num"])
    if CONTROLLER_BACKUP_CFG in deploy_config and CONTROLLER_BACKUP_SW in deploy_config[CONTROLLER_BACKUP_CFG]:
        temp_updated = update_json_value(temp_updated, "controller_backup_cfg/function_sw",
                                         deploy_config[CONTROLLER_BACKUP_CFG][CONTROLLER_BACKUP_SW])
    return temp_updated


def modify_controller_config(out_controller_config):
    out_p_server_config = read_json(ms_config_p_json)
    out_d_server_config = read_json(ms_config_d_json)
    updated = update_ms_controller_config(out_controller_config, out_p_server_config, out_d_server_config,
                                          deploy_config)
    write_json_data(updated, ms_controller_json)


def obtain_model_id(deploy_config):
    config_model_id = deploy_config[MODEL_ID].strip()
    return f"{deploy_config[CONFIG_JOB_ID]}_{datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d%H%M%S')}"


if __name__ == '__main__':

    args = parse_arguments()

    input_conf_root_path = args.conf_path
    deploy_yaml_root_path = args.deploy_yaml_path
    output_root_path = args.output_path
    user_config_path = args.user_config_path
    if not os.path.exists(output_root_path):
        os.makedirs(output_root_path)
    if not os.path.exists(os.path.join(output_root_path, "conf")):
        os.makedirs(os.path.join(output_root_path, "conf"))
    if not os.path.exists(os.path.join(output_root_path, "deployment")):
        os.makedirs(os.path.join(output_root_path, "deployment"))
    if not os.path.exists(user_config_path):
        raise FileNotFoundError(f"Configuration file not found at: '{user_config_path}'."
                                f"Please verify the path or provide a valid config file.")
    else:
        logging.info(f"Starting service deployment using config file path: {user_config_path}.")

    controller_input_yaml = os.path.join(deploy_yaml_root_path, 'controller_init.yaml')
    controller_output_yaml = os.path.join(output_root_path, 'deployment', 'mindie_ms_controller.yaml')
    coordinator_input_yaml = os.path.join(deploy_yaml_root_path, 'coordinator_init.yaml')
    coordinator_output_yaml = os.path.join(output_root_path, 'deployment', 'mindie_ms_coordinator.yaml')
    server_input_yaml = os.path.join(deploy_yaml_root_path, 'server_init.yaml')
    server_output_yaml = os.path.join(output_root_path, 'deployment', 'mindie_server')
    singer_container_input_yaml = os.path.join(deploy_yaml_root_path, 'single_container_init.yaml')
    singer_container_output_yaml = os.path.join(output_root_path, 'deployment', 'mindie_service_single_container.yaml')
    ms_controller_json = os.path.join(output_root_path, 'conf', 'ms_controller.json')
    ms_coordinator_json = os.path.join(output_root_path, 'conf', 'ms_coordinator.json')
    ms_config_p_json = os.path.join(output_root_path, 'conf', 'config_p.json')
    ms_config_d_json = os.path.join(output_root_path, 'conf', 'config_d.json')
    ms_client_ctl_json = os.path.join(output_root_path, 'conf', 'http_client_ctl.json')
    server_config_path = os.path.join(output_root_path, 'conf', 'config.json')
    init_ms_controller_json = os.path.join(input_conf_root_path, 'ms_controller.json')
    init_ms_coordinator_json = os.path.join(input_conf_root_path, 'ms_coordinator.json')
    init_ms_config_p_json = os.path.join(input_conf_root_path, 'config_p.json')
    init_ms_config_d_json = os.path.join(input_conf_root_path, 'config_d.json')
    init_ms_client_ctl_json = os.path.join(input_conf_root_path, 'http_client_ctl.json')
    init_server_config_path = os.path.join(input_conf_root_path, 'config.json')
    env_config_path = os.path.join(input_conf_root_path, 'mindie_env.json')

    json_config = read_json(user_config_path)
    deploy_config = json_config["deploy_config"]
    if "mindie_env_path" in deploy_config:
        env_config_path = deploy_config["mindie_env_path"]

    if json_config["mindie_ms_controller_config"]["deploy_mode"] == "pd_disaggregation_single_container":
        generator_yaml(singer_container_input_yaml, singer_container_output_yaml, user_config_path, False)
        exec_all_kubectl_singer(deploy_config, output_root_path)
    else:
        env_config = read_json(env_config_path)
        env_config["MODEL_ID"] = obtain_model_id(deploy_config)
        modify_controller_json(json_config["mindie_ms_controller_config"], init_ms_controller_json, ms_controller_json,
                               deploy_config)
        modify_coordinator_json(json_config["mindie_ms_coordinator_config"], init_ms_coordinator_json,
                                ms_coordinator_json, deploy_config)
        http_json = json_config["http_client_ctl_config"] if "http_client_ctl_config" in json_config else dict()
        modify_http_client_json(http_json, init_ms_client_ctl_json, ms_client_ctl_json,
                                deploy_config)
        # 非跨机不区分
        CONFIG_MODEL_NAME = get_config_model_name(ms_config_p_json, server_config_path)
        out_controller_config = read_json(ms_controller_json)
        INIT_PORT = out_controller_config["initial_dist_server_port"]
        modify_controller_config(out_controller_config)
        generator_yaml(controller_input_yaml, controller_output_yaml, user_config_path, True, env_config)
        generator_yaml(coordinator_input_yaml, coordinator_output_yaml, user_config_path, False, env_config)
        generator_yaml(server_input_yaml, server_output_yaml, user_config_path, False, env_config)

    logging.info("all deploy end.")
