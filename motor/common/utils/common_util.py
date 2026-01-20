# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import ctypes
import sys


def clear_passwd(password):
    if not password:
        return
    password_len = len(password)
    password_offset = sys.getsizeof(password) - password_len - 1
    ctypes.memset(id(password) + password_offset, 0, password_len)