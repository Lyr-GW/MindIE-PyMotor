#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import time
import threading
from enum import Enum
import requests
from motor.common.utils.singleton import ThreadSafeSingleton
from motor.config.coordinator import CoordinatorConfig
from motor.common.resources.instance import Instance
from motor.coordinator.core.instance_manager import InstanceManager
from motor.common.utils.logger import get_logger

logger = get_logger(__name__)


class MetricType(Enum):
    GAUGE = "gauge"
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"

    def __str__(self):
        return self.value

    @classmethod
    def from_string(cls, type_string):
        return cls[type_string.upper()]


class SingleMetric():
    def __init__(self, single_metric=None):
        if single_metric:
            self.name: str = single_metric.name
            self.help: str = single_metric.help
            self.type: MetricType = single_metric.type
            self.label: list[str] = single_metric.label
            self.value: list[float] = [0.0] * len(single_metric.label)
        else:
            self.name: str = ""
            self.help: str = ""
            self.type: str = ""
            self.label: list[str] = []
            self.value: list[float] = []


class MetricsCollector(ThreadSafeSingleton):
    METRICS_KEY = "metrics"

    def __init__(self):
        # If the metrics collector is already initialized, return.
        if hasattr(self, '_initialized'):
            return

        # Initial metrics state
        self._inactive_instance_metrics_aggregate: list[SingleMetric] = []
        self._instance_metrics_cached: dict[int, dict[str, list[SingleMetric]]] = {}
        self._last_metrics: str = ""
        self._last_instance_metrics: dict[int, list[SingleMetric]] = {}

        self._reuse_time: int = CoordinatorConfig().prometheus_metrics_config.reuse_time
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._metrics_update_thread = threading.Thread(
            target=self._update_metrics_thread,
            daemon=True,
            name="MetricsUpdate"
        )
        self._metrics_update_thread.start()

        self._initialized = True
        logger.info("MetricsCollector started.")

    def stop(self) -> None:
        """
        Stop update metrics thread.

        :returns:
        """

        self._stop_event.set()
        self._metrics_update_thread.join()
        logger.info("MetricsCollector stopped.")

    def prometheus_instance_metrics_handler(self):
        """
        Callback of http /metrics.

        :returns:
        """

        with self._lock:
            instance_metrics = self._last_instance_metrics
        return instance_metrics

    def prometheus_metrics_handler(self):
        """
        Callback of http /instance/metrics.

        :returns:
        """

        with self._lock:
            metrics = self._last_metrics
        return metrics

    def _update_metrics_thread(self) -> None:
        """
        Start update metrics thread.

        :returns:
        """

        while not self._stop_event.is_set():
            metrics, instance_metrics = self._get_and_aggregate_metrics()
            with self._lock:
                if metrics and instance_metrics:
                    self._last_metrics = metrics
                    self._last_instance_metrics = instance_metrics
            time.sleep(self._reuse_time)

    def _get_server_metrics_single(self, ip: str, port: str) -> str:
        """
        Get metrics of single engine server.

        :param ip: engine server ip
        :param port: engine server port
        :returns: engine server metrics. If request failed, return "".
        """

        url = f"http://{ip}:{port}/metrics"
        try:
            response = requests.get(url)

            if response.status_code == 200:
                data = response.text
                return data
            else:
                logger.warning(f"[Metrics] request metrics failed: code = {response.status_code}")

        except requests.exceptions.RequestException as e:
            logger.warning(f"[Metrics] request metrics failed: {e}")

        return ""

    def _get_server_metrics_endpoints(self, ins_info: Instance) -> dict[str, dict[int, str]]:
        """
        Get all endpoints metrics text in single instance.

        :param ins_info:
        :returns: if any failed, return {}
            for example:
            {
                "endpoints": {
                    endpoint_id0: {
                        "metrics_str": "xxx"
                    },
                    endpoint_id1: ...
                }
            }
        """

        collect = {
            "endpoints": {}
        }

        for ens_info in ins_info.endpoints.values():
            for en_info in ens_info.values():
                metrics_str = self._get_server_metrics_single(en_info.ip, en_info.mgmt_port)
                if not metrics_str:
                    return {}
                collect["endpoints"][en_info.id] = {
                    "metrics_str": metrics_str
                }

        return collect

    def _get_server_metrics(
        self,
        available_instances: dict[int, Instance]
    ) -> dict[int, dict[str, dict[int, str]]]:
        """
        Get instances/endpoints info and get all endpoints metrics text.

        :param available_instances: alive instances
        :returns:
            for example:
            {
                instance_id0: {
                    "endpoints": {
                        endpoint_id0: {
                            "metrics_str": "xxx"
                        },
                        endpoint_id1: ...
                    }
                },
                instance_id1: ...
            }
        """

        collects = {}
        for ins_info in available_instances.values():
            collect = self._get_server_metrics_endpoints(ins_info)
            if collect:
                collects[ins_info.id] = collect

        return collects

    def _parse_metric_help(self, single_metric: SingleMetric, line: str) -> bool:
        """
        Parse help line.

        :param single_metric:
        :param line: format: "# HELP <name> <help description>"
        :returns: if success, update single_metric and return True, else return False
        """

        parts = line.split()
        sharp_index = 0
        help_mark_index = 1
        name_index = 2
        help_desc_index = 3
        if len(parts) >= help_desc_index + 1 and parts[sharp_index] == "#" and parts[help_mark_index] == "HELP":
            single_metric.name = parts[name_index]
            single_metric.help = " ".join(parts[help_desc_index:])
            return True
        else:
            logger.error("[Metrics] Parse metric help failed.")
            return False

    def _parse_metric_type(self, single_metric: SingleMetric, line: str) -> bool:
        """
        Parse type line.

        :param single_metric:
        :param line: format: "# TYPE <name> <gauge|counter|histogram|summary>"
        :returns: if success, update single_metric and return True, else return False
        """

        parts = line.split()
        sharp_index = 0
        type_mark_index = 1
        type_index = 3
        if len(parts) == type_index + 1 and parts[sharp_index] == "#" and parts[type_mark_index] == "TYPE":
            try:
                single_metric.type = MetricType.from_string(parts[3])
            except KeyError:
                logger.error("[Metrics] Illegal metric type: %s", parts[3])
                return False
            return True
        else:
            logger.error("[Metrics] Parse metric type failed.")
            return False

    def _parse_metric_body_block(self, single_metric: SingleMetric, line: str) -> bool:
        """
        Parse help line.

        :param single_metric:
        :param line: format: "<label> <value>"
        :returns: if success, update single_metric and return True, else return False
        """

        parts = line.split()
        label_index = 0
        value_index = 1

        if len(parts) != value_index + 1:
            logger.error("[Metrics] Parse metric body failed.")
            return False
    
        single_metric.label.append(parts[label_index])
        try:
            value = float(parts[value_index])
            if value < 0:
                logger.error("[Metrics] Illegal metric value: %s", parts[value_index])
                return False
            single_metric.value.append(value)
        except ValueError:
            logger.error("[Metrics] Illegal metric value: %s", parts[value_index])
            return False
        return True

    def _parse_metric_text(self, metrics_str) -> list[SingleMetric]:
        """
        Parse metrics from text to format data.

        :param metrics_str:
            metrics_str format:
                # HELP <name> <help description>
                # TYPE <name> <gauge|counter|histogram|summary>
                <label0> <value0>
                <label1> <value1>
                ...
                <labeln> <valuen>
                # HELP ...
                # TYPE ...
                ...
        :returns: If success, return a list of SingleMetric, else return []
            SingleMetric format:
                name = <name>
                help = <help description>
                type = <gauge|counter|histogram|summary>
                label = [label0, label1, ..., labeln]
                value = [value0, value1, ..., valuen]
        """

        metric_array = []
        lines = metrics_str.strip().split("\n")
        i = 0
        while i < len(lines):
            single_metric = SingleMetric()
            if i < len(lines) and not self._parse_metric_help(single_metric, lines[i]):
                return []
            i += 1
            if i < len(lines) and not self._parse_metric_type(single_metric, lines[i]):
                return []
            i += 1
            while i < len(lines) and lines[i][0] != "#":
                if not self._parse_metric_body_block(single_metric, lines[i]):
                    return []
                i += 1
            metric_array.append(single_metric)
        return metric_array

    def _parse_metrics(
        self,
        collects: dict[int, dict[str, dict[int, dict[str, str]]]]
    ) -> bool:
        """
        Parse metrics text to format data for all instances/endpoints.

        :param collects:
            collects before call:
            {
                instance_id0: {
                    "endpoints": {
                        endpoint_id0: {
                            "metrics_str": "xxx"
                        },
                        endpoint_id1: ...
                    }
                },
                instance_id1: ...
            }
            collects after call:
            {
                instance_id0: {
                    "endpoints": {
                        endpoint_id0: {
                            "metrics": metrics_value # the type of metrics_value: list[SingleMetric]
                        },
                        endpoint_id1: ...
                    }
                },
                instance_id1: ...
            }
        :returns: if success, replace "metrics_str" by "metrics" and return True, else return False
        """

        if not isinstance(collects, dict):
            logger.error("[Metrics] Invalid pods metric JSON file.")
            return False

        if not collects:
            return True

        metric_count = 0
        for instance_id in collects.keys():
            if not isinstance(collects[instance_id], dict) or \
                not collects[instance_id] or "endpoints" not in collects[instance_id]:
                logger.error("[Metrics] Invalid pods metric JSON file.")
                return False

            pods = collects[instance_id]["endpoints"]
            for pod_info in pods.values():
                if "metrics_str" not in pod_info:
                    logger.error("[Metrics] Invalid 'metrics_str' in pod metrics JSON file.")
                    return False
                parsed_metric = self._parse_metric_text(pod_info["metrics_str"])
                if metric_count == 0:
                    metric_count = len(parsed_metric)
                elif metric_count != len(parsed_metric):
                    parsed_metric = {}
                if not parsed_metric:
                    logger.error("[Metrics] Parse metric text failed.")
                    return False
                pod_info[self.METRICS_KEY] = parsed_metric
        return True

    def _aggregate_metric_by_sum(
        self,
        endpoints: dict[int, dict[str, list[SingleMetric]]],
        single_metric: SingleMetric,
        index: int
    ) -> None:
        """
        Aggregate the index-th metric of all pods in single instance.

        :param endpoints:
            endpoints format:
            {
                endpoint_id0: {
                    "metrics": metrics_value # the type of metrics_value: list[SingleMetric]
                },
                endpoint_id1: ...
            }
        :param single_metric: aggregate result save to single_metric
        :param index: the position in list[SingleMetric]
        :returns:
        """
        first_pod = next(iter(endpoints.values()))
        value_num = len(first_pod[self.METRICS_KEY][index].value)
        single_metric.value = [0.0] * value_num
        for i in range(value_num):
            for pod_info in endpoints.values():
                single_metric.value[i] += pod_info[self.METRICS_KEY][index].value[i]

    def _aggregate_metrics_by_instance(
        self,
        collects: dict[int, dict[str, dict[int, dict[str, list[SingleMetric]]]]]
    ) -> bool:
        """
        For each instance, aggreagte metrics of all endpoints.

        :param collects:
            collects before call:
            {
                instance_id0: {
                    "endpoints": {
                        endpoint_id0: {
                            "metrics": metrics_value # the type of metrics_value: list[SingleMetric]
                        },
                        endpoint_id1: ...
                    }
                },
                instance_id1: ...
            }
            collects after call:
            {
                instance_id0: {
                    "metrics": metrics_value # the type of metrics_value: list[SingleMetric]
                },
                instance_id1: ...
            }
        :returns:
        """

        for instance_id in collects.keys():
            endpoints = collects[instance_id]["endpoints"]
            if not endpoints:
                continue

            first_pod = next(iter(endpoints.values()))
            aggregate = []
            metric_count = len(first_pod[self.METRICS_KEY])
            for i in range(metric_count):
                single_metric = SingleMetric(first_pod[self.METRICS_KEY][i])
                self._aggregate_metric_by_sum(endpoints, single_metric, i)
                aggregate.append(single_metric)
            collects[instance_id][self.METRICS_KEY] = aggregate
            del collects[instance_id]["endpoints"]

            if not self._check_and_update_metrics_cached(instance_id, collects[instance_id][self.METRICS_KEY]):
                logger.error("[Metrics] Update metrics state failed.")
                return False

        return True

    def _check_metric_format(self, base_metric: SingleMetric, single_metric: SingleMetric) -> bool:
        """
        Check metric format.

        :param base_metric:
        :param single_metric:
        :returns:
        """

        if base_metric.name != single_metric.name:
            return False
        if base_metric.help != single_metric.help:
            return False
        if base_metric.type != single_metric.type:
            return False
        if base_metric.label != single_metric.label:
            return False
        return True

    def _check_and_update_metrics_cached(self, instance_id: int, instance_metrics: list[SingleMetric]) -> bool:
        """
        Check metrics format and add/update cache.

        :param instance_id: instance id
        :param instance_metrics: instance metrics
        :returns:
        """

        # check metrics format
        if not isinstance(instance_metrics, list) or not instance_metrics:
            return False

        if self._instance_metrics_cached:
            base_metrics = next(iter(self._instance_metrics_cached.values()))[self.METRICS_KEY]
            if len(base_metrics) != len(instance_metrics):
                return False

            for i, base_metric in enumerate(base_metrics):
                if not self._check_metric_format(base_metric, instance_metrics[i]):
                    return False

        # update cache
        self._instance_metrics_cached[instance_id] = {
            self.METRICS_KEY: instance_metrics
        }
        return True

    def _aggregate_instance_metric_by_sum(
        self,
        collects: dict[int, dict[str, list[SingleMetric]]],
        single_metric: SingleMetric,
        index: int
    ) -> None:
        """
        Aggregate the index-th metric of all instance.

        :param collects:
        :param single_metric: aggregate result save to single_metric
        :param index: the position in list[SingleMetric]
        :returns:
        """

        if not self._instance_metrics_cached:
            return

        first_instance = next(iter(self._instance_metrics_cached.values()))
        value_num = len(first_instance[self.METRICS_KEY][index].value)
        for ins_id in self._instance_metrics_cached:
            # gauge type only aggregate active instances
            if single_metric.type == MetricType.GAUGE and ins_id not in collects:
                continue

            for i in range(value_num):
                single_metric.value[i] += self._instance_metrics_cached[ins_id][self.METRICS_KEY][index].value[i]
                if self._inactive_instance_metrics_aggregate:
                    single_metric.value[i] += self._inactive_instance_metrics_aggregate[index].value[i]

    def _aggregate_metrics_all_instance(self, collects: dict[int, dict[str, list[SingleMetric]]]) -> list[SingleMetric]:
        """
        Aggreagte metrics of all instances.

        :param collects:
        :returns:
        """

        if not self._instance_metrics_cached:
            return []

        first_instance = next(iter(self._instance_metrics_cached.values()))
        aggregate = []
        metric_count = len(first_instance[self.METRICS_KEY])
        for i in range(metric_count):
            single_metric = SingleMetric(first_instance[self.METRICS_KEY][i])
            self._aggregate_instance_metric_by_sum(collects, single_metric, i)
            aggregate.append(single_metric)

        return aggregate

    def _get_value_str(self, value: float) -> str:
        """
        Transform float to str.

        :returns:
        """

        if value == float("nan"):
            return "Nan"
        elif value == float("inf"):
            return "+Inf"
        elif value == float("-inf"):
            return "-Inf"
        return str(value)

    def _get_serialize_metrics(self, aggregate: list[SingleMetric]) -> str:
        """
        Metrics serialize.

        :param aggregate:
        :returns:
        """

        lines = []
        for item in aggregate:
            lines.append("# HELP {} {}".format(item.name, item.help))
            lines.append("# TYPE {} {}".format(item.name, item.type))
            for i, lable_name in enumerate(item.label):
                lines.append("{} {}".format(lable_name, self._get_value_str(item.value[i])))
        return "\n".join(lines)

    def _get_serialize_instance_metrics(
        self,
        collects: dict[int, dict[str, list[SingleMetric]]]
    ) -> dict[int, list[SingleMetric]]:
        """
        Instance metrics serialize.

        :param collects:
        :returns:
        """

        instance_metrics = {}
        for ins_id in collects.keys():
            instance_metrics[ins_id] = self._instance_metrics_cached[ins_id][self.METRICS_KEY]

        return instance_metrics

    def _clear_inactive_metrics(self, unavailable_pool: dict[int, Instance]) -> None:
        clear_ins_list = []
        for ins_id in unavailable_pool.keys():
            if ins_id in self._instance_metrics_cached:
                clear_ins_list.append(ins_id)
        
        for ins_id in clear_ins_list:
            metrics = self._instance_metrics_cached[ins_id][self.METRICS_KEY]

            # initialize self._inactive_instance_metrics_aggregate
            if not self._inactive_instance_metrics_aggregate:
                for metric in metrics:
                    aggregate_metric = SingleMetric(metric)
                    self._inactive_instance_metrics_aggregate.append(aggregate_metric)

            # aggregate metrics[index] to self._inactive_instance_metrics_aggregate
            for index, metric in enumerate(metrics):
                if metric.type == MetricType.GAUGE:
                    continue
                for i, value in enumerate(metric.value):
                    self._inactive_instance_metrics_aggregate[index].value[i] += value

            # remove ins_id from cache
            del self._instance_metrics_cached[ins_id]


    def _get_and_aggregate_metrics(self) -> tuple[str, dict[str, list[SingleMetric]]]:
        """
        Get and Aggregate metrics.

        :returns:
        """

        # Step 0: get instances/endpoints info
        available_instances, unavailable_instances = InstanceManager().get_all_instances()
        self._clear_inactive_metrics(unavailable_instances)

        # Step 1: get instances/endpoints info and get all endpoints metrics text.
        collects = self._get_server_metrics(available_instances)

        # Step 2: parse metrics text to format data for all instances/endpoints.
        if not self._parse_metrics(collects):
            logger.error("[Metrics] Parse vllm server metrics failed.")
            return "", {}

        # Step 3: for each instance, aggreagte metrics of all endpoints.
        self._aggregate_metrics_by_instance(collects)

        # Step 4: aggreagte metrics of all instances.
        aggregate = self._aggregate_metrics_all_instance(collects)

        # Step 5: serialize and return to handler.
        return self._get_serialize_metrics(aggregate), self._get_serialize_instance_metrics(collects)

