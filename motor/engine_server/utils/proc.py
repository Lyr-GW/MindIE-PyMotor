#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import contextlib
import os
import signal
import time
from multiprocessing.process import BaseProcess
from typing import List
import psutil


def get_child_processes(base_processes: List[BaseProcess], recursive: bool = False) -> List[psutil.Process]:
    processes = []
    for base in base_processes:
        if not base.is_alive():
            continue
        try:
            base_util = psutil.Process(base.pid)
            for child in base_util.children(recursive=recursive):
                processes.append(child)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def exit_process(procs: List[BaseProcess]):
    for proc in procs:
        if proc.is_alive():
            proc.terminate()

    deadline = time.monotonic() + 5
    for proc in procs:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if proc.is_alive():
            proc.join(remaining)

    for proc in procs:
        pid = proc.pid
        if proc.is_alive() and pid is not None:
            kill_process_tree(pid)


def kill_process_tree(pid: int):
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return

    children = parent.children(recursive=True)

    for child in children:
        with contextlib.suppress(ProcessLookupError):
            os.kill(child.pid, signal.SIGKILL)

    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
