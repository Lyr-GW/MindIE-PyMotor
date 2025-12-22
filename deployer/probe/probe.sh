#!/bin/bash

# check probe type
if [ -z "$1" ]; then
    echo "Error: Missing probe type. Please provide one of 'startup', 'readiness', or 'liveness'."
    exit 1
fi

probe_type=$1
role=$ROLE

# Execute probe
python3 $CONFIGMAP_PATH/probe.py $role $probe_type