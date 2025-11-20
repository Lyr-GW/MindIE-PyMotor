#!/bin/bash
set -x
set_common_env

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
USER_CONFIG_FILE="$CONFIGMAP_PATH/user_config.json"

# Core dump settings
if [ "$SAVE_CORE_DUMP_FILE_ENABLE" = "1" ]; then
    ulimit -c 31457280        # 31457280KB = 30G
    mkdir -p /var/coredump
    chmod 700 /var/coredump
    sysctl -w kernel.core_pattern=/var/coredump/core.%e.%p.%t
else
    ulimit -c 0
fi

mkdir $CONFIG_PATH -p
chmod 750 $CONFIG_PATH

if [ "$ROLE" = "prefill" ] || [ "$ROLE" = "decode" ]; then
    # Update configuration files based on user configuration
    echo "Updating nodemanager configuration file..."
    export MOTOR_NODE_MANAGER_CONFIG_PATH=$CONFIG_PATH/node_manager_config.json
    python3 "$CONFIGMAP_PATH/update_config_from_user_config.py" "$MOTOR_NODE_MANAGER_CONFIG_PATH" "$USER_CONFIG_FILE" "motor_nodemanger_config"
    export MOTOR_ENGINE_PATH=$CONFIG_PATH/motor_engine.json
    if [ "$ROLE" == "prefill" ]; then
        echo "Updating prefill server configuration file..."
        python3 "$CONFIGMAP_PATH/update_config_from_user_config.py" "$MOTOR_ENGINE_PATH" "$USER_CONFIG_FILE" "motor_engine_prefill_config"
    elif [ "$ROLE" == "decode" ]; then
        echo "Updating decode server configuration file..."
        python3 "$CONFIGMAP_PATH/update_config_from_user_config.py" "$MOTOR_ENGINE_PATH" "$USER_CONFIG_FILE" "motor_engine_decode_config"
    fi

    # Use hccl_tools.py to generate ranktable.json
    if [ -f "$CONFIGMAP_PATH/hccl_tools.py" ]; then
        echo "Using hccl_tools.py to generate ranktable.json..."
        export HCCL_PATH="$CONFIG_PATH/hccl.json"
        PYTHONUNBUFFERED=1 python3 "$CONFIGMAP_PATH/hccl_tools.py" --hccl_path "$HCCL_PATH"
        # ranktable output path, use by NodeManager
        export RANKTABLE_PATH="$CONFIG_PATH/ranktable.json"
        echo "Ranktable generated successfully: $HCCL_PATH"
    else
        echo "hccl_tools.py does not exist, skip ranktable generation"
    fi

    export RANK_TABLE_PATH="$CONFIG_PATH/ranktable.json"

    # Set environment variables for CANN
    export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/Ascend/driver/lib64/driver:/usr/local/Ascend/driver/lib64/common"
    source "$CANN_INSTALL_PATH/ascend-toolkit/set_env.sh"
    source "$CANN_INSTALL_PATH/nnal/atb/set_env.sh"

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
    export MOTOR_CONTROLLER_CONFIG_PATH=$CONFIG_PATH/controller_config.json
    python3 "$CONFIGMAP_PATH/update_config_from_user_config.py" "$MOTOR_CONTROLLER_CONFIG_PATH" "$USER_CONFIG_FILE" "motor_controller_config"
    
    if [ -n "$CONTROLLER_LOG_CONFIG_PATH" ] && [ -n "$MODEL_NAME" ] && [ -n "$MODEL_ID" ]; then
        chmod 750 "$CONTROLLER_LOG_CONFIG_PATH"
        if [ ! -d "$CONTROLLER_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID" ];then
            mkdir -p -m 750 "$CONTROLLER_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID"
        fi
        export MINDIE_LOG_PATH="$CONTROLLER_LOG_CONFIG_PATH/$MODEL_NAME/$MODEL_ID/mindie"
    fi
    set_controller_env

    # Controller start command
    python3 -m motor.controller.main --config $MOTOR_CONTROLLER_CONFIG_PATH
fi

if [ "$ROLE" == "coordinator" ]; then
    echo "Updating coordinator configuration file..."
    export MOTOR_COORDINATOR_CONFIG_PATH=$CONFIG_PATH/coordinator_config.json
    python3 "$CONFIGMAP_PATH/update_config_from_user_config.py" "$MOTOR_COORDINATOR_CONFIG_PATH" "$USER_CONFIG_FILE" "motor_coordinator_config"
    
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
