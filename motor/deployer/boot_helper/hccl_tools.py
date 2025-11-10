# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2012-2020. All rights reserved.
import os
import sys
import json
import socket
import logging
from argparse import ArgumentParser
from typing import Dict, Any


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
    parser.add_argument("--device_num", type=str, default="[0,8)",
                        help="The number of the Ascend accelerators used. please note that the Ascend accelerators"
                             "used must be continuous, such [0,4) means using four chips "
                             "0，1，2，3; [0,1) means using chip 0; In the most Ascend system, "
                             "the first four chips belong to one group, and the last four chips belong to another one."
                             "Only full chips are allowed to cross-group such as [0,8), other cross-group such as [3,6)"
                             "are prohibited.")
    parser.add_argument("--visible_devices", type=str, default="0,1,2,3,4,5,6,7",
                        help="The visible devices according to the software system. "
                             "Usually used in the virtual system or docker container "
                             "that makes the device_id dismatch logic_id. --device_num uses logic_id. "
                             "For example \"4,5,6,7\" means the system has 4 logic chips "
                             "which are actually the last 4 chips in hardware "
                             "while `--device_num` could only be set to \"[0, 4)\" instead of \"[4, 8)\"")
    parser.add_argument("--server_ip", type=str, default="",
                        help="Set the server_ip manually, to avoid errors in auto detection.")
    parser.add_argument("--rank_table_path", type=str, default="./hccl/ranktable.json",
                        help="Set the rank_table_path manually, to avoid errors in auto detection.")
    args = parser.parse_args()
    return args


def get_host_ip():
    """
    get host ip
    """
    ip = None

    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
    except EOFError:
        pass

    return ip


def main():
    logging.info("start %s", __file__)
    args = parse_args()

    # visible_devices
    visible_devices = args.visible_devices.split(',')
    logging.info('visible_devices: %s', visible_devices)

    # server_id
    ip = get_host_ip()
    if args.server_ip:
        server_id = args.server_ip
    elif ip:
        server_id = ip
    else:
        raise ValueError("please input server ip!")
    logging.info('server_id: %s', server_id)

    # device_num
    first_num = int(args.device_num[1])
    last_num = int(args.device_num[3])
    if first_num < 0 or last_num > 8:
        raise ValueError("device num {} must be in range [0,8] !".format(args.device_num))
    if first_num > last_num:
        raise ValueError("First num {} of device num {} must less than last num {} !".format(first_num, args.device_num,
                                                                                             last_num))
    if first_num < 4 < last_num:
        if first_num == 0 and last_num == 8:
            pass
        else:
            raise ValueError("device num {} must be in the same group of [0,4] or [4,8] !".format(args.device_num))

    device_num_list = list(range(first_num, last_num))
    logging.info("device_num_list: %s", device_num_list)

    if len(visible_devices) < len(device_num_list):
        raise ValueError("visible_devices {} must be more than device_num_list {} !"\
                         .format(visible_devices, device_num_list))

    # construct hccn_table
    device_ips: Dict[Any, Any] = {}
    try:
        for device_id in device_num_list:
            ret = os.popen("hccn_tool -i %d -ip -g" % device_id).readlines()
            device_ips[str(device_id)] = ret[0].split(":")[1].replace('\n', '')
    except IndexError:
        logging.error("Failed to call hccn_tool, try to read /etc/hccn.conf instead")
        try:
            with open('/etc/hccn.conf', 'r') as fin:
                for hccn_item in fin.readlines():
                    if hccn_item.strip().startswith('address_'):
                        device_id, device_ip = hccn_item.split('=')
                        device_id = device_id.split('_')[1]
                        device_ips[device_id] = device_ip.strip()
        except OSError as e:
            logging.error("Failed to read /etc/hccn.conf")
            raise SystemError("Failed to find information for hccl") from e

    hccn_table = {'version': '1.0',
                  'server_count': '1',
                  'server_list': []}
    device_list = []
    rank_id = 0
    for instance_id in device_num_list:
        device_id = visible_devices[instance_id]
        device_ip = device_ips[device_id]
        device = {'device_id': device_id,
                  'device_ip': device_ip,
                  'rank_id': str(rank_id)}
        logging.info('rank_id: %s, device_id: %s, device_ip: %s', rank_id, device_id, device_ip)
        rank_id += 1
        device_list.append(device)
    hccn_table['server_list'].append({
        'server_id': server_id,
        'device': device_list,
        'host_nic_ip': 'reserve'
    })
    hccn_table['status'] = 'completed'

    table_fn = args.rank_table_path
    with open(table_fn, 'w') as table_fp:
        json.dump(hccn_table, table_fp, indent=4)
    sys.stdout.flush()
    logging.info("Completed: hccl file was save in : %s", table_fn)


if __name__ == "__main__":
    main()
