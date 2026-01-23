# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.

import json
import os
import sys
import logging
from enum import Enum
from typing import Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
ENCODING_UTF8 = 'utf-8'
BASIC_CONFIG = 'basic_config'
PARALLEL_CONFIG = 'parallel_config'
PREFILL_PARALLEL_CONFIG = 'prefill_parallel_config'
DECODE_PARALLEL_CONFIG = 'decode_parallel_config'
MODEL_CONFIG = 'model_config'
ENGINE_CONFIG = 'engine_config'
PREFILL = 'prefill'
DECODE = 'decode'
MOTOR_DEPLOY_CONFIG = 'motor_deploy_config'
CA_FILE = 'ca_file'
CERT_FILE = 'cert_file'
KEY_FILE = 'key_file'
SSL_ENABLE = 'ssl_enable'
SSL_CA_CERTS = 'ssl_ca_certs'
SSL_CERTFILE = 'ssl_certfile'
SSL_KEYFILE = 'ssl_keyfile'
TLS_CONFIG = 'tls_config'
TLS_ENABLE = 'tls_enable'
INFER_TLS_CONFIG = 'infer_tls_config'
GRPC_TLS_CONFIG = 'grpc_tls_config'
ETCD_TLS_CONFIG = 'etcd_tls_config'
MGMT_TLS_CONFIG = 'mgmt_tls_config'
KV_TRANSFER_CONFIG = "kv_transfer_config"
KV_CONNECTOR_EXTRA_CONFIG = "kv_connector_extra_config"
AIGW = 'aigw'
ID = 'id'
MOTOR_ENGINE_PREFILL_CONFIG = 'motor_engine_prefill_config'
MOTOR_ENGINE_DECODE_CONFIG = 'motor_engine_decode_config'
MODEL_NAME = 'model_name'
OBJECT = 'object'
MODEL = 'model'
OWNERED_BY = 'owned_by'
MOTOR = 'motor'
MAX_MODEL_LEN = 'max_model_len'
P_MAX_SEQLEN = 'p_max_seqlen'
D_MAX_SEQLEN = 'd_max_seqlen'
SLO_TTFT = 'slo_ttft'
SLO_TPOT = 'slo_tpot'
HARDWARE_TYPE = 'hardware_type'
LOCAL_HOSTNAME = 'local_hostname'
MASTER_SERVER_ADDRESS = 'master_server_address'
MASTER_SERVER_PORT = '50088'


class ConfigKey(Enum):
    MOTOR_CONTROLLER = "motor_controller_config"
    MOTOR_COORDINATOR = "motor_coordinator_config"
    MOTOR_ENGINE_PREFILL = "motor_engine_prefill_config"
    MOTOR_ENGINE_DECODE = "motor_engine_decode_config"
    MOTOR_NODEMANAGER = "motor_nodemanger_config"
    MOTOR_KV_POOL = "kv_cache_pool_config"

    @staticmethod
    def is_valid(config_key: str) -> bool:
        return config_key in [key.value for key in ConfigKey]
    
    @staticmethod
    def get_supported_keys() -> str:
        return ", ".join([key.value for key in ConfigKey])


def update_dict(original, modified):
    """
    Recursively update the original dictionary, adding or modifying fields that 
    exist in the modified dictionary but not in the original
    :param original: The original dictionary to be modified
    :param modified: The dictionary containing modification content
    """
    for key in modified:
        # Handle existing keys
        if key in original:
            # Recursively handle nested dictionaries
            if isinstance(modified[key], dict) and isinstance(original[key], dict):
                update_dict(original[key], modified[key])
            # Update value if different
            elif original[key] != modified[key]:
                original[key] = modified[key]
        # Add new keys (including nested dictionaries)
        else:
            # Recursively create nested dictionary structure
            if isinstance(modified[key], dict):
                original[key] = {}
                update_dict(original[key], modified[key])
            # Add simple values
            else:
                original[key] = modified[key]


def update_aigw_config(updated_config, user_config_data):
    updated_aigw_config = updated_config[AIGW]
    updated_aigw_config[ID] = user_config_data[MOTOR_ENGINE_PREFILL_CONFIG][MODEL_CONFIG][MODEL_NAME]
    updated_aigw_config[OBJECT] = MODEL
    updated_aigw_config[OWNERED_BY] = MOTOR
    updated_aigw_config[P_MAX_SEQLEN] = \
        user_config_data[MOTOR_ENGINE_PREFILL_CONFIG][ENGINE_CONFIG][MAX_MODEL_LEN]
    updated_aigw_config[D_MAX_SEQLEN] = \
        user_config_data[MOTOR_ENGINE_DECODE_CONFIG][ENGINE_CONFIG][MAX_MODEL_LEN]
    if SLO_TTFT not in updated_aigw_config:
        updated_aigw_config[SLO_TTFT] = 1000
        logging.info(f"Set {SLO_TTFT}=1000, while user_config.json does not contain it.")
    if SLO_TPOT not in updated_aigw_config:
        updated_aigw_config[SLO_TPOT] = 50
        logging.info(f"Set {SLO_TPOT}=50, while user_config.json does not contain it.")


def update_config_from_user_config(config_file, user_config_file, config_key):
    """
    Update the target configuration file using a specific field from user_config.json
    :param config_file: Path to the target configuration file
    :param user_config_file: Path to user_config.json file
    :param config_key: Field name in user_config.json to use for updating
    """
    try:
        # Create directory if needed
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        # Always start with empty config
        config_data = {}
        
        with open(user_config_file, 'r', encoding=ENCODING_UTF8) as file:
            user_config_data = json.load(file)
        
        logging.info(f"Starting to update configuration file: {config_file}")
        logging.info(f"Using user_config field: {config_key}")
        
        # Check if the configuration field exists
        if config_key not in user_config_data:
            logging.warning(f"user_config.json does not contain field: {config_key}")
            return True
        
        # Get the configuration data to be updated
        update_data = user_config_data[config_key]
        
        # Update the configuration
        update_dict(config_data, update_data)
        updated_config = config_data

        try:
            # For controller and coordinator, write config directly without merge
            if config_key == ConfigKey.MOTOR_CONTROLLER.value:
                updated_config = user_config_data[config_key]
                tls_configs = [MGMT_TLS_CONFIG, ETCD_TLS_CONFIG, GRPC_TLS_CONFIG]
                _update_tls_config(tls_configs, updated_config, user_config_data)
                logging.info("Controller configuration will be written directly")
            elif config_key == ConfigKey.MOTOR_COORDINATOR.value:
                updated_config = user_config_data[config_key]
                tls_configs = [MGMT_TLS_CONFIG, INFER_TLS_CONFIG, ETCD_TLS_CONFIG]
                _update_tls_config(tls_configs, updated_config, user_config_data)
                if AIGW in updated_config:
                    update_aigw_config(updated_config, user_config_data)
                logging.info("Coordinator configuration will be written directly")
            elif config_key == ConfigKey.MOTOR_NODEMANAGER.value:
                role = os.getenv('ROLE')
                # Ensure basic_config exists
                if BASIC_CONFIG not in updated_config:
                    updated_config[BASIC_CONFIG] = {}
                # Set model_name in basic_config
                updated_config[BASIC_CONFIG][MODEL_NAME] = \
                    user_config_data[ConfigKey.MOTOR_ENGINE_PREFILL.value][MODEL_CONFIG][MODEL_NAME]
                # Set hardware_type in basic_config
                updated_config[BASIC_CONFIG][HARDWARE_TYPE] = \
                    user_config_data[MOTOR_DEPLOY_CONFIG][HARDWARE_TYPE]
                # Set parallel_config based on role
                if role == PREFILL:
                    updated_config[BASIC_CONFIG][PARALLEL_CONFIG] = \
                        user_config_data[ConfigKey.MOTOR_ENGINE_PREFILL.value][MODEL_CONFIG][PREFILL_PARALLEL_CONFIG]
                elif role == DECODE:
                    updated_config[BASIC_CONFIG][PARALLEL_CONFIG] = \
                        user_config_data[ConfigKey.MOTOR_ENGINE_DECODE.value][MODEL_CONFIG][DECODE_PARALLEL_CONFIG]
                tls_configs = [MGMT_TLS_CONFIG]
                _update_tls_config(tls_configs, updated_config, user_config_data)
            elif config_key == ConfigKey.MOTOR_ENGINE_PREFILL.value:
                updated_config[MODEL_CONFIG][DECODE_PARALLEL_CONFIG] = \
                    user_config_data[ConfigKey.MOTOR_ENGINE_DECODE.value][MODEL_CONFIG][DECODE_PARALLEL_CONFIG]
                _update_engine_server_tls_config(updated_config, user_config_data)
            elif config_key == ConfigKey.MOTOR_ENGINE_DECODE.value:
                updated_config[MODEL_CONFIG][PREFILL_PARALLEL_CONFIG] = \
                    user_config_data[ConfigKey.MOTOR_ENGINE_PREFILL.value][MODEL_CONFIG][PREFILL_PARALLEL_CONFIG]
                _update_engine_server_tls_config(updated_config, user_config_data)
            elif config_key == ConfigKey.MOTOR_KV_POOL.value:
                updated_config[LOCAL_HOSTNAME] = f"{os.getenv('POD_IP')}"
                updated_config[MASTER_SERVER_ADDRESS] = f"{os.getenv('KVP_MASTER_SERVICE')}:{MASTER_SERVER_PORT}"
        except KeyError as e:
            logging.warning(f"Failed to update {config_key} due to missing key: {str(e)}")

        # Write the updated configuration back to the file
        with open(config_file, 'w', encoding=ENCODING_UTF8) as file:
            json.dump(updated_config, file, indent=4, ensure_ascii=False)

        logging.info(f"Configuration file updated successfully: {config_file}")
        return True
        
    except Exception as e:
        logging.error(f"Failed to update configuration file: {str(e)}")
        return False


def _update_tls_config(tls_configs: list[str], updated_config: dict[Any, Any], user_config_data):
    for tls_config in tls_configs:
        updated_config[tls_config] = user_config_data[MOTOR_DEPLOY_CONFIG][TLS_CONFIG][tls_config]


def _update_engine_server_tls_config(updated_config: dict[Any, Any], user_config_data):
    updated_config[MGMT_TLS_CONFIG] = user_config_data[MOTOR_DEPLOY_CONFIG][TLS_CONFIG][MGMT_TLS_CONFIG]
    infer_tls_config = user_config_data[MOTOR_DEPLOY_CONFIG][TLS_CONFIG][INFER_TLS_CONFIG]
    updated_config[INFER_TLS_CONFIG] = infer_tls_config
    if infer_tls_config and infer_tls_config[TLS_ENABLE]:
        updated_config[ENGINE_CONFIG][SSL_KEYFILE] = infer_tls_config[KEY_FILE]
        updated_config[ENGINE_CONFIG][SSL_CERTFILE] = infer_tls_config[CERT_FILE]
        updated_config[ENGINE_CONFIG][SSL_CA_CERTS] = infer_tls_config[CA_FILE]

        engine_config = updated_config[ENGINE_CONFIG]
        if KV_TRANSFER_CONFIG not in engine_config:
            engine_config[KV_TRANSFER_CONFIG] = {}
        kv_transfer_config = engine_config[KV_TRANSFER_CONFIG]
        if KV_CONNECTOR_EXTRA_CONFIG not in kv_transfer_config:
            kv_transfer_config[KV_CONNECTOR_EXTRA_CONFIG] = {}
        kv_connector_config = kv_transfer_config[KV_CONNECTOR_EXTRA_CONFIG]
        if TLS_CONFIG not in kv_connector_config:
            kv_connector_config[TLS_CONFIG] = {}
        tls_config = kv_connector_config[TLS_CONFIG]
        tls_config[SSL_ENABLE] = True
        tls_config[SSL_KEYFILE] = infer_tls_config[KEY_FILE]
        tls_config[SSL_CERTFILE] = infer_tls_config[CERT_FILE]
        tls_config[SSL_CA_CERTS] = infer_tls_config[CA_FILE]


def main():
    if len(sys.argv) != 4:
        logging.info("Usage: python update_config_from_user_config.py <config_file> <user_config_file> <config_key>")
        logging.info("Supported config_key:")
        logging.info("  - motor_controller_config: Update motor_controller.json")
        logging.info("  - motor_coordinator_config: Update motor_coordinator.json")
        logging.info("  - motor_engine_prefill_config: Update motor_engine_decode.json")
        logging.info("  - motor_engine_decode_config: Update motor_engine_decode.json")
        logging.info("  - motor_nodemanger_config: Update motor_nodemanger.json")
        sys.exit(1)

    config_file = sys.argv[1]
    user_config_file = sys.argv[2]
    config_key = sys.argv[3]

    if not os.path.exists(user_config_file):
        logging.error(f"user_config.json file does not exist: {user_config_file}")
        sys.exit(1)

    if not ConfigKey.is_valid(config_key):
        logging.error(f"Unsupported config_key: {config_key}. Supported config_key: {ConfigKey.get_supported_keys()}")
        sys.exit(1)

    success = update_config_from_user_config(config_file, user_config_file, config_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()