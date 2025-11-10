#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import time
from typing import Dict, Any, Optional

import requests

from motor.engine_server.config.base import IConfig
from motor.engine_server.core.base_collector import BaseCollector
from motor.engine_server.utils.logger import run_log


class VLLMCollector(BaseCollector):
    def __init__(self, config: IConfig):
        super().__init__(config)
        self.host = config.get_args().host
        self.port = config.get_args().port
        self.collect_interval = 3
        self.timeout = 2
        self._metrics_url = f"http://{self.host}:{self.port}/metrics"
        self._health_url = f"http://{self.host}:{self.port}/health"
        run_log.info(
            f"VLLMCollector initialized: metrics_url={self._metrics_url}, "
            f"health_url={self._health_url}, collect_interval={self.collect_interval}s"
        )

    @staticmethod
    def _build_error_result(error_msg: str, url: str, http_status_code: Optional[int]) -> Dict[str, Any]:
        return {
            "api_url": url,
            "status": "failed",
            "error": error_msg,
            "data": None,
            "collect_time": int(time.time() * 1000),
            "http_status_code": http_status_code
        }

    def _collect(self) -> Dict[str, Any]:
        metrics_data = self._do_collect_metrics()
        health_data = self._do_collect_health()

        return {
            "timestamp": int(time.time() * 1000),
            "collector_name": self.name,
            "metrics": metrics_data,
            "health": health_data,
        }

    def _do_collect_metrics(self) -> Dict[str, Any]:
        run_log.debug(f"Start collecting vLLM metrics from {self._metrics_url}")
        try:
            response = requests.get(self._metrics_url, timeout=self.timeout)
            response.raise_for_status()
            run_log.debug(f"Successfully collected vLLM metrics")
            return {
                "api_url": self._metrics_url,
                "status": "success",
                "data": response.text,
                "collect_time": int(time.time() * 1000),
                "http_status_code": 200
            }
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            error_msg = f"Connect failed: {str(e)}"
            run_log.error(f"Metrics collect failed: {error_msg}")
            return self._build_error_result(error_msg, self._metrics_url, None)

        except requests.exceptions.HTTPError as e:
            http_status_code = e.response.status_code if e.response else None
            error_msg = f"HTTP request failed: {str(e)} (status code: {http_status_code})"
            run_log.error(f"Metrics collect failed: {error_msg}")
            return self._build_error_result(error_msg, self._metrics_url, http_status_code)

        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            run_log.error(f"Metrics collect failed: {error_msg}")
            return self._build_error_result(error_msg, self._metrics_url, None)

    def _do_collect_health(self) -> Dict[str, Any]:
        run_log.debug(f"Start collecting vLLM health from {self._health_url}")
        try:
            response = requests.get(self._health_url, timeout=self.timeout)
            if response.status_code == 200:
                return {
                    "api_url": self._health_url,
                    "status": "success",
                    "data": None,
                    "collect_time": int(time.time() * 1000),
                    "http_status_code": 200
                }
            else:
                error_msg = f"Health check failed with HTTP status code: {response.status_code}"
                run_log.error(f"Health collect failed: {error_msg}")
                return self._build_error_result(error_msg, self._health_url, response.status_code)

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            error_msg = f"Connect failed: {str(e)}"
            run_log.error(f"Health collect failed: {error_msg}")
            return self._build_error_result(error_msg, self._health_url, None)

        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            run_log.error(f"Health collect failed: {error_msg}")
            return self._build_error_result(error_msg, self._health_url, None)
