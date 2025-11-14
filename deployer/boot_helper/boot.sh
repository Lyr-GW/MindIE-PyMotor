#!/bin/bash
set_common_env

# Read environment variable role to determine node type
echo "Current node role: ROLE=$ROLE"

# Search for libjemalloc.so.2 in /usr directory
jemalloc_path=$(find /usr -type f -name "libjemalloc.so.2" 2>/dev/null | head -n 1)
if [[ -n "$jemalloc_path" ]]; then
    export LD_PRELOAD="${jemalloc_path}:${LD_PRELOAD}"
    echo "jemalloc found at: $jemalloc_path"
    echo "LD_PRELOAD is set successfully."
else
    echo "Warning: libjemalloc.so.2 not found under /usr"
    echo "Please make sure jemalloc is installed."
fi

# Define configuration file paths
CONFIG_DIR="$INSTALL_PATH/conf"
RANKTABLE_DIR="$INSTALL_PATH/conf"
USER_CONFIG_FILE="$CONFIG_FROM_CONFIGMAP_PATH/user_config.json"

# Load environment variables
source $INSTALL_PATH/set_env.sh

# Set library and python paths
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$INSTALL_PATH/lib"
export PYTHONPATH="$INSTALL_PATH/bin:$PYTHONPATH"

# Core dump settings
if [ "$SAVE_CORE_DUMP_FILE_ENABLE" = "1" ]; then
    ulimit -c 31457280        # 31457280KB = 30G
    mkdir -p /var/coredump
    chmod 700 /var/coredump
    sysctl -w kernel.core_pattern=/var/coredump/core.%e.%p.%t
else
    ulimit -c 0
fi

cd "$INSTALL_PATH"

if [ "$ROLE" = "prefill" ] || [ "$ROLE" = "decode" ]; then
    # Update configuration files based on user configuration
    echo "Updating nodemanager configuration file..."
    python3 "$CONFIG_FROM_CONFIGMAP_PATH/update_config_from_user_config.py" "$CONFIG_DIR/motor_nodemanger.json" "$USER_CONFIG_FILE" "motor_nodemanger_config"
    if [ "$ROLE" == "prefill" ]; then
        echo "Updating prefill server configuration file..."
        python3 "$CONFIG_FROM_CONFIGMAP_PATH/update_config_from_user_config.py" "$CONFIG_DIR/motor_engine_prefill.json" "$USER_CONFIG_FILE" "motor_engine_prefill_config"
    elif [ "$ROLE" == "decode" ]; then
        echo "Updating decode server configuration file..."
        python3 "$CONFIG_FROM_CONFIGMAP_PATH/update_config_from_user_config.py" "$CONFIG_DIR/motor_engine_decode.json" "$USER_CONFIG_FILE" "motor_engine_decode_config"
    fi

    # Use hccl_tools.py to generate ranktable.json
    if [ -f "$CONFIG_FROM_CONFIGMAP_PATH/hccl_tools.py" ]; then
        echo "Using hccl_tools.py to generate ranktable.json..."
        export RANKTABLE_PATH="$RANKTABLE_DIR/ranktable.json"
        PYTHONUNBUFFERED=1 python3 "$CONFIG_FROM_CONFIGMAP_PATH/hccl_tools.py" \
            --rank_table_path "$RANKTABLE_PATH"
        echo "Ranktable generated successfully: $RANKTABLE_PATH"
    else
        echo "hccl_tools.py does not exist, skip ranktable generation"
    fi

    # Set environment variables for CANN
    export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/Ascend/driver/lib64/driver:/usr/local/Ascend/driver/lib64/common"
    source "$CANN_INSTALL_PATH/ascend-toolkit/set_env.sh"
    source "$CANN_INSTALL_PATH/nnal/atb/set_env.sh"

    # Set Common environment variables for PD
    export MIES_CONTAINER_IP="$POD_IP"
    export MIES_CONTAINER_MANAGEMENT_IP="$POD_IP"

    # Set log and work paths
    if [ -n "$MINDIE_LOG_CONFIG_PATH" ] && [ -n "$MODEL_NAME" ] && [ -n "$MODEL_ID" ]; then
        chmod 750 "$MINDIE_LOG_CONFIG_PATH"
        if [ ! -d "$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID" ];then
            mkdir -p -m 750 "$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID"
        fi
        if [ ! -d "$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/mindie" ];then
            mkdir -p -m 750 "$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/mindie"
        fi
        if [ ! -d "$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/ascend_work_path" ];then
            mkdir -p -m 750 "$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/ascend_work_path"
        fi
        if [ ! -d "$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/ascend_cache_path" ];then
            mkdir -p -m 750 "$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/ascend_cache_path"
        fi
        export MINDIE_LOG_PATH="$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/mindie"
        export ASCEND_WORK_PATH="$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/ascend_work_path"
        export ASCEND_CACHE_PATH="$MINDIE_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/ascend_cache_path"
    fi

    # Set role-specific environment variables
    if [ "$ROLE" = "decode" ]; then
        set_decode_env
    elif [ "$ROLE" = "prefill" ]; then
        set_prefill_env
    fi

    # Nodemanager start command
    python3 -m motor.node_manager.main &
    pid=$!
    echo "pull up $ROLE instance"
    
    wait $pid
    exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "Error: mindie daemon exited with code $exit_code"
        exit 1
    fi
    echo "All processes finished successfully."
    exit 0
fi

if [ "$ROLE" = "controller" ]; then
    echo "Updating controller configuration file..."
    python3 "$CONFIG_FROM_CONFIGMAP_PATH/update_config_from_user_config.py" "$CONFIG_DIR/motor_controller.json" "$USER_CONFIG_FILE" "motor_controller_config"
    
    if [ -n "$CONTROLLER_LOG_CONFIG_PATH" ] && [ -n "$MODEL_NAME" ] && [ -n "$MODEL_ID" ]; then
        chmod 750 "$CONTROLLER_LOG_CONFIG_PATH"
        if [ ! -d "$CONTROLLER_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID" ];then
            mkdir -p -m 750 "$CONTROLLER_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID"
        fi
        export MINDIE_LOG_PATH="$CONTROLLER_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/mindie"
    fi
    set_controller_env

    # Controller start command
    python3 -m motor.controller.main
fi

if [ "$ROLE" == "coordinator" ]; then
    echo "Updating coordinator configuration file..."
    python3 "$CONFIG_FROM_CONFIGMAP_PATH/update_config_from_user_config.py" "$CONFIG_DIR/motor_coordinator.json" "$USER_CONFIG_FILE" "motor_coordinator_config"
    
    if [ -n "$COORDINATOR_LOG_CONFIG_PATH" ] && [ -n "$MODEL_NAME" ] && [ -n "$MODEL_ID" ]; then
        chmod 750 "$COORDINATOR_LOG_CONFIG_PATH"
        if [ ! -d "$COORDINATOR_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID" ];then
            mkdir -p -m 750 "$COORDINATOR_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID"
        fi
        export MINDIE_LOG_PATH="$COORDINATOR_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/mindie"
    fi
    set_coordinator_env

    # Coordinator start command
    python3 -m motor.coordinator.main
fi