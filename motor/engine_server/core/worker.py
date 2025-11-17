#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from typing import List

import psutil

from motor.common.utils.logger import get_logger

logger = get_logger("engine_server")


class WorkerManager:
    def __init__(self, process: List[psutil.Process]):
        self.processes = process

    def add_processes(self, process: List[psutil.Process]) -> None:
        self.processes.extend(process)

    def get_exited_processes(self) -> List[psutil.Process]:
        exited = []
        for proc in self.processes:
            try:
                if not proc.is_running():
                    exited.append(proc)
            except psutil.NoSuchProcess:
                exited.append(proc)
            except psutil.AccessDenied:
                continue
        return exited

    def remove_exited_processes(self) -> None:
        exited = self.get_exited_processes()
        self.processes = [proc for proc in self.processes if proc not in exited]

    def close(self) -> None:
        self.remove_exited_processes()
        for proc in self.processes:
            try:
                pid = proc.pid
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                    logger.info(f"Process (PID: {pid}) terminated gracefully")
                except psutil.TimeoutExpired:
                    logger.info(f"Process (PID: {pid}) did not terminate in time, attempting force kill")
                    proc.kill()  # Force termination
                    logger.info(f"Process (PID: {pid}) force killed")
            except psutil.NoSuchProcess:
                logger.info(f"Process already exited (PID: {proc.pid})")
            except psutil.AccessDenied:
                logger.info(f"Permission denied to terminate process (PID: {proc.pid})")
            except Exception as e:
                logger.info(f"Error terminating process (PID: {proc.pid}): {str(e)}")

        self.processes.clear()
