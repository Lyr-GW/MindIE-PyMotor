#!/bin/bash

script_dir=$(dirname "$(realpath "$0")")
deployer_dir=$1

cp ${script_dir}/user_config_sample.json $deployer_dir
cp ${script_dir}/single_container_init.yaml ${deployer_dir}/deployment/single_container_init.yaml
cd $deployer_dir && python3 deploy.py --user_config_path=user_config_sample.json --single_container_yaml_file=single_container_init.yaml
