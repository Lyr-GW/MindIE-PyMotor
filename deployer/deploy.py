# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.
import argparse
import os
import json
import logging
import subprocess
import uuid
import time
import yaml as ym

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define constants
P_INSTANCES_NUM = "p_instances_num"
D_INSTANCES_NUM = "d_instances_num"
CONFIG_JOB_ID = "job_id"
SINGER_P_INSTANCES_NUM = "single_p_instance_pod_num"
SINGER_D_INSTANCES_NUM = "single_d_instance_pod_num"
P_POD_NPU_NUM = "p_pod_npu_num"
D_POD_NPU_NUM = "d_pod_npu_num"
ASCEND_910_NPU_NUM = "huawei.com/Ascend910"
METADATA = "metadata"
CONTROLLER = "controller"
COORDINATOR = "coordinator"
NAMESPACE = "namespace"
NAME = "name"
ENV = "env"
SPEC = "spec"
TEMPLATE = "template"
REPLICAS = "replicas"
LABELS = "labels"
KIND = "kind"
APP = "app"
VALUE = "value"
RESOURCES = "resources"
SUBJECTS = "subjects"
DEPLOYMENT = "deployment"
DEPLOYMENT_KIND = "Deployment"
SERVICE_ACCOUNT = "ServiceAccount"
SERVICE = "Service"
CLUSTER_ROLE_BINDING = "ClusterRoleBinding"
HARDWARE_TYPE = 'hardware_type'
ANNOTATIONS = "annotations"
SP_BLOCK = "sp-block"
DATA = "data"
NAME_FLAG = " -n "
BOOT_SHELL_PATH = "./boot_helper/boot.sh"
MOTOR_COMMON_ENV = "motor_common_env"
KV_CACHE_POOL_CONFIG = "kv_cache_pool_config"
KV_POOL_PORT = "port"
KV_POOL_EVICTION_HIGH_WATERMARK_RATIO = "eviction_high_watermark_ratio"
KV_POOL_EVICTION_RATIO = "eviction_ratio"
DEFAULT_KV_POOL_PORT = 50088
KV_CONDUCTOR_CONFIG = "kv_conductor_config"
KV_CONDUCTOR_PORT = "http_server_port"
STANDBY_CONFIG = "standby_config"
MOTOR_CONTROLLER_CONFIG = "motor_controller_config"
MOTOR_COORDINATOR_CONFIG = "motor_coordinator_config"
ENABLE_MASTER_STANDBY = "enable_master_standby"
INSTANCE_NUM_ZERO = 0
INSTANCE_NUM_MAX = 16
MOTOR_CONFIG_CONFIGMAP_NAME = "motor-config"
SERVER_BASE_NAME_MAP = {
    "vllm": "vllm",
    "mindie-llm": "mindie-server",
    "sglang": "sglang"
}
LOG_PATH = "plog-path"
DEPLOY_YAML_ROOT_PATH = "./deployment"
OUTPUT_ROOT_PATH = "./output"
INFER_SERVICE_INIT_YAML = "infer_service_init.yaml"
INFER_SERVICE_OUTPUT_YAML = "infer_service.yaml"
SELECTOR = "selector"
DEPLOY_MODE_INFER_SERVICE_SET = "infer_service_set"
DEPLOY_MODE_MULTI_DEPLOYMENT_YAML = "multi_deployment"
DEPLOYMENT_BACKEND_KEY = "deployment_backend"
VALID_DEPLOYMENT_BACKENDS = (DEPLOY_MODE_INFER_SERVICE_SET, DEPLOY_MODE_MULTI_DEPLOYMENT_YAML)
MATCHLABELS = "matchLabels"
LOGGING_CONFIG = "logging_config"
HOST_LOG_DIR = "host_log_dir"
NODE_SELECTOR = "nodeSelector"

# Global variables
g_controller_service = "mindie-motor-controller-service"
g_coordinator_service = "mindie-motor-coordinator-service"
g_kv_pool_service = "kvp-master"
g_kv_conductor_service = "kv-conductor"
g_kv_pool_enabled = False
g_kv_conductor_enabled = False
g_engine_base_name = "mindie-server"
g_generate_yaml_list = []


def read_json(file_path):
    """Read JSON file"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_yaml(data, output_file, single_doc=True):
    """Write to YAML file"""
    logger.info(f"Writing YAML to {output_file}")
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        if single_doc:
            ym.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=float("inf"))
        else:
            ym.dump_all(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=float("inf"))


def load_yaml(input_yaml, single_doc):
    """Load YAML file"""
    with open(input_yaml, 'r', encoding="utf-8") as f:
        if single_doc:
            data = ym.safe_load(f)
        else:
            data = list(ym.safe_load_all(f))
    return data


def exec_cmd(command):
    """Execute command"""
    logger.info(f"Executing command: {command}")
    os.popen(command).read()


def safe_exec_cmd(command):
    """Safely execute command"""
    try:
        exec_cmd(command)
    except Exception as e:
        logger.warning(f"Command execution failed: {e}")
        raise


def run_cmd_get_output(args):
    """Run command and return stdout. args: list of command and arguments. Raises on non-zero return code."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {result.stderr or result.stdout}")
    return result.stdout.strip()


def get_baseline_config_from_configmap(job_id):
    """Get current deployed user_config from cluster ConfigMap. Returns None if CM missing or no user_config."""
    try:
        out = run_cmd_get_output(
            ["kubectl", "get", "configmap", MOTOR_CONFIG_CONFIGMAP_NAME, "-n", job_id, "-o", "json"]
        )
        data = json.loads(out)
        if DATA not in data or "user_config.json" not in data[DATA]:
            return None
        return json.loads(data[DATA]["user_config.json"])
    except (RuntimeError, json.JSONDecodeError, KeyError):
        return None


def apply_configmap(create_cmd: str):
    """Create or update a configmap by applying the generated manifest."""
    safe_exec_cmd(f"{create_cmd} --dry-run=client -o yaml | kubectl apply -f -")


def shell_escape(value):
    if not isinstance(value, str):
        return str(value)
    
    value = value.replace('\\', '\\\\')
    value = value.replace('"', '\\"')
    value = value.replace('$', '\\$')
    value = value.replace('`', '\\`')
    value = value.replace('\n', '\\n')
    value = value.replace('\r', '\\r')
    value = value.replace('\t', '\\t')
    
    return value


def update_shell_script_safely(script_path, env_config, component_key="", function_name="set_common_env"):
    all_env_vars = {}
    all_env_vars.update(env_config.get(MOTOR_COMMON_ENV, {}))
    if component_key and component_key in env_config:
        all_env_vars.update(env_config[component_key])

    with open(script_path, 'r') as f:
        lines = f.readlines()

    start_idx, end_idx = -1, -1
    for i, line in enumerate(lines):
        if line.strip().startswith(f"function {function_name}()"):
            start_idx = i
        elif start_idx != -1 and line.strip() == "}":
            end_idx = i
            break

    new_function_lines = [
        f"function {function_name}() {{\n",
        *[
            f'    export {key}="{shell_escape(value)}"\n' if isinstance(value, str) else f'    export {key}={value}\n'
            for key, value in all_env_vars.items()
        ],
        "}\n"
    ]

    if start_idx != -1 and end_idx != -1:
        new_lines = lines[:start_idx] + new_function_lines + lines[end_idx + 1:]
    else:
        new_lines = new_function_lines + ["\n"] + lines

    with open(script_path, 'w') as f:
        f.writelines(new_lines)


def generate_unique_id():
    timestamp = str(int(time.time() * 1000))
    random_part = str(uuid.uuid4()).split('-')[0]
    return f"{timestamp}{random_part}"


def update_kv_pool_enabled_flag(user_config):
    global g_kv_pool_enabled
    g_kv_pool_enabled = False

    kv_connector = user_config.get("motor_engine_prefill_config", {}).get("engine_config", {})\
                    .get("kv_transfer_config", {}).get("kv_connector", "")
    if kv_connector == "MultiConnector":
        g_kv_pool_enabled = True


def update_kv_conductor_enabled_flag(user_config):
    global g_kv_conductor_enabled
    g_kv_conductor_enabled = False

    kv_conductor_config = user_config.get("kv_conductor_config", None)
    if kv_conductor_config is None:
        return
    http_server_port = kv_conductor_config.get("http_server_port", 0)
    if http_server_port != 0:
        g_kv_conductor_enabled = True


def extract_resources(data):
    """Extract deployment, services, and RBAC resources from YAML data"""
    deployment_data = None
    service_list = []
    rbac_resources = []

    if isinstance(data, list):
        for item in data:
            if item.get(KIND) == DEPLOYMENT_KIND:
                deployment_data = item
            elif item.get(KIND) == SERVICE:
                service_list.append(item)
            else:
                # RBAC resources: ServiceAccount, ClusterRole, ClusterRoleBinding
                rbac_resources.append(item)
    else:
        deployment_data = data

    return deployment_data, service_list, rbac_resources


def set_rbac_namespace(rbac_resources, namespace):
    """Set namespace for RBAC resources"""
    for rbac_resource in rbac_resources:
        if rbac_resource.get(KIND) == SERVICE_ACCOUNT:
            rbac_resource[METADATA][NAMESPACE] = namespace
        elif rbac_resource.get(KIND) == CLUSTER_ROLE_BINDING:
            rbac_resource[METADATA][NAMESPACE] = namespace
            # Also update namespace in subjects for ServiceAccount references
            if SUBJECTS in rbac_resource:
                for subject in rbac_resource[SUBJECTS]:
                    if subject.get(KIND) == SERVICE_ACCOUNT:
                        subject[NAMESPACE] = namespace


def modify_deployment(deployment_data, deploy_config, user_config):
    """Modify deployment namespace and environment variables"""
    if not deployment_data:
        return
    
    namespace = deploy_config[CONFIG_JOB_ID]
    deployment_data[METADATA][NAMESPACE] = namespace

    container = deployment_data[SPEC][TEMPLATE][SPEC]["containers"][0]
    container["image"] = deploy_config["image_name"]

    role = CONTROLLER if CONTROLLER in deployment_data[METADATA][NAME] else COORDINATOR
    if ENV not in container:
        container[ENV] = []

    container[ENV].append({
        NAME: "ROLE",
        VALUE: role
    })

    # Generate unique job name
    uuid_spec = generate_unique_id()
    job_name = f"{deploy_config[CONFIG_JOB_ID]}-{role}-{uuid_spec}"
    deployment_data[METADATA][LABELS]["job-name"] = job_name
    container[ENV].append({
        NAME: "JOB_NAME",
        VALUE: job_name
    })

    container[ENV].extend([
        {NAME: "CONTROLLER_SERVICE", VALUE: g_controller_service},
        {NAME: "COORDINATOR_SERVICE", VALUE: g_coordinator_service}
    ])

    if g_kv_conductor_enabled:
        container[ENV].append(
            {NAME: "KV_CONDUCTOR_SERVICE", VALUE: g_kv_conductor_service}
        )

    modify_coordinator_or_controller_replicas(deployment_data, user_config, role)
    modify_log_mount(deployment_data, user_config)


def set_services_namespace(service_list, namespace):
    """Set namespace for all services"""
    for service_data in service_list:
        service_data[METADATA][NAMESPACE] = namespace


def modify_controller_or_coordinator_yaml(data, deploy_config, user_config):
    """Modify controller or coordinator YAML configuration"""
    namespace = deploy_config[CONFIG_JOB_ID]

    # Extract resources
    deployment_data, service_list, rbac_resources = extract_resources(data)

    # Set namespace for RBAC resources
    set_rbac_namespace(rbac_resources, namespace)

    # Modify deployment data
    modify_deployment(deployment_data, deploy_config, user_config)

    # Set namespace for all services
    set_services_namespace(service_list, namespace)

    container = deployment_data[SPEC][TEMPLATE][SPEC]["containers"][0]
    weight_mount_path = deploy_config.get("weight_mount_path", "/mnt/weight")
    volume = [{
        "name": "weight-mount",
        "hostPath": {
            "path": weight_mount_path
        }
    }]
    deployment_data[SPEC][TEMPLATE][SPEC]["volumes"].extend(volume)
    volume_mount = [{
        "name": "weight-mount",
        "mountPath": weight_mount_path
    }]
    container["volumeMounts"].extend(volume_mount)


def modify_coordinator_or_controller_replicas(data, user_config, role):
    #  Modify replicas based on standby_config from motor_controller_config and motor_coordinator_config
    if role == CONTROLLER:
        if MOTOR_CONTROLLER_CONFIG in user_config and \
           STANDBY_CONFIG in user_config[MOTOR_CONTROLLER_CONFIG] and \
           user_config[MOTOR_CONTROLLER_CONFIG][STANDBY_CONFIG][ENABLE_MASTER_STANDBY]:
            data[SPEC][REPLICAS] = 2
    elif role == COORDINATOR:
        if MOTOR_COORDINATOR_CONFIG in user_config and \
           STANDBY_CONFIG in user_config[MOTOR_COORDINATOR_CONFIG] and \
           user_config[MOTOR_COORDINATOR_CONFIG][STANDBY_CONFIG][ENABLE_MASTER_STANDBY]:
            data[SPEC][REPLICAS] = 2


def modify_sp_block_num(data, pd_flag, config):
    if HARDWARE_TYPE not in config or config[HARDWARE_TYPE] == "800I_A2":
        if ANNOTATIONS in data[METADATA]:
            del data[METADATA][ANNOTATIONS]
        return
    if pd_flag == "d":
        single_d_instance_pod_num = int(config[SINGER_D_INSTANCES_NUM])
        d_pod_npu_num = int(config[D_POD_NPU_NUM])
        sp_block_num = single_d_instance_pod_num * d_pod_npu_num
        data[METADATA][ANNOTATIONS][SP_BLOCK] = f"{sp_block_num}"
    elif pd_flag == "p":
        single_p_instance_pod_num = int(config[SINGER_P_INSTANCES_NUM])
        p_pod_npu_num = int(config[P_POD_NPU_NUM])
        sp_block_num = single_p_instance_pod_num * p_pod_npu_num
        data[METADATA][ANNOTATIONS][SP_BLOCK] = f"{sp_block_num}"


def update_engine_base_name(user_config):
    global g_engine_base_name
    g_engine_base_name = "mindie-server"
    engine_type = user_config.get("motor_engine_prefill_config", {}).get("engine_type", "mindie-llm")
    if engine_type in SERVER_BASE_NAME_MAP:
        g_engine_base_name = SERVER_BASE_NAME_MAP[engine_type]


def normalize_kv_cache_pool_config(user_config):
    kv_config = user_config.get(KV_CACHE_POOL_CONFIG)
    if not isinstance(kv_config, dict):
        raise ValueError(f"Missing or invalid '{KV_CACHE_POOL_CONFIG}' in user config")

    if KV_POOL_PORT not in kv_config:
        kv_config[KV_POOL_PORT] = DEFAULT_KV_POOL_PORT

    return kv_config


def normalize_kv_conductor_pool_config(user_config):
    mc_config = user_config.get(KV_CONDUCTOR_CONFIG)
    if not isinstance(mc_config, dict):
        raise ValueError(f"Missing or invalid '{KV_CONDUCTOR_CONFIG}' in user config")

    if KV_POOL_PORT not in mc_config:
        mc_config[KV_POOL_PORT] = DEFAULT_KV_POOL_PORT

    return mc_config


def gen_kv_pool_env(kv_pool_config):
    service_port = kv_pool_config.get(KV_POOL_PORT)
    missing_keys = []
    if KV_POOL_EVICTION_HIGH_WATERMARK_RATIO not in kv_pool_config:
        missing_keys.append(KV_POOL_EVICTION_HIGH_WATERMARK_RATIO)
    if KV_POOL_EVICTION_RATIO not in kv_pool_config:
        missing_keys.append(KV_POOL_EVICTION_RATIO)
    if missing_keys:
        raise ValueError(
            f"Missing required kv cache pool config: {missing_keys}. "
            f"Please configure them in '{KV_CACHE_POOL_CONFIG}'."
        )

    kv_pool_env = [
        {NAME: "KVP_MASTER_SERVICE", VALUE: g_kv_pool_service},
        {NAME: "KV_POOL_PORT", VALUE: str(service_port)},
        {NAME: "KV_POOL_EVICTION_HIGH_WATERMARK_RATIO",
            VALUE: str(kv_pool_config[KV_POOL_EVICTION_HIGH_WATERMARK_RATIO])},
        {NAME: "KV_POOL_EVICTION_RATIO", VALUE: str(kv_pool_config[KV_POOL_EVICTION_RATIO])},
    ]

    return kv_pool_env


def get_infer_role(infer_service_set, role_name):
    """Get role by name from InferServiceSet spec.template.roles."""
    roles = infer_service_set.get(SPEC, {}).get(TEMPLATE, {}).get("roles", [])
    for role in roles:
        if role.get("name") == role_name:
            return role
    return None


def set_container_env(container, env_list):
    """Append or update env vars in container."""
    if ENV not in container:
        container[ENV] = []
    existing_names = {e[NAME] for e in container[ENV] if isinstance(e, dict) and NAME in e}
    for env_item in env_list:
        name = env_item.get(NAME)
        if name not in existing_names:
            container[ENV].append(env_item)
            existing_names.add(name)


def find_infer_service_set_doc(all_docs):
    for doc in all_docs:
        if doc and doc.get(KIND) == "InferServiceSet":
            return doc
    raise ValueError("InferServiceSet document not found in infer_service_init.yaml")


def update_infer_rbac_namespace(all_docs, namespace):
    for doc in all_docs:
        if not doc:
            continue
        kind = doc.get(KIND)
        metadata = doc.setdefault(METADATA, {})
        name = metadata.get(NAME)
        if kind == SERVICE_ACCOUNT and name == "mindie-motor-controller":
            metadata[NAMESPACE] = namespace
        elif kind == CLUSTER_ROLE_BINDING and name == "mindie-controller-binding":
            metadata[NAMESPACE] = namespace
            for subj in doc.get(SUBJECTS, []):
                if isinstance(subj, dict) and subj.get("kind") == SERVICE_ACCOUNT:
                    subj[NAMESPACE] = namespace


def configure_controller_role(infer_doc, user_config, deploy_config):
    controller_role = get_infer_role(infer_doc, CONTROLLER)
    if not controller_role:
        return
    controller_role[REPLICAS] = 1
    controller_cfg = user_config.get(MOTOR_CONTROLLER_CONFIG, {})
    standby_cfg = controller_cfg.get(STANDBY_CONFIG, {})
    replicas = 2 if standby_cfg.get(ENABLE_MASTER_STANDBY) else 1
    workload_spec = controller_role.setdefault(SPEC, {})
    workload_spec[REPLICAS] = replicas
    template = workload_spec.setdefault(TEMPLATE, {})
    pod_spec = template.setdefault(SPEC, {})
    containers = pod_spec.get("containers", [])
    if not containers:
        return
    container = containers[0]
    container["image"] = deploy_config["image_name"]
    job_id = deploy_config[CONFIG_JOB_ID]
    uuid_spec = generate_unique_id()
    job_name = f"{job_id}-{CONTROLLER}-{uuid_spec}"
    set_container_env(container, [
        {NAME: "ROLE", VALUE: CONTROLLER},
        {NAME: "JOB_NAME", VALUE: job_name},
        {NAME: "CONTROLLER_SERVICE", VALUE: g_controller_service},
        {NAME: "COORDINATOR_SERVICE", VALUE: g_coordinator_service},
    ])


def configure_coordinator_role(infer_doc, user_config, deploy_config):
    coordinator_role = get_infer_role(infer_doc, COORDINATOR)
    if not coordinator_role:
        return
    coordinator_role[REPLICAS] = 1
    coord_cfg = user_config.get(MOTOR_COORDINATOR_CONFIG, {})
    standby_cfg = coord_cfg.get(STANDBY_CONFIG, {})
    replicas = 2 if standby_cfg.get(ENABLE_MASTER_STANDBY) else 1
    workload_spec = coordinator_role.setdefault(SPEC, {})
    workload_spec[REPLICAS] = replicas
    template = workload_spec.setdefault(TEMPLATE, {})
    pod_spec = template.setdefault(SPEC, {})
    containers = pod_spec.get("containers", [])
    if not containers:
        return
    container = containers[0]
    container["image"] = deploy_config["image_name"]
    job_id = deploy_config[CONFIG_JOB_ID]
    uuid_spec = generate_unique_id()
    job_name = f"{job_id}-{COORDINATOR}-{uuid_spec}"
    set_container_env(container, [
        {NAME: "ROLE", VALUE: COORDINATOR},
        {NAME: "JOB_NAME", VALUE: job_name},
        {NAME: "CONTROLLER_SERVICE", VALUE: g_controller_service},
        {NAME: "COORDINATOR_SERVICE", VALUE: g_coordinator_service},
    ])


def apply_infer_node_selector_and_sp_block(
    deploy_config, pod_spec, template, instance_key, npu_key
):
    hardware_type = deploy_config.get(HARDWARE_TYPE, "800I_A2")
    pod_spec[NODE_SELECTOR] = pod_spec.get(NODE_SELECTOR, {})
    if hardware_type == "800I_A2":
        pod_spec[NODE_SELECTOR]["accelerator-type"] = "module-910b-8"
    elif hardware_type == "800I_A3":
        pod_spec[NODE_SELECTOR]["accelerator-type"] = "module-a3-16"

    if deploy_config.get(HARDWARE_TYPE) == "800I_A3":
        single_instance = int(deploy_config.get(instance_key, 1))
        pod_npu = int(deploy_config.get(npu_key, 1))
        sp_block = single_instance * pod_npu
        metadata = template.setdefault(METADATA, {})
        annotations = metadata.setdefault(ANNOTATIONS, {})
        annotations[SP_BLOCK] = str(sp_block)


def configure_prefill_role(infer_doc, deploy_config, infer_name):
    role = get_infer_role(infer_doc, "prefill")
    if not role:
        return
    p_total, _ = obtain_engine_instance_total(deploy_config)
    single_p = int(deploy_config.get(SINGER_P_INSTANCES_NUM, 1))
    role[REPLICAS] = p_total
    workload_spec = role.setdefault(SPEC, {})
    workload_spec[REPLICAS] = single_p
    selector = workload_spec.setdefault(SELECTOR, {}).setdefault(MATCHLABELS, {})
    selector[APP] = infer_name
    template = workload_spec.setdefault(TEMPLATE, {})
    template.setdefault(METADATA, {}).setdefault(LABELS, {})[APP] = infer_name
    pod_spec = template.setdefault(SPEC, {})
    containers = pod_spec.get("containers", [])
    if not containers:
        return
    container = containers[0]
    container["image"] = deploy_config["image_name"]
    container[NAME] = infer_name
    job_id = deploy_config[CONFIG_JOB_ID]
    job_name_base = f"{job_id}-{infer_name}"
    env_items = [
        {NAME: "ROLE", VALUE: "prefill"},
        {NAME: "JOB_NAME", VALUE: job_name_base},
        {NAME: "CONTROLLER_SERVICE", VALUE: g_controller_service},
        {NAME: "COORDINATOR_SERVICE", VALUE: g_coordinator_service},
    ]
    if g_kv_pool_enabled:
        env_items.append({NAME: "KVP_MASTER_SERVICE", VALUE: g_kv_pool_service})
    set_container_env(container, env_items)
    npu_num = int(deploy_config.get(P_POD_NPU_NUM, 1))
    if RESOURCES in container:
        container[RESOURCES]["requests"][ASCEND_910_NPU_NUM] = npu_num
        container[RESOURCES]["limits"][ASCEND_910_NPU_NUM] = npu_num
    weight_path = deploy_config.get("weight_mount_path", "/mnt/weight")
    for vm in container.get("volumeMounts", []):
        if vm.get("name") == "weight-mount":
            vm["mountPath"] = weight_path
    for vol in pod_spec.get("volumes", []):
        if vol.get("name") == "weight-mount" and "hostPath" in vol:
            vol["hostPath"]["path"] = weight_path
    apply_infer_node_selector_and_sp_block(
        deploy_config, pod_spec, template, SINGER_P_INSTANCES_NUM, P_POD_NPU_NUM
    )


def configure_decode_role(infer_doc, deploy_config, infer_name):
    role = get_infer_role(infer_doc, "decode")
    if not role:
        return
    _, d_total = obtain_engine_instance_total(deploy_config)
    single_d = int(deploy_config.get(SINGER_D_INSTANCES_NUM, 1))
    role[REPLICAS] = d_total
    workload_spec = role.setdefault(SPEC, {})
    workload_spec[REPLICAS] = single_d
    selector = workload_spec.setdefault(SELECTOR, {}).setdefault(MATCHLABELS, {})
    selector[APP] = infer_name
    template = workload_spec.setdefault(TEMPLATE, {})
    template.setdefault(METADATA, {}).setdefault(LABELS, {})[APP] = infer_name
    pod_spec = template.setdefault(SPEC, {})
    containers = pod_spec.get("containers", [])
    if not containers:
        return
    container = containers[0]
    container["image"] = deploy_config["image_name"]
    container[NAME] = infer_name
    job_id = deploy_config[CONFIG_JOB_ID]
    job_name_base = f"{job_id}-{infer_name}"
    env_items = [
        {NAME: "ROLE", VALUE: "decode"},
        {NAME: "JOB_NAME", VALUE: job_name_base},
        {NAME: "CONTROLLER_SERVICE", VALUE: g_controller_service},
        {NAME: "COORDINATOR_SERVICE", VALUE: g_coordinator_service},
    ]
    if g_kv_pool_enabled:
        env_items.append({NAME: "KVP_MASTER_SERVICE", VALUE: g_kv_pool_service})
    set_container_env(container, env_items)
    npu_num = int(deploy_config.get(D_POD_NPU_NUM, 1))
    if RESOURCES in container:
        container[RESOURCES]["requests"][ASCEND_910_NPU_NUM] = npu_num
        container[RESOURCES]["limits"][ASCEND_910_NPU_NUM] = npu_num
    weight_path = deploy_config.get("weight_mount_path", "/mnt/weight")
    for vm in container.get("volumeMounts", []):
        if vm.get("name") == "weight-mount":
            vm["mountPath"] = weight_path
    for vol in pod_spec.get("volumes", []):
        if vol.get("name") == "weight-mount" and "hostPath" in vol:
            vol["hostPath"]["path"] = weight_path
    apply_infer_node_selector_and_sp_block(
        deploy_config, pod_spec, template, SINGER_D_INSTANCES_NUM, D_POD_NPU_NUM
    )


def update_infer_service_replicas_only(infer_service_yaml_path, deploy_config):
    """Update only prefill/decode instance count (role.replicas) in infer_service.yaml for scaling."""
    logger.info(f"Updating InferServiceSet instance replicas in {infer_service_yaml_path}")
    all_docs = load_yaml(infer_service_yaml_path, False)
    if not isinstance(all_docs, list):
        all_docs = [all_docs]
    infer_doc = find_infer_service_set_doc(all_docs)
    p_total, d_total = obtain_engine_instance_total(deploy_config)

    prefill_role = get_infer_role(infer_doc, "prefill")
    if prefill_role:
        prefill_role[REPLICAS] = p_total

    decode_role = get_infer_role(infer_doc, "decode")
    if decode_role:
        decode_role[REPLICAS] = d_total

    os.makedirs(os.path.dirname(infer_service_yaml_path), exist_ok=True)
    write_yaml(all_docs, infer_service_yaml_path, False)
    global g_generate_yaml_list
    g_generate_yaml_list.append(infer_service_yaml_path)


def generate_yaml_infer_service_set(input_yaml, output_file, user_config, deploy_config):
    """Generate InferServiceSet yaml from init template and user_config."""
    logger.info(f"Generating InferServiceSet YAML from {input_yaml} to {output_file}")
    all_docs = load_yaml(input_yaml, False)
    if not isinstance(all_docs, list):
        all_docs = [all_docs]
    namespace = deploy_config[CONFIG_JOB_ID]
    infer_doc = find_infer_service_set_doc(all_docs)
    infer_name = infer_doc.get(METADATA, {}).get(NAME, "mindie-server")
    update_infer_rbac_namespace(all_docs, namespace)
    infer_doc[METADATA][NAMESPACE] = namespace
    configure_controller_role(infer_doc, user_config, deploy_config)
    configure_coordinator_role(infer_doc, user_config, deploy_config)
    configure_prefill_role(infer_doc, deploy_config, infer_name)
    configure_decode_role(infer_doc, deploy_config, infer_name)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    write_yaml(all_docs, output_file, False)
    global g_generate_yaml_list
    g_generate_yaml_list.append(output_file)


def init_infer_service_domain_name(infer_service_init_yaml, deploy_config):
    """
    Set g_controller_service and g_coordinator_service for CRD InferServiceSet mode.
    CRD creates services with naming: {service_name}-{infer_service_set_name}-0-{role_name}
    """
    all_docs = load_yaml(infer_service_init_yaml, False)
    if not isinstance(all_docs, list):
        all_docs = [all_docs]
    infer_doc = find_infer_service_set_doc(all_docs)
    infer_name = infer_doc.get(METADATA, {}).get(NAME, "mindie-server")
    namespace = deploy_config[CONFIG_JOB_ID]

    def get_service_fqdn_for_role(role_name):
        role = get_infer_role(infer_doc, role_name)
        if not role:
            return None
        services = role.get("services", [])
        if not services:
            return None
        service_name = services[0].get("name", "")
        role_name_val = role.get("name", role_name)
        full_service_name = f"{service_name}-{infer_name}-0-{role_name_val}"
        return f"{full_service_name}.{namespace}.svc.cluster.local"

    global g_controller_service, g_coordinator_service
    g_controller_service = get_service_fqdn_for_role(CONTROLLER)
    g_coordinator_service = get_service_fqdn_for_role(COORDINATOR)
    if not g_controller_service or not g_coordinator_service:
        raise ValueError("Controller or coordinator role not found in infer_service_init.yaml")


def set_engine_metadata(deployment_data, deploy_config, index, node_type, job_name):
    deployment_data[METADATA][NAMESPACE] = deploy_config[CONFIG_JOB_ID]
    unique_name = f"{g_engine_base_name}-{node_type}{index}"
    deployment_data[METADATA][NAME] = unique_name
    deployment_data[METADATA][LABELS][APP] = unique_name
    deployment_data[SPEC]["selector"]["matchLabels"]["app"] = unique_name
    deployment_data[SPEC][TEMPLATE][METADATA][LABELS][APP] = unique_name
    deployment_data[METADATA][LABELS]["job-name"] = job_name


def set_engine_env(container, node_type, job_name):
    role = "prefill" if node_type == "p" else "decode"
    container[ENV].extend([
        {NAME: "ROLE", VALUE: role},
        {NAME: "JOB_NAME", VALUE: job_name},
        {NAME: "CONTROLLER_SERVICE", VALUE: g_controller_service},
        {NAME: "COORDINATOR_SERVICE", VALUE: g_coordinator_service}
    ])
    if g_kv_pool_enabled:
        container[ENV].append({NAME: "KVP_MASTER_SERVICE", VALUE: g_kv_pool_service})


def set_engine_replicas(deployment_data, deploy_config, node_type):
    instance_pod_num_key = SINGER_P_INSTANCES_NUM if node_type == "p" else SINGER_D_INSTANCES_NUM
    if instance_pod_num_key in deploy_config:
        deployment_data[SPEC]["replicas"] = int(deploy_config[instance_pod_num_key])


def set_engine_npu(container, deploy_config, node_type):
    if node_type == "p" and P_POD_NPU_NUM in deploy_config:
        npu_num = int(deploy_config[P_POD_NPU_NUM])
    elif node_type == "d" and D_POD_NPU_NUM in deploy_config:
        npu_num = int(deploy_config[D_POD_NPU_NUM])
    else:
        return
    container[RESOURCES]["requests"][ASCEND_910_NPU_NUM] = npu_num
    container[RESOURCES]["limits"][ASCEND_910_NPU_NUM] = npu_num


def set_engine_node_selector(deployment_data, deploy_config, node_type):
    modify_sp_block_num(deployment_data, node_type, deploy_config)
    hardware_type = deploy_config[HARDWARE_TYPE]
    if hardware_type == "800I_A2":
        deployment_data[SPEC][TEMPLATE][SPEC][NODE_SELECTOR]["accelerator-type"] = "module-910b-8"
    elif hardware_type == "800I_A3":
        deployment_data[SPEC][TEMPLATE][SPEC][NODE_SELECTOR]["accelerator-type"] = "module-a3-16"


def set_engine_weight_mount(deployment_data, container, deploy_config):
    weight_mount_path = deploy_config.get("weight_mount_path", "/mnt/weight")
    for volume in deployment_data[SPEC][TEMPLATE][SPEC]["volumes"]:
        if volume["name"] == "weight-mount":
            volume["hostPath"]["path"] = weight_mount_path
    for volume_mount in container["volumeMounts"]:
        if volume_mount["name"] == "weight-mount":
            volume_mount["mountPath"] = weight_mount_path


def modify_engine_yaml(deployment_data, deploy_config, user_config, index, node_type):
    container = deployment_data[SPEC][TEMPLATE][SPEC]["containers"][0]
    container["image"] = deploy_config["image_name"]
    job_name = f"{deploy_config[CONFIG_JOB_ID]}-{node_type}{index}-{generate_unique_id()}"
    set_engine_metadata(deployment_data, deploy_config, index, node_type, job_name)
    container[NAME] = g_engine_base_name
    if ENV not in container:
        container[ENV] = []
    set_engine_env(container, node_type, job_name)
    set_engine_replicas(deployment_data, deploy_config, node_type)
    set_engine_npu(container, deploy_config, node_type)
    set_engine_node_selector(deployment_data, deploy_config, node_type)
    set_engine_weight_mount(deployment_data, container, deploy_config)
    modify_log_mount(deployment_data, user_config)


def modify_log_mount(deployment_data, user_config):
    app_type = deployment_data[METADATA][NAME]
    host_log_dir = "/root/ascend/log"
    if app_type == "mindie-motor-controller":
        temp_app_config = get_json_by_path(user_config, MOTOR_CONTROLLER_CONFIG)
    elif app_type == "mindie-motor-coordinator":
        temp_app_config = get_json_by_path(user_config, MOTOR_COORDINATOR_CONFIG)
    else:
        temp_app_config = get_json_by_path(user_config, "motor_nodemanger_config")
    if temp_app_config:
        host_log_dir = get_json_by_path(temp_app_config, "logging_config.host_log_dir", "/root/ascend/log")
    for volume in deployment_data[SPEC][TEMPLATE][SPEC]["volumes"]:
        if volume["name"] == LOG_PATH:
            volume["hostPath"]["path"] = host_log_dir


def obtain_engine_instance_total(deploy_config):
    if P_INSTANCES_NUM not in deploy_config:
        raise KeyError(f"{P_INSTANCES_NUM} is required in motor_deploy_config")
    if D_INSTANCES_NUM not in deploy_config:
        raise KeyError(f"{D_INSTANCES_NUM} is required in motor_deploy_config")
    try:
        p_instances = int(deploy_config[P_INSTANCES_NUM])
        d_instances = int(deploy_config[D_INSTANCES_NUM])
    except (TypeError, ValueError) as e:
        raise ValueError(f"{P_INSTANCES_NUM} and {D_INSTANCES_NUM} must be integers") from e
    return p_instances, d_instances


def validate_instance_nums(deploy_config):
    p_total, d_total = obtain_engine_instance_total(deploy_config)
    if p_total <= INSTANCE_NUM_ZERO:
        raise ValueError(f"{P_INSTANCES_NUM} must be greater than {INSTANCE_NUM_ZERO}")
    if p_total > INSTANCE_NUM_MAX:
        raise ValueError(f"{P_INSTANCES_NUM} must not exceed {INSTANCE_NUM_MAX}")
    if d_total <= INSTANCE_NUM_ZERO:
        raise ValueError(f"{D_INSTANCES_NUM} must be greater than {INSTANCE_NUM_ZERO}")
    if d_total > INSTANCE_NUM_MAX:
        raise ValueError(f"{D_INSTANCES_NUM} must not exceed {INSTANCE_NUM_MAX}")


def strip_instance_nums(config_dict):
    cleaned = json.loads(json.dumps(config_dict))
    cleaned["motor_deploy_config"].pop(P_INSTANCES_NUM, None)
    cleaned["motor_deploy_config"].pop(D_INSTANCES_NUM, None)
    return cleaned


def validate_only_instance_changed(current_config, baseline_config):
    if strip_instance_nums(current_config) != strip_instance_nums(baseline_config):
        raise ValueError("user_config changes detected beyond instance numbers. "
                         "Only p_instances_num/d_instances_num can be modified for scaling.")


def get_deployment_backend_from_config(deploy_config):
    """Read deployment_backend from motor_deploy_config; default infer_service_set; validate value."""
    backend = deploy_config.get(DEPLOYMENT_BACKEND_KEY, DEPLOY_MODE_INFER_SERVICE_SET)
    if backend not in VALID_DEPLOYMENT_BACKENDS:
        raise ValueError(
            f"motor_deploy_config.{DEPLOYMENT_BACKEND_KEY} must be one of {list(VALID_DEPLOYMENT_BACKENDS)}, "
            f"got: {backend}"
        )
    return backend


def generate_yaml_controller_or_coordinator(input_yaml, output_file, user_config, deploy_config):
    logger.info(f"Generating YAML from {input_yaml} to {output_file}")
    data = load_yaml(input_yaml, False)
    modify_controller_or_coordinator_yaml(data, deploy_config, user_config)
    write_yaml(data, output_file, False)
    global g_generate_yaml_list
    g_generate_yaml_list.append(output_file)


def generate_yaml_engine(input_yaml, output_file, deploy_config, user_config):
    logger.info(f"Generating YAML from {input_yaml} to {output_file}")
    global g_generate_yaml_list
    p_total, d_total = obtain_engine_instance_total(deploy_config)
    for p_index in range(p_total):
        data = load_yaml(input_yaml, True)
        modify_engine_yaml(data, deploy_config, user_config, p_index, "p")
        output_file_p = output_file + "_p" + str(p_index) + ".yaml"
        write_yaml(data, output_file_p, True)
        g_generate_yaml_list.append(output_file_p)
    for d_index in range(d_total):
        data = load_yaml(input_yaml, True)
        modify_engine_yaml(data, deploy_config, user_config, d_index, "d")
        output_file_d = output_file + "_d" + str(d_index) + ".yaml"
        write_yaml(data, output_file_d, True)
        g_generate_yaml_list.append(output_file_d)


def generate_yaml_kv_pool(input_yaml, output_file, deploy_config, kv_pool_config):
    logger.info(f"Generating YAML from {input_yaml} to {output_file}")
    data = load_yaml(input_yaml, False)
    # Modify deployment data
    deployment_data = data[0]
    deployment_data[METADATA][NAMESPACE] = deploy_config[CONFIG_JOB_ID]

    container = deployment_data[SPEC][TEMPLATE][SPEC]["containers"][0]
    container["image"] = deploy_config["image_name"]

    if ENV not in container:
        container[ENV] = []

    service_port = kv_pool_config.get(KV_POOL_PORT)

    kv_pool_env = gen_kv_pool_env(kv_pool_config)
    container[ENV].extend(kv_pool_env)

    # Modify service data
    service_data = data[1]
    service_data[METADATA][NAMESPACE] = deploy_config[CONFIG_JOB_ID]
    ports = service_data.get(SPEC, {}).get("ports", [])
    if not ports:
        raise ValueError(
            "Missing required service ports in 'kv_pool_init.yaml'. "
            "Please configure spec.ports for KV pool service."
        )
    ports[0]["port"] = service_port
    ports[0]["targetPort"] = service_port

    write_yaml(data, output_file, False)
    global g_generate_yaml_list
    g_generate_yaml_list.append(output_file)



def generate_yaml_kv_conductor(input_yaml, output_file, deploy_config, kv_conductor_config):
    logger.info(f"Generating YAML from {input_yaml} to {output_file}")
    data = load_yaml(input_yaml, False)

    # Extract resources
    deployment_data, service_list, rbac_resources = extract_resources(data)

    # Modify deployment data
    deployment_data[METADATA][NAMESPACE] = deploy_config[CONFIG_JOB_ID]

    container = deployment_data[SPEC][TEMPLATE][SPEC]["containers"][0]
    container["image"] = deploy_config["image_name"]

    if ENV not in container:
        container[ENV] = []

    # Set namespace for all services
    set_services_namespace(service_list, deploy_config[CONFIG_JOB_ID])

    service_port = kv_conductor_config.get(KV_CONDUCTOR_PORT)

    ports = service_list[0].get(SPEC, {}).get("ports", [])
    if not ports:
        raise ValueError(
            "Missing required service ports in 'kv_pool_init.yaml'. "
            "Please configure spec.ports for KV pool service."
        )
    ports[0]["port"] = service_port
    ports[0]["targetPort"] = service_port

    kv_pool_env = [
        {NAME: "KVP_MASTER_SERVICE", VALUE: g_kv_pool_service}
    ]
    container[ENV].extend(kv_pool_env)

    write_yaml(data, output_file, False)
    global g_generate_yaml_list
    g_generate_yaml_list.append(output_file)


def init_service_domain_name(controller_input_yaml, coordinator_input_yaml, kv_pool_input_yaml, kv_conductor_input_yaml,
                             deploy_config):

    controller_data = load_yaml(controller_input_yaml, False)
    coordinator_data = load_yaml(coordinator_input_yaml, False)
    kv_pull_data = load_yaml(kv_pool_input_yaml, False)
    kv_conductor_data = load_yaml(kv_conductor_input_yaml, False)

    # Find Service resource from controller data
    controller_service_data = None
    for doc in controller_data:
        if doc.get(KIND) == SERVICE:
            controller_service_data = doc
            break

    # Find first Service resource from coordinator data
    coordinator_service_data = None
    for doc in coordinator_data:
        if doc.get(KIND) == SERVICE:
            coordinator_service_data = doc
            break

    # Find Service resource from kv_pool data
    kv_pull_service_data = None
    for doc in kv_pull_data:
        if doc.get(KIND) == SERVICE:
            kv_pull_service_data = doc
            break

    # Find Service resource from kv_pool data
    kv_conductor_service_data = None
    for doc in kv_conductor_data:
        if doc.get(KIND) == SERVICE:
            kv_conductor_service_data = doc
            break

    global g_controller_service
    controller_name = controller_service_data[METADATA][NAME]
    g_controller_service = f"{controller_name}.{deploy_config[CONFIG_JOB_ID]}.svc.cluster.local"
    global g_coordinator_service
    coordinator_name = coordinator_service_data[METADATA][NAME]
    g_coordinator_service = f"{coordinator_name}.{deploy_config[CONFIG_JOB_ID]}.svc.cluster.local"
    global g_kv_pool_service
    kv_pool_name = kv_pull_service_data[METADATA][NAME]
    g_kv_pool_service = f"{kv_pool_name}.{deploy_config[CONFIG_JOB_ID]}.svc.cluster.local"
    global g_kv_conductor_service
    kv_pool_name = kv_conductor_service_data[METADATA][NAME]
    g_kv_conductor_service = f"{kv_pool_name}.{deploy_config[CONFIG_JOB_ID]}.svc.cluster.local"



def elastic_distributed_engine_deploy(deploy_config, baseline_deploy_config, out_deploy_yaml_path):
    scale_engine_by_type(deploy_config, baseline_deploy_config, out_deploy_yaml_path, "p")
    scale_engine_by_type(deploy_config, baseline_deploy_config, out_deploy_yaml_path, "d")
    logger.info("Engine scale done.")


def scale_engine_by_type(deploy_config, baseline_deploy_config, out_deploy_yaml_path, node_type):
    job_id = deploy_config[CONFIG_JOB_ID]
    totals = obtain_engine_instance_total(deploy_config)
    bases = obtain_engine_instance_total(baseline_deploy_config)
    total = totals[0] if node_type == "p" else totals[1]
    base = bases[0] if node_type == "p" else bases[1]
    if total < base:
        logger.info(f"Scale-in {node_type} instance, {base} -> {total}")
        for index in reversed(range(total, base)):
            yaml_path = os.path.join(out_deploy_yaml_path, f"{g_engine_base_name}_{node_type}{index}.yaml")
            safe_exec_cmd(f"kubectl delete -f {yaml_path} -n {job_id}")
            if os.path.exists(yaml_path):
                os.remove(yaml_path)
    if total > base:
        logger.info(f"Scale-out {node_type} instance, {base} -> {total}")
        for index in range(base, total):
            yaml_path = os.path.join(out_deploy_yaml_path, f"{g_engine_base_name}_{node_type}{index}.yaml")
            safe_exec_cmd(f"kubectl apply -f {yaml_path} -n {job_id}")


def exec_all_kubectl_multi(
    deploy_config, baseline_config, user_config_path, deployment_backend=DEPLOY_MODE_INFER_SERVICE_SET
):
    job_id = deploy_config[CONFIG_JOB_ID]
    out_deploy_yaml_path = os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT)
    create_motor_config_configmap(job_id, user_config_path)

    if baseline_config is None or deployment_backend == DEPLOY_MODE_INFER_SERVICE_SET:
        for yaml_file in g_generate_yaml_list:
            safe_exec_cmd(f"kubectl apply -f {yaml_file} -n {job_id}")
    else:
        baseline_deploy_config = baseline_config.get("motor_deploy_config", {})
        elastic_distributed_engine_deploy(deploy_config, baseline_deploy_config, out_deploy_yaml_path)


def get_json_by_path(data, path, default=None):
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current


def set_env_to_shell(deploy_config, user_config):
    env_config_path = deploy_config.get("env_path", "./conf/env.json")
    if os.path.exists(env_config_path):
        env_config = read_json(env_config_path)

        # Extract and add engine_type and model_name from user_config
        engine_type = get_json_by_path(user_config, "motor_engine_prefill_config.engine_type", "Unknown")
        model_name = get_json_by_path(user_config, "motor_engine_prefill_config.model_config.model_name", "Unknown")
        north_platform = get_json_by_path(user_config, "north_config.name")

        # Add to motor_common_env if not already present
        if MOTOR_COMMON_ENV not in env_config:
            env_config[MOTOR_COMMON_ENV] = {}

        env_config[MOTOR_COMMON_ENV]["ENGINE_TYPE"] = engine_type
        logger.info(f"Set ENGINE_TYPE environment variable to: {engine_type}")

        env_config[MOTOR_COMMON_ENV]["MODEL_NAME"] = model_name
        logger.info(f"Set MODEL_NAME environment variable to: {model_name}")

        env_config[MOTOR_COMMON_ENV]["NORTH_PLATFORM"] = north_platform
        logger.info(f"Set NORTH_PLATFORM environment variable to: {north_platform}")

        update_shell_script_safely(BOOT_SHELL_PATH, env_config, MOTOR_COMMON_ENV, "set_common_env")
        update_shell_script_safely(BOOT_SHELL_PATH, env_config, "motor_controller_env", "set_controller_env")
        update_shell_script_safely(BOOT_SHELL_PATH, env_config, "motor_coordinator_env", "set_coordinator_env")
        update_shell_script_safely(BOOT_SHELL_PATH, env_config, "motor_engine_prefill_env", "set_prefill_env")
        update_shell_script_safely(BOOT_SHELL_PATH, env_config, "motor_engine_decode_env", "set_decode_env")
        update_shell_script_safely(BOOT_SHELL_PATH, env_config, "motor_kv_cache_pool_env", "set_kv_pool_env")
        update_shell_script_safely(BOOT_SHELL_PATH, env_config, "motor_kv_conductor_env", "set_kv_conductor_env")


def create_motor_config_configmap(job_id, user_config_path):
    """Create or update ConfigMap motor-config with all mounted files (scripts + user_config.json)."""
    if not os.path.exists(user_config_path):
        raise FileNotFoundError(f"user_config file not found: {user_config_path}")
    apply_configmap(
        f"kubectl create configmap {MOTOR_CONFIG_CONFIGMAP_NAME} "
        "--from-file=./boot_helper/boot.sh "
        "--from-file=./boot_helper/hccl_tools.py "
        "--from-file=./boot_helper/update_kv_cache_pool_config.py "
        "--from-file=./boot_helper/update_kv_conductor_config.py "
        "--from-file=./probe/probe.sh "
        "--from-file=./probe/probe.py "
        f"--from-file=user_config.json={user_config_path}"
        + NAME_FLAG + job_id
    )


def generate_yaml_single_container(input_yaml, output_file, user_config):
    logger.info(f"Generating YAML from {input_yaml} to {output_file}")
    data = load_yaml(input_yaml, False)

    deploy_config = user_config["motor_deploy_config"]

    # Modify deployment data
    job_id = deploy_config[CONFIG_JOB_ID]

    deployment_data = data[0] if isinstance(data, list) else data
    app_name = f"{job_id}-single-container"
    deployment_data[METADATA][NAME] = app_name
    deployment_data[METADATA][LABELS][APP] = app_name
    deployment_data[SPEC][SELECTOR][MATCHLABELS][APP] = app_name
    deployment_data[SPEC][TEMPLATE][METADATA][LABELS][APP] = app_name
    deployment_data[METADATA][NAMESPACE] = deploy_config[CONFIG_JOB_ID]

    container = deployment_data[SPEC][TEMPLATE][SPEC]["containers"][0]
    container["image"] = deploy_config["image_name"]

    # Modify service data
    service_data = data[1]
    service_data[METADATA][NAME] = f"{job_id}-coordinator-service"
    service_data[METADATA][LABELS][APP] = app_name
    service_data[METADATA][NAMESPACE] = deploy_config[CONFIG_JOB_ID]
    service_data['spec']['selector']['app'] = app_name

    external_service_data = data[2]
    external_service_data[METADATA][NAMESPACE] = deploy_config[CONFIG_JOB_ID]
    external_service_data[METADATA][LABELS][APP] = f"{job_id}-coordinator-infer"
    external_service_data[METADATA][LABELS][APP] = app_name
    external_service_data['spec']['selector']['app'] = app_name

    if ENV not in container:
        container[ENV] = []
    role = "SINGLE_CONTAINER"
    uuid_spec = generate_unique_id()
    job_name = f"{deploy_config[CONFIG_JOB_ID]}-{role}-{uuid_spec}"
    container[ENV].extend([
        {NAME: "ROLE", VALUE: role},
        {NAME: "JOB_NAME", VALUE: job_name},
    ])
    if g_kv_pool_enabled:
        kv_pool_config = normalize_kv_cache_pool_config(user_config)
        kv_pool_env = gen_kv_pool_env(kv_pool_config)
        container[ENV].extend(kv_pool_env)

    npu_num = int(deploy_config[P_POD_NPU_NUM]) * int(deploy_config[P_INSTANCES_NUM]) + \
            int(deploy_config[D_POD_NPU_NUM]) * int(deploy_config[D_INSTANCES_NUM])
    container[RESOURCES]["requests"][ASCEND_910_NPU_NUM] = npu_num
    container[RESOURCES]["limits"][ASCEND_910_NPU_NUM] = npu_num

    hardware_type = deploy_config[HARDWARE_TYPE]
    if hardware_type == "800I_A2":
        deployment_data[SPEC][TEMPLATE][SPEC][NODE_SELECTOR]["accelerator-type"] = "module-910b-8"
        del deployment_data[METADATA][ANNOTATIONS]
    elif hardware_type == "800I_A3":
        deployment_data[SPEC][TEMPLATE][SPEC][NODE_SELECTOR]["accelerator-type"] = "module-a3-16"
        deployment_data[METADATA][ANNOTATIONS][SP_BLOCK] = f"{npu_num}"

    weight_mount_path = deploy_config.get("weight_mount_path", "/mnt/weight")
    for volume in deployment_data[SPEC][TEMPLATE][SPEC]["volumes"]:
        if volume["name"] == "weight-mount":
            volume["hostPath"]["path"] = weight_mount_path
    for volume_mount in container["volumeMounts"]:
        if volume_mount["name"] == "weight-mount":
            volume_mount["mountPath"] = weight_mount_path

    write_yaml(data, output_file, False)


def exec_all_kubectl_singer(deploy_config, user_config_path, yaml_file):
    job_id = deploy_config[CONFIG_JOB_ID]
    create_motor_config_configmap(job_id, user_config_path)

    # Apply yaml
    safe_exec_cmd(f"kubectl apply -f {yaml_file} -n {job_id}")


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user_config_path",
        type=str,
        default="./user_config.json",
        help="Path of user config"
    )
    parser.add_argument(
        "--update_config",
        action="store_true",
        help="Only refresh configmap without applying deployments"
    )
    parser.add_argument(
        "--update_instance_num",
        action="store_true",
        help="Scale instances by comparing ConfigMap baseline with current user_config"
    )
    parser.add_argument(
        "--single_container_yaml_file",
        type=str,
        default="mindie_service_single_container.yaml",
        help="Path of init yaml for single container deployment"
    )
    return parser.parse_args()


def handle_update_config(deploy_config, user_config_path):
    baseline_config = get_baseline_config_from_configmap(deploy_config[CONFIG_JOB_ID])
    if baseline_config is None:
        raise FileNotFoundError("ConfigMap motor-config not found or has no user_config in cluster. "
                                "Please deploy once before updating configmap.")
    baseline_deploy = baseline_config["motor_deploy_config"]
    if (deploy_config.get(P_INSTANCES_NUM) != baseline_deploy.get(P_INSTANCES_NUM)
            or deploy_config.get(D_INSTANCES_NUM) != baseline_deploy.get(D_INSTANCES_NUM)):
        raise ValueError(
            "P/D instance count in user_config differs from the deployed baseline. "
            "Use --update_instance_num to scale instances instead of --update_config."
        )
    baseline_backend = baseline_deploy.get(DEPLOYMENT_BACKEND_KEY, DEPLOY_MODE_INFER_SERVICE_SET)
    current_backend = deploy_config.get(DEPLOYMENT_BACKEND_KEY, DEPLOY_MODE_INFER_SERVICE_SET)
    if baseline_backend != current_backend:
        raise ValueError(
            f"motor_deploy_config.{DEPLOYMENT_BACKEND_KEY} cannot be changed when updating config. "
            f"Current deployment uses '{baseline_backend}', user_config has '{current_backend}'."
        )
    create_motor_config_configmap(deploy_config[CONFIG_JOB_ID], user_config_path)
    logger.info("Configmap refreshed.")


def handle_update_instance_num(user_config, deploy_config, user_config_path):
    baseline_config = get_baseline_config_from_configmap(deploy_config[CONFIG_JOB_ID])
    if baseline_config is None:
        raise FileNotFoundError("ConfigMap motor-config not found. "
                                "Please deploy once before scaling.")
    validate_only_instance_changed(user_config, baseline_config)

    baseline_deploy = baseline_config.get("motor_deploy_config", {})
    deployment_backend = get_deployment_backend_from_config(baseline_deploy)

    update_kv_pool_enabled_flag(user_config)
    update_engine_base_name(user_config)

    if deployment_backend == DEPLOY_MODE_INFER_SERVICE_SET:
        infer_output = os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT, INFER_SERVICE_OUTPUT_YAML)
        infer_input = os.path.join(DEPLOY_YAML_ROOT_PATH, INFER_SERVICE_INIT_YAML)
        if os.path.exists(infer_output):
            update_infer_service_replicas_only(infer_output, deploy_config)
        else:
            if not os.path.exists(infer_input):
                raise FileNotFoundError(f"InferServiceSet init yaml not found: {infer_input}.")
            init_service_domain_name(
                os.path.join(DEPLOY_YAML_ROOT_PATH, 'controller_init.yaml'),
                os.path.join(DEPLOY_YAML_ROOT_PATH, 'coordinator_init.yaml'),
                os.path.join(DEPLOY_YAML_ROOT_PATH, 'kv_pool_init.yaml'),
                deploy_config
            )
            init_infer_service_domain_name(infer_input, deploy_config)
            generate_yaml_infer_service_set(infer_input, infer_output, user_config, deploy_config)
    else:
        engine_input_yaml = os.path.join(DEPLOY_YAML_ROOT_PATH, 'engine_init.yaml')
        engine_output_yaml = os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT, g_engine_base_name)
        generate_yaml_engine(engine_input_yaml, engine_output_yaml, deploy_config, user_config)

    exec_all_kubectl_multi(deploy_config, baseline_config, user_config_path, deployment_backend)
    logger.info("instance num update end.")


def get_deploy_paths(single_container_yaml_file):
    return {
        "controller_input_yaml": os.path.join(DEPLOY_YAML_ROOT_PATH, 'controller_init.yaml'),
        "controller_output_yaml": os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT, 'mindie_motor_controller.yaml'),
        "coordinator_input_yaml": os.path.join(DEPLOY_YAML_ROOT_PATH, 'coordinator_init.yaml'),
        "coordinator_output_yaml": os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT, 'mindie_motor_coordinator.yaml'),
        "engine_input_yaml": os.path.join(DEPLOY_YAML_ROOT_PATH, 'engine_init.yaml'),
        "engine_output_yaml": os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT, g_engine_base_name),
        "kv_pool_input_yaml": os.path.join(DEPLOY_YAML_ROOT_PATH, 'kv_pool_init.yaml'),
        "kv_pool_output_yaml": os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT, 'mindie_ms_kv_pool.yaml'),
        "infer_service_input_yaml": os.path.join(DEPLOY_YAML_ROOT_PATH, INFER_SERVICE_INIT_YAML),
        "infer_service_output_yaml": os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT, INFER_SERVICE_OUTPUT_YAML),
        "singer_container_input_yaml": os.path.join(DEPLOY_YAML_ROOT_PATH, single_container_yaml_file),
        "singer_container_output_yaml": os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT,
                                                     'mindie_motor_single_container.yaml'),
        "kv_conductor_input_yaml": os.path.join(DEPLOY_YAML_ROOT_PATH, 'kv_conductor.yaml'),
        "kv_conductor_output_yaml": os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT, 'mindie_ms_kv_conductor.yaml')
    }


def deploy_services_multi_yaml(paths, user_config, deploy_config, user_config_path):
    init_service_domain_name(
        paths["controller_input_yaml"], paths["coordinator_input_yaml"],
        paths["kv_pool_input_yaml"], paths["kv_conductor_input_yaml"], deploy_config
    )
    generate_yaml_controller_or_coordinator(
        paths["controller_input_yaml"], paths["controller_output_yaml"], user_config, deploy_config
    )
    generate_yaml_controller_or_coordinator(
        paths["coordinator_input_yaml"], paths["coordinator_output_yaml"], user_config, deploy_config
    )
    generate_yaml_engine(paths["engine_input_yaml"], paths["engine_output_yaml"], deploy_config, user_config)
    if g_kv_pool_enabled:
        kv_pool_config = normalize_kv_cache_pool_config(user_config)
        generate_yaml_kv_pool(
            paths["kv_pool_input_yaml"], paths["kv_pool_output_yaml"], deploy_config, kv_pool_config
        )
    if g_kv_conductor_enabled:
        kv_conductor_config = normalize_kv_conductor_pool_config(user_config)
        generate_yaml_kv_conductor(
            paths["kv_conductor_input_yaml"], paths["kv_conductor_output_yaml"],
            deploy_config, kv_conductor_config
        )
    exec_all_kubectl_multi(deploy_config, None, user_config_path, DEPLOY_MODE_MULTI_DEPLOYMENT_YAML)



def deploy_services_infer_service_set(paths, user_config, deploy_config, user_config_path):
    init_service_domain_name(
        paths["controller_input_yaml"], paths["coordinator_input_yaml"],
        paths["kv_pool_input_yaml"], paths["kv_conductor_input_yaml"], deploy_config
    )
    infer_input = paths["infer_service_input_yaml"]
    if not os.path.exists(infer_input):
        raise FileNotFoundError(
            f"InferServiceSet init yaml not found: {infer_input}. "
            "Please ensure infer_service_init.yaml exists in deployment folder."
        )
    init_infer_service_domain_name(infer_input, deploy_config)
    generate_yaml_infer_service_set(
        infer_input, paths["infer_service_output_yaml"], user_config, deploy_config
    )
    exec_all_kubectl_multi(deploy_config, None, user_config_path, DEPLOY_MODE_INFER_SERVICE_SET)


def deploy_services(user_config, deploy_config, user_config_path, single_container_yaml_file):
    update_kv_pool_enabled_flag(user_config)
    update_kv_conductor_enabled_flag(user_config)
    update_engine_base_name(user_config)
    set_env_to_shell(deploy_config, user_config)

    deployment_backend = get_deployment_backend_from_config(deploy_config)
    paths = get_deploy_paths(single_container_yaml_file)

    deploy_mode = user_config["motor_coordinator_config"].get("scheduler_config", {}).get("deploy_mode", "")
    if deploy_mode == "pd_disaggregation_single_container":
        update_kv_pool_enabled_flag(user_config)

        generate_yaml_single_container(paths["singer_container_input_yaml"],
                                       paths["singer_container_output_yaml"], user_config)
        exec_all_kubectl_singer(deploy_config, user_config_path, paths["singer_container_output_yaml"])
    elif deployment_backend == DEPLOY_MODE_INFER_SERVICE_SET:
        deploy_services_infer_service_set(paths, user_config, deploy_config, user_config_path)
    else:
        deploy_services_multi_yaml(paths, user_config, deploy_config, user_config_path)

    logger.info("all deploy end.")


def main():
    args = parse_arguments()

    user_config_path = args.user_config_path
    single_container_yaml_file = args.single_container_yaml_file
    
    os.makedirs(OUTPUT_ROOT_PATH, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_ROOT_PATH, DEPLOYMENT), exist_ok=True)
    
    logger.info(f"Starting service deployment using config file path: {user_config_path}.")

    user_config = read_json(user_config_path)
    deploy_config = user_config["motor_deploy_config"]
    validate_instance_nums(deploy_config)

    if args.update_config:
        handle_update_config(deploy_config, user_config_path)
        return
    if args.update_instance_num:
        handle_update_instance_num(user_config, deploy_config, user_config_path)
        return

    deploy_services(user_config, deploy_config, user_config_path, single_container_yaml_file)


if __name__ == '__main__':
    main()
