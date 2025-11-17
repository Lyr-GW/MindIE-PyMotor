# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.
import os
import re
import sys
import json
import shutil
import logging
import subprocess
from argparse import ArgumentParser
from typing import Dict, Any
from enum import Enum


class HardwareType(Enum):
    A2 = 'd802'
    A3 = 'd803'
    UNKNOWN = 'unknown'


def parse_args():
    """
    parse args .

    Args:

    Returns:
        args.

    Examples:
        >>> parse_args()
    """
    parser = ArgumentParser(description="mindspore distributed training launch "
                                        "helper utility that will generate hccl"
                                        " config file")
    parser.add_argument("--hccl_path", type=str, default="hccl.json",
                        help="Set the hccl_path manually, to avoid errors in auto detection.")
    args = parser.parse_args()
    return args


def get_hardware_type():
    """
    get npu type
    """
    try:
        lspci_path = shutil.which("lspci")
        if not lspci_path:
            raise ValueError("lspci not found!")
        output = subprocess.check_output(
            f"{lspci_path}",
            text=True,
            timeout=5
        )
        if HardwareType.A2.value in output:
            return HardwareType.A2
        elif HardwareType.A3.value in output:
            return HardwareType.A3
    except EOFError as e:
        logging.error("get hardware type failed: %s", e)

    return HardwareType.UNKNOWN


def get_visible_devices():
    """
    get visible devices in container
    """
    try:
        # Check /dev/davinci*
        import glob
        davinci_devices = glob.glob("/dev/davinci*")
        if davinci_devices:
            # extract device id from device path, e.g. /dev/davinci0 -> 0
            device_ids = []
            for device_path in davinci_devices:
                # extract device id from device path, e.g. /dev/davinci0 -> 0
                match = re.search(r'davinci(\d+)', device_path)
                if match:
                    device_ids.append(match.group(1))
            if device_ids:
                return sorted(device_ids)
               
    except Exception as e:
        logging.error(f"Failed to detect visible devices: {e}")
    return []


def main():
    logging.info("start %s", __file__)
    args = parse_args()

    # visible_devices
    visible_devices = get_visible_devices()
    logging.info('Detected visible_devices: %s', visible_devices)
    
    # hardware_type
    hardware_type = get_hardware_type()
    if hardware_type == HardwareType.UNKNOWN:
        raise ValueError("unknown hardware type!")
    logging.info('Detected hardware_type: %s', hardware_type)

    # server_id
    host_ip = os.getenv('HOST_IP', '127.0.0.1')
    pod_ip = os.getenv('POD_IP', '127.0.0.1')
    logging.info('host_ip: %s', host_ip)
    logging.info('pod_ip: %s', pod_ip)

    # construct hccn_table
    device_ips: Dict[Any, Any] = {}
    device_sdids: Dict[Any, Any] = {}
    try:
        for device_id in visible_devices:
            # device_ip
            ret_ip = os.popen("hccn_tool -i %s -ip -g" % device_id).readlines()
            device_ips[device_id] = ret_ip[0].split(":")[1].replace('\n', '').replace(' ', '')
            if hardware_type == HardwareType.A3:
                # super_device_id
                device_id_int = int(device_id)
                card_id = device_id_int // 2
                chip_id = device_id_int % 2
                ret_sdid = os.popen(f"npu-smi info -t spod-info -i {card_id} -c {chip_id}").readlines()
                device_sdids[device_id] = ret_sdid[0].split(":")[1].replace('\n', '').replace(' ', '')
    except Exception as e:
        logging.error(f"Failed to get device_ip or super_device_id, error: {e}")

    hccn_table = {'version': '1.0', 'server_count': '1', 'server_list': []}
    device_list = []
    rank_id = 0
    for rank_id, device_id in enumerate(visible_devices):
        device_ip = device_ips[device_id]
        device = {'device_id': device_id,
                  'device_ip': device_ip,
                  'rank_id': str(rank_id)}
        if hardware_type == HardwareType.A3:
            device['super_device_id'] = device_sdids[device_id]
        logging.info('rank_id: %s, device_id: %s, device_ip: %s', rank_id, device_id, device_ip)
        device_list.append(device)

    hccn_table['server_list'].append({
        'server_id': host_ip,
        'container_ip': pod_ip,
        'device': device_list
    })

    if hardware_type == HardwareType.A3:
        hccn_table['super_pod_list'] = [{"super_pod_id": "0", "server_list": [{"server_id": host_ip}]}]

    hccn_table['status'] = 'completed'

    table_fn = args.hccl_path
    with open(table_fn, 'w') as table_fp:
        json.dump(hccn_table, table_fp, indent=4)
    sys.stdout.flush()
    logging.info("Completed: hccl file was save in : %s", table_fn)


if __name__ == "__main__":
    main()
