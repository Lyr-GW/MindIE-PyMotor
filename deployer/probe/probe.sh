#!/bin/bash

# check probe type
if [ -z "$1" ]; then
    echo "Error: Missing probe type. Please provide one of 'startup', 'readiness', or 'liveness'."
    exit 1
fi

probe_type=$1
cd $CONFIGMAP_PATH

role=$ROLE

# Controller
if [ "$role" == "controller" ]; then
    startup_url=/startup
    readiness_url=/readiness
    liveness_url=/liveness
    port=$(python $CONFIGMAP_PATH/get_mgmt_port.py "$CONFIG_PATH/controller_config.json" "api_config.controller_api_port")
fi

# Coordinator
if [ "$role" == "coordinator" ]; then
    startup_url=/startup
    readiness_url=/readiness
    liveness_url=/health
    port=$(python $CONFIGMAP_PATH/get_mgmt_port.py "$CONFIG_PATH/coordinator_config.json" "http_config.coordinator_api_mgmt_port")
fi

case "$probe_type" in
    startup)
        echo "Executing startup probe..."
        python3 $CONFIGMAP_PATH/probe_status_check.py $POD_IP $port $startup_url
        if [ $? -ne 0 ]; then
            echo "Service is not running."
            exit 1
        fi
        echo "Service is running."
        exit 0
        ;;

    readiness)
        echo "Executing readiness probe..."
        python3 $CONFIGMAP_PATH/probe_status_check.py $POD_IP $port $readiness_url
        if [ $? -ne 0 ]; then
            echo "Service is not ready."
            exit 1
        fi
        echo "Service is ready."
        exit 0
        ;;

    liveness)
        echo "Executing liveness probe..."
        python3 $CONFIGMAP_PATH/probe_status_check.py $POD_IP $port $liveness_url
        if [ $? -ne 0 ]; then
            echo "Service is not alive."
            exit 1
        fi
        echo "Service is alive."
        exit 0
        ;;

    *)
        echo "Error: Invalid probe type. Please use 'startup', 'readiness', or 'liveness'."
        exit 1
        ;;
esac