#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import signal

from motor.engine_server.config.base import IConfig
from motor.engine_server.core.base_core import BaseServerCore
from motor.engine_server.core.vllm.vllm_engine_proc_mgr import ProcManager
from motor.engine_server.utils.logger import run_log


class VLLMServerCore(BaseServerCore):
    def __init__(self, config: IConfig):
        super().__init__(config)
        self.engine_proc_manager = ProcManager(self.config.get_args())

    def initialize(self) -> None:
        self._register_signal_handlers()
        super().initialize()
        self.engine_proc_manager.initialize()
        self.data_controller.set_server_core(self)

    def run(self) -> None:
        super().run()
        self.engine_proc_manager.run()

    def join(self) -> None:
        self.engine_proc_manager.join()

    def shutdown(self) -> None:
        super().shutdown()
        self.engine_proc_manager.shutdown()
        run_log.info(f"[VLLMServerCore] vLLM shutdown completed")

    def status(self) -> str:
        return self.engine_proc_manager.status

    def _signal_handler(self, sig: int, frame) -> None:
        run_log.info(f"[VLLMServerCore] Received signal {sig} (SIGINT/SIGTERM), initiating shutdown")
        self.shutdown()

    def _register_signal_handlers(self) -> None:
        def handle_signal(signum, frame):
            self.shutdown()

        for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
            signal.signal(sig, handle_signal)
