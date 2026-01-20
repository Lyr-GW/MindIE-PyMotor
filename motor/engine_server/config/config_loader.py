#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from dataclasses import dataclass
from typing import Dict, Any
import json
from pathlib import Path

from motor.config.tls_config import TLSConfig


@dataclass
class ParallelConfig:
    """Configuration for parallel processing (both prefill and decode)"""
    dp_size: int
    tp_size: int
    pp_size: int
    enable_ep: bool
    dp_rpc_port: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParallelConfig":
        return cls(**data)


@dataclass
class ModelConfig:
    """Configuration for the model itself"""
    model_name: str
    model_path: str
    npu_mem_utils: float
    prefill_parallel_config: ParallelConfig
    decode_parallel_config: ParallelConfig

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig":
        return cls(
            model_name=data["model_name"],
            model_path=data["model_path"],
            npu_mem_utils=data["npu_mem_utils"],
            prefill_parallel_config=ParallelConfig.from_dict(data["prefill_parallel_config"]),
            decode_parallel_config=ParallelConfig.from_dict(data["decode_parallel_config"])
        )


@dataclass
class EngineConfig:
    """Configuration for the engine with dynamic key-value pairs"""
    configs: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineConfig":
        """Parse EngineConfig from a dictionary (stores dynamic key-value pairs directly)"""
        return cls(configs=data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.configs.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.configs[key] = value


@dataclass
class DeployConfig:
    """Root configuration class representing the entire JSON structure"""
    engine_type: str
    model_config: ModelConfig
    engine_config: EngineConfig
    mgmt_tls_config: TLSConfig
    infer_tls_config: TLSConfig

    @classmethod
    def load(cls, file_path: str | Path) -> "DeployConfig":
        """
        Load configuration from a JSON file and parse into a DeployConfig instance

        :param file_path: Path to the JSON file
        :return: Parsed DeployConfig instance
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            engine_type=data["engine_type"],
            model_config=ModelConfig.from_dict(data["model_config"]),
            engine_config=EngineConfig.from_dict(data["engine_config"]),
            mgmt_tls_config=TLSConfig.from_dict(data["mgmt_tls_config"]),
            infer_tls_config=TLSConfig.from_dict(data["infer_tls_config"])
        )

    def get_parallel_config(self, role: str = "union") -> ParallelConfig:
        """
        Get the parallel configuration based on the role.

        :param role: Role for parallel config:
            - "union" or "prefill": Get prefill_parallel_config
            - "decode": Get decode_parallel_config
        :return: Corresponding ParallelConfig instance
        """
        if role in ("union", "prefill"):
            return self.model_config.prefill_parallel_config
        elif role == "decode":
            return self.model_config.decode_parallel_config
        else:
            raise ValueError(f"Unsupported role: {role}. Allowed values: 'union', 'prefill', 'decode'")
