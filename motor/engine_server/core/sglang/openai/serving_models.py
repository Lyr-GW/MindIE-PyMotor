# Copyright 2023-2024 SGLang Team
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
#
# MindIE is licensed under both the Mulan PSL v2 and the Apache License, Version 2.0.
# You may choose to use this software under the terms of either license.
#
# ---------------------------------------------------------------------------
# Mulan PSL v2:
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
#
# Apache License, Version 2.0:
# You may obtain a copy of the License at:
#         http://www.apache.org/licenses/LICENSE-2.0
# ---------------------------------------------------------------------------
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""OpenAI /v1/models listing for SGLang (aligned with sglang srt entrypoints http_server)."""

from typing import TYPE_CHECKING, Any

from sglang.srt.entrypoints.openai.protocol import ModelCard, ModelList

if TYPE_CHECKING:
    from sglang.srt.managers.tokenizer_manager import TokenizerManager


class OpenAIServingModels:
    """
    Lists served base model and loaded LoRA adapters; 
    same contract as vLLM OpenAIServingModels.show_available_models.
    """

    def __init__(self, tokenizer_manager: "TokenizerManager") -> None:
        self._tokenizer_manager: Any = tokenizer_manager

    async def show_available_models(self) -> ModelList:
        tm = self._tokenizer_manager
        served_model_names = [tm.served_model_name]
        model_cards: list[ModelCard] = []

        for served_model_name in served_model_names:
            model_cards.append(
                ModelCard(
                    id=served_model_name,
                    root=served_model_name,
                    max_model_len=tm.model_config.context_len,
                )
            )

        if tm.server_args.enable_lora:
            lora_registry = tm.lora_registry
            for _, lora_ref in lora_registry.get_all_adapters().items():
                model_cards.append(
                    ModelCard(
                        id=lora_ref.lora_name,
                        root=lora_ref.lora_path,
                        parent=served_model_names[0],
                        max_model_len=None,
                    )
                )

        return ModelList(data=model_cards)
