# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

import importlib.metadata as md
from typing import Any

import vllm
from vllm.entrypoints.utils import cli_env_setup
from vllm.usage.usage_lib import UsageContext
from vllm.v1.engine.async_llm import AsyncLLM

from motor.common.utils.logger import get_logger
from motor.engine_server.core.config import IConfig
from motor.engine_server.core.engine import Engine

logger = get_logger(__name__)

vllm_version = md.version("vllm")
logger.info(f"vLLM version: {vllm_version}")


class VLLMEngine(Engine):
    def __init__(self, config: IConfig):
        self.config = config
        self.args = config.get_args()
        self.async_llm: AsyncLLM | None = None

    def launch(self) -> Any:
        cli_env_setup()
        return self._run_vllm()
    
    def shutdown(self) -> None:
        if self.async_llm is not None:
            self.async_llm.shutdown()
            self.async_llm = None
        logger.info(f"[VLLMServerCore] vLLM shutdown completed")

    def _run_vllm(self):
        endpoint_instance_count = self.args.api_server_count

        engine_config = vllm.AsyncEngineArgs.from_cli_args(self.args)
        safe_count = endpoint_instance_count or 1
        setattr(engine_config, "_api_process_count", safe_count)
        setattr(engine_config, "_api_process_rank", -1)

        endpoint_usage_context = UsageContext.OPENAI_API_SERVER
        if hasattr(engine_config, 'lookup_rpc_port'):
            delattr(engine_config, 'lookup_rpc_port')
        vllm_endpoint_config = engine_config.create_engine_config(usage_context=endpoint_usage_context)

        parallel_setup = vllm_endpoint_config.parallel_config
        dp_rank_value = parallel_setup.data_parallel_rank
        use_external_load_balancing = parallel_setup.data_parallel_external_lb
        use_hybrid_load_balancing = parallel_setup.data_parallel_hybrid_lb

        if not (use_external_load_balancing or use_hybrid_load_balancing or dp_rank_value == 0):
            validation_msg = f"Invalid configuration: external_dp_lb={use_external_load_balancing}, "
            validation_msg += f"hybrid_dp_lb={use_hybrid_load_balancing}, dp_rank={dp_rank_value}"
            raise ValueError(validation_msg)

        self.async_llm = AsyncLLM.from_vllm_config(
            vllm_config=vllm_endpoint_config,
            usage_context=endpoint_usage_context,
            disable_log_stats=engine_config.disable_log_stats,
        )

        logger.info("VLLMEngine launched successfully")
        return self.async_llm
