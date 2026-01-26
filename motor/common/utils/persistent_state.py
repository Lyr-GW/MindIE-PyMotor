#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from motor.common.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class PersistentState:
    """
    Unified persistent state with version control, data integrity, and type fixing

    This class provides comprehensive data persistence with automatic type correction
    to handle data type mismatches that occur during JSON serialization/deserialization.

    Key features:
    - Version control and data integrity verification via checksums
    - Automatic type fixing for data stored in external systems like ETCD
    - Special handling for endpoints field (converting string keys to int where appropriate)
    - Recursive type fixing for nested dictionaries and lists

    Type fixing methods:
    - _fix_data_types: fix the data types mismatch between the original data and the stored data in ETCD.
    - _fix_endpoints: fix the endpoints field by converting the string keys to int keys.
    - _fix_endpoint_dict: fix a single endpoint dictionary by converting the string keys to int keys.
    - _fix_list: fix a list by recursively processing any dict elements.
    """
    data: dict[str, Any]
    version: int
    timestamp: float
    checksum: str

    @staticmethod
    def _fix_data_types(data: dict) -> dict:
        """Fix data types that are lost during JSON serialization/deserialization"""
        if not isinstance(data, dict):
            return data

        fixed_data = {}
        for key, value in data.items():
            fixed_data[key] = PersistentState._fix_value(key, value)

        return fixed_data

    @staticmethod
    def _fix_value(key: str, value) -> any:
        """Fix a single value based on its key and type"""
        # Special handling for endpoints field
        if key == "endpoints":
            return PersistentState._fix_endpoints(value)

        # Handle different value types
        if isinstance(value, dict):
            return PersistentState._fix_data_types(value)
        elif isinstance(value, list):
            return PersistentState._fix_list(value)
        else:
            return value

    @staticmethod
    def _fix_list(data_list: list) -> list:
        """Fix a list by recursively processing any dict elements"""
        return [
            PersistentState._fix_data_types(item)
            if isinstance(item, dict) else item for item in data_list
        ]

    @staticmethod
    def _fix_endpoints(endpoints: dict) -> dict:
        """
        Fix endpoints data structure, converting inner dict keys from str to int.

        The endpoints data structure has the following format:
        {
            "pod_ip_1": {0: Endpoint(...), 1: Endpoint(...), ...},
            "pod_ip_2": {0: Endpoint(...), 2: Endpoint(...), ...},
            ...
        }

        When this data is serialized to JSON and stored in ETCD, the inner dict keys
        (which are integers representing endpoint IDs) get converted to strings.
        This method restores the correct integer keys to maintain data consistency.
        """
        if not isinstance(endpoints, dict):
            return endpoints

        fixed_endpoints = {}
        for pod_ip, endpoint_dict in endpoints.items():
            fixed_endpoints[pod_ip] = PersistentState._fix_endpoint_dict(endpoint_dict)

        return fixed_endpoints

    @staticmethod
    def _fix_endpoint_dict(endpoint_dict) -> dict:
        """
        Fix a single endpoint dictionary, converting string keys to int where possible.

        Endpoint dictionaries use integer keys representing endpoint IDs (0, 1, 2, ...).
        After JSON serialization/deserialization, these keys become strings ("0", "1", "2", ...).
        This method converts digit strings back to integers while preserving non-digit keys.
        """
        if not isinstance(endpoint_dict, dict):
            return endpoint_dict

        fixed_dict = {}
        for endpoint_key, endpoint_value in endpoint_dict.items():
            # Convert string key to int if it's a digit string, otherwise return as-is
            try:
                if isinstance(endpoint_key, str) and endpoint_key.isdigit():
                    fixed_key = int(endpoint_key)
                else:
                    fixed_key = endpoint_key
            except (ValueError, TypeError):
                fixed_key = endpoint_key
            fixed_dict[fixed_key] = endpoint_value

        return fixed_dict

    def calculate_checksum(self) -> str:
        """Calculate checksum for data integrity verification"""
        try:
            # Fix data types first to ensure consistency
            fixed_data = PersistentState._fix_data_types(self.data)
            # Calculate checksum using type-fixed data for consistency
            sorted_data = str(sorted(fixed_data.items()))
            data_str = f"{sorted_data}{self.version}{self.timestamp}"
            return hashlib.sha256(data_str.encode()).hexdigest()
        except Exception as e:
            logger.error("Error calculating checksum: %s", e)
            return ""

    def is_valid(self) -> bool:
        """Validate data integrity using checksum"""
        # Try both original format checksum and JSON normalized checksum for compatibility
        current_checksum = self.calculate_checksum()
        logger.debug("Validating data integrity - stored checksum: %s, calculated checksum: %s",
                     self.checksum, current_checksum)
        logger.debug("Validation data - version: %s, timestamp: %s", self.version, self.timestamp)

        if self.checksum == current_checksum:
            return True

        logger.warning("Original format checksum mismatch, attempting JSON normalized checksum")

        # Also try with JSON normalized data for cases where data was stored with different types
        try:
            # First normalize the data through JSON serialization/deserialization
            normalized_data = json.loads(json.dumps(self.data, sort_keys=True))

            # Fix data types that are lost during JSON serialization (especially dict keys)
            fixed_data = PersistentState._fix_data_types(normalized_data)

            normalized_checksum = hashlib.sha256(
                f"{fixed_data}{self.version}{self.timestamp}".encode()
            ).hexdigest()

            logger.debug("JSON normalized checksum: %s", normalized_checksum)
            logger.debug("Original data type information: %s",
                         {k: type(v).__name__ for k, v in self.data.items()})

            if self.checksum == normalized_checksum:
                logger.debug("Type-fixed checksum matched successfully")
                return True
            else:
                logger.error("Validation failed - stored checksum: %s, normalized checksum: %s",
                             self.checksum, normalized_checksum)
                return False
        except Exception as e:
            logger.error("Exception occurred during JSON normalization: %s", e)
            logger.error("Original data content: %s", self.data)
            return False
