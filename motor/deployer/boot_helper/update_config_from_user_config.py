# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.

import json
import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
ENCODING_UTF8 = 'utf-8'


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
    return original


def update_config_from_user_config(config_file, user_config_file, config_key):
    """
    Update the target configuration file using a specific field from user_config.json
    :param config_file: Path to the target configuration file
    :param user_config_file: Path to user_config.json file
    :param config_key: Field name in user_config.json to use for updating
    """
    try:
        # Check if config file exists, create if not
        if not os.path.exists(config_file):
            logging.info(f"Configuration file does not exist, creating: {config_file}")
            # Create directory if needed
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            # Create empty config file
            with open(config_file, 'w', encoding=ENCODING_UTF8) as file:
                json.dump({}, file, indent=4, ensure_ascii=False)
            config_data = {}
        else:
            # Read existing config file
            with open(config_file, 'r', encoding=ENCODING_UTF8) as file:
                config_data = json.load(file)
        
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
        updated_config = update_dict(config_data, update_data)
        
        # Write the updated configuration back to the file
        with open(config_file, 'w', encoding=ENCODING_UTF8) as file:
            json.dump(updated_config, file, indent=4, ensure_ascii=False)
        
        logging.info(f"Configuration file updated successfully: {config_file}")
        return True
        
    except Exception as e:
        logging.error(f"Failed to update configuration file: {str(e)}")
        return False


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
    
    # Validate config_key
    valid_keys = [
        "motor_controller_config",
        "motor_coordinator_config", 
        "motor_engine_prefill_config",
        "motor_engine_decode_config",
        "motor_nodemanger_config"
    ]
    
    if config_key not in valid_keys:
        logging.error(f"Unsupported config_key: {config_key}. Supported config_key: {', '.join(valid_keys)}")
        sys.exit(1)
    
    success = update_config_from_user_config(config_file, user_config_file, config_key)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()