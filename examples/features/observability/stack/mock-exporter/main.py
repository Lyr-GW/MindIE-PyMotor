"""
motor-metrics-mock
------------------

A lightweight Prometheus exporter that emits **mock** metrics matching the
real schema currently exposed by pymotor (engine_server / coordinator) plus
forward-looking schemas (coordinator-level SLI, KV cache, Ascend NPU).

Design goals:

* 1:1 schema fidelity with the real metrics so dashboards do not need to be
  modified when switching from mock to real data.
* All metrics are emitted **without** a ``source`` label; Prometheus is
  expected to inject ``source="mock"`` via relabel_configs at scrape time.
* Drive everything from declarative YAML specs/profiles so adding metrics
  does not require touching this file.
"""

from __future__ import annotations

import logging
import math
import os
import random
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import yaml
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Summary,
    start_http_server,
)


SPECS_DIR = Path(os.environ.get("MOCK_SPECS_DIR", "/app/specs"))
PROFILES_DIR = Path(os.environ.get("MOCK_PROFILES_DIR", "/app/profiles"))
PROFILE_NAME = os.environ.get("MOCK_PROFILE", "default")
LISTEN_PORT = int(os.environ.get("MOCK_PORT", "9105"))
TICK_INTERVAL_SEC = float(os.environ.get("MOCK_TICK_INTERVAL_SEC", "1.0"))


logging.basicConfig(
    level=os.environ.get("MOCK_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("motor-metrics-mock")


# ---------------------------------------------------------------------------
# Profile / spec loading
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


def load_profile(profile_name: str) -> dict[str, Any]:
    path = PROFILES_DIR / f"{profile_name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Profile not found: {path}")
    profile = _load_yaml(path)
    logger.info("Loaded profile %s from %s", profile_name, path)
    return profile


def load_spec_files(spec_names: Iterable[str]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for name in spec_names:
        path = SPECS_DIR / f"{name}.yaml"
        if not path.is_file():
            logger.warning("Spec file not found, skipping: %s", path)
            continue
        spec = _load_yaml(path)
        items = spec.get("metrics", []) or []
        for item in items:
            item["_source_spec"] = name
        logger.info("Loaded %d metrics from spec %s", len(items), name)
        metrics.extend(items)
    return metrics


# ---------------------------------------------------------------------------
# Dimension expansion (instance_id, npu id, pod info, etc.)
# ---------------------------------------------------------------------------

def expand_instance_dimensions(profile: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Generate ordered dimension tuples for various label combinations.

    Returns a dict keyed by dimension-kind, each value is a list of
    label_dict; the caller selects which keys it needs.
    """

    deploy = profile.get("deploy", {})
    job_id = deploy.get("job_id", "mindie-motor")
    p_num = int(deploy.get("p_instances_num", 1))
    d_num = int(deploy.get("d_instances_num", 1))
    p_pod = int(deploy.get("single_p_instance_pod_num", 1))
    d_pod = int(deploy.get("single_d_instance_pod_num", 1))
    p_npu = int(deploy.get("p_pod_npu_num", 8))
    d_npu = int(deploy.get("d_pod_npu_num", 8))
    hw_type = deploy.get("hardware_type", "800I_A2")

    # NPU chip model name follows mind-cluster npu-exporter convention.
    # 800I_A3 → Ascend910B4, 800I_A2 → Ascend910B3 (approx for mock purposes).
    chip_model_name = "910B-Ascend-V1"

    instances: list[dict[str, str]] = []
    npu_entries: list[dict[str, str]] = []

    instance_id_counter = 0
    npu_global_id = 0
    for role, role_str, n_instances, n_pods, n_npu in (
        ("p", "prefill", p_num, p_pod, p_npu),
        ("d", "decode", d_num, d_pod, d_npu),
    ):
        for i in range(n_instances):
            job_name = f"{job_id}-{role}{i}"
            instances.append(
                {
                    "instance_id": str(instance_id_counter),
                    "job_name": job_name,
                    "pd_role": role_str,
                }
            )
            for pod_idx in range(n_pods):
                pod_name = f"{job_name}-{pod_idx}"
                namespace = job_id
                container_name = "engine"
                pcie_bus_prefix = "0000:61"
                for npu_idx in range(n_npu):
                    npu_entries.append(
                        {
                            "id": str(npu_global_id),
                            "model_name": chip_model_name,
                            "pcie_bus_info": f"{pcie_bus_prefix}:{npu_idx:02d}.0",
                            "vdie_id": f"{npu_global_id:08X}-"
                            "00000000-00000000-00000000-00000000",
                            "container_name": container_name,
                            "pod_name": pod_name,
                            "namespace": namespace,
                        }
                    )
                    npu_global_id += 1
            instance_id_counter += 1

    return {
        "instances": instances,
        "npu": npu_entries,
        "deploy": [
            {
                "p_instances_num": str(p_num),
                "d_instances_num": str(d_num),
                "p_pod_npu_num": str(p_npu),
                "d_pod_npu_num": str(d_npu),
                "hardware_type": hw_type,
                "job_id": job_id,
            }
        ],
    }


def cartesian_label_combinations(
    label_names: list[str],
    label_values: dict[str, list[str]],
    fallback_values: dict[str, list[str]] | None = None,
) -> list[dict[str, str]]:
    """Expand explicitly enumerated label values into Cartesian product."""

    fallback_values = fallback_values or {}
    pools: list[list[tuple[str, str]]] = []
    for name in label_names:
        if name in label_values:
            values = label_values[name]
        elif name in fallback_values:
            values = fallback_values[name]
        else:
            continue
        pools.append([(name, v) for v in values])

    if not pools:
        return [{}]

    combos = [{}]
    for pool in pools:
        new_combos = []
        for combo in combos:
            for k, v in pool:
                merged = dict(combo)
                merged[k] = v
                new_combos.append(merged)
        combos = new_combos
    return combos


# ---------------------------------------------------------------------------
# Value generators
# ---------------------------------------------------------------------------

class ValueGenerator:
    """Stateful generator for per-label-set values."""

    def __init__(self, spec_value: dict[str, Any], profile: dict[str, Any]) -> None:
        self.cfg = spec_value or {}
        self.profile = profile
        self.t0 = time.time()
        self._counter_state: dict[tuple, float] = defaultdict(float)
        self._counter_last_ts: dict[tuple, float] = {}

    def _now(self) -> float:
        return time.time()

    def _elapsed(self) -> float:
        return self._now() - self.t0

    # -- Gauge generators -------------------------------------------------

    def gauge_sin(self, _label_tuple: tuple) -> float:
        cfg = self.cfg
        base = float(cfg.get("base", 0.0))
        amp = float(cfg.get("amp", 0.0))
        period = max(1.0, float(cfg.get("period_sec", 60.0)))
        noise = float(cfg.get("noise", 0.0))
        clamp = cfg.get("clamp")
        value = base + amp * math.sin(2 * math.pi * self._elapsed() / period)
        if noise:
            value += random.gauss(0.0, noise)
        if clamp:
            value = max(clamp[0], min(clamp[1], value))
        return value

    def pd_active_count(self, _label_tuple: tuple) -> float:
        deploy = self.profile.get("deploy", {})
        role = self.cfg.get("role", "prefill")
        n = int(deploy.get("p_instances_num" if role == "prefill" else "d_instances_num", 0))
        # Allow occasional dips by 1 (simulate transient unavailability).
        if n > 0 and random.random() < 0.02:
            return float(n - 1)
        return float(n)

    def pd_inactive_count(self, _label_tuple: tuple) -> float:
        deploy = self.profile.get("deploy", {})
        role = self.cfg.get("role", "prefill")
        n = int(deploy.get("p_instances_num" if role == "prefill" else "d_instances_num", 0))
        # Mirror pd_active_count: when active dips to n-1, inactive becomes 1.
        if n > 0 and random.random() < 0.02:
            return 1.0
        return 0.0

    def constant(self, _label_tuple: tuple) -> float:
        return float(self.cfg.get("value", 1.0))

    def gauge_npu_total_memory_mb(self, _label_tuple: tuple) -> float:
        hw = self.profile.get("deploy", {}).get("hardware_type", "800I_A2")
        return 131072.0 if hw == "800I_A3" else 65536.0

    def gauge_npu_used_memory_mb(self, _label_tuple: tuple) -> float:
        total = self.gauge_npu_total_memory_mb(_label_tuple)
        ratio = 0.3 + 0.6 * (0.5 + 0.5 * math.sin(2 * math.pi * self._elapsed() / 300.0))
        ratio += random.gauss(0.0, 0.02)
        return max(0.0, min(total, total * ratio))

    # -- Counter generators ----------------------------------------------

    def counter_rate_increment(self, label_tuple: tuple) -> float:
        rate = float(self.cfg.get("rate_per_sec", 0.0))
        now = self._now()
        last = self._counter_last_ts.get(label_tuple)
        self._counter_last_ts[label_tuple] = now
        dt = TICK_INTERVAL_SEC if last is None else max(0.0, now - last)
        # Poisson-ish jitter: ±20%
        jitter = 1.0 + random.uniform(-0.2, 0.2)
        return max(0.0, rate * dt * jitter)

    def counter_rate_per_label_increment(
        self, label_tuple: tuple, label_dict: dict[str, str]
    ) -> float:
        """Per-label-value rate map; resolves the rate from a label key
        defined in the spec (e.g. ``finished_reason`` or ``direction``)."""
        per_label_map = None
        per_label_key = None
        for k in ("finished_reason", "direction"):
            if k in self.cfg:
                per_label_map = self.cfg[k]
                per_label_key = k
                break
        if per_label_map is None or per_label_key is None:
            return 0.0
        rate = float(per_label_map.get(label_dict.get(per_label_key, ""), 0.0))
        now = self._now()
        last = self._counter_last_ts.get(label_tuple)
        self._counter_last_ts[label_tuple] = now
        dt = TICK_INTERVAL_SEC if last is None else max(0.0, now - last)
        jitter = 1.0 + random.uniform(-0.2, 0.2)
        return max(0.0, rate * dt * jitter)

    # -- Histogram / Summary observe generators --------------------------

    @staticmethod
    def _sample_count(rate: float) -> int:
        """Unbiased integer sample count for the current tick.

        Splits ``rate * TICK_INTERVAL_SEC`` into integer + fractional parts
        and uses a Bernoulli trial for the fractional part so very small
        rates (e.g. 0.25/tick) still produce occasional samples.
        """
        expected = rate * TICK_INTERVAL_SEC * (1.0 + random.uniform(-0.2, 0.2))
        if expected <= 0:
            return 0
        n_int = int(expected)
        frac = expected - n_int
        if frac > 0 and random.random() < frac:
            n_int += 1
        return n_int

    def histogram_lognormal_samples(self, _label_tuple: tuple) -> list[float]:
        rate = float(self.cfg.get("rate_per_sec", 0.0))
        n = self._sample_count(rate)
        if n <= 0:
            return []
        mu = float(self.cfg.get("mu", 0.0))
        sigma = float(self.cfg.get("sigma", 1.0))
        return [random.lognormvariate(mu, sigma) for _ in range(n)]

    def histogram_constant_samples(self, _label_tuple: tuple) -> list[float]:
        rate = float(self.cfg.get("rate_per_sec", 0.0))
        n = self._sample_count(rate)
        if n <= 0:
            return []
        return [float(self.cfg.get("constant", 1.0))] * n

    def summary_uniform_samples(self, _label_tuple: tuple) -> list[float]:
        rate = float(self.cfg.get("rate_per_sec", 0.0))
        n = self._sample_count(rate)
        if n <= 0:
            return []
        low = float(self.cfg.get("low", 0.0))
        high = float(self.cfg.get("high", 1.0))
        return [random.uniform(low, high) for _ in range(n)]


# ---------------------------------------------------------------------------
# Metric registration / update
# ---------------------------------------------------------------------------

class MockMetric:
    def __init__(
        self,
        spec: dict[str, Any],
        registry: CollectorRegistry,
        profile: dict[str, Any],
        dims: dict[str, list[dict[str, str]]],
    ) -> None:
        self.spec = spec
        self.profile = profile
        self.dims = dims
        self.name = spec["name"]
        self.metric_type = spec["type"].lower()
        self.help_text = spec.get("help", "")
        self.label_names: list[str] = list(spec.get("labels") or [])
        self.buckets = spec.get("buckets")
        self.value_cfg = spec.get("value") or {}
        self.label_value_pool: dict[str, list[str]] = spec.get("label_values") or {}
        self.value_mode = self.value_cfg.get("mode", "")
        self.generator = ValueGenerator(self.value_cfg, profile)

        # Build label-set combinations once.
        self.label_combos = self._build_label_combos()

        # Register the prometheus_client metric family.
        self.metric = self._create_metric(registry)

    def _build_label_combos(self) -> list[dict[str, str]]:
        fallback: dict[str, list[str]] = {}

        # model_name / model labels come from profile.models[*]
        models = self.profile.get("models", []) or []
        if "model_name" in self.label_names:
            fallback["model_name"] = list(models)
        if "model" in self.label_names:
            fallback["model"] = list(models)

        # pd_role / instance_id come from expanded dims.
        if any(n in self.label_names for n in ("pd_role", "instance_id")) and not (
            "pd_role" in self.label_value_pool or "instance_id" in self.label_value_pool
        ):
            combos: list[dict[str, str]] = []
            for inst in self.dims["instances"]:
                base = {"pd_role": inst["pd_role"], "instance_id": inst["instance_id"]}
                # Combine with model if needed.
                if "model" in self.label_names or "model_name" in self.label_names:
                    model_key = "model" if "model" in self.label_names else "model_name"
                    for m in models or [""]:
                        merged = dict(base)
                        merged[model_key] = m
                        combos.append({k: merged[k] for k in self.label_names if k in merged})
                else:
                    combos.append({k: base[k] for k in self.label_names if k in base})

            # If finished_reason / direction explicit pools exist, multiply.
            for explicit in ("finished_reason", "direction"):
                if explicit in self.label_names and explicit in self.label_value_pool:
                    new_combos: list[dict[str, str]] = []
                    for combo in combos:
                        for v in self.label_value_pool[explicit]:
                            merged = dict(combo)
                            merged[explicit] = v
                            new_combos.append(merged)
                    combos = new_combos
            return combos or [{}]

        # NPU labels: use dims["npu"] directly.
        if "id" in self.label_names and "pcie_bus_info" in self.label_names:
            combos = []
            for entry in self.dims["npu"]:
                combo = {k: entry.get(k, "") for k in self.label_names if k in entry}
                # Extra explicit pools (e.g. chip_name).
                for extra_key, extra_values in self.label_value_pool.items():
                    if extra_key not in entry:
                        # Only use the first value of the pool for info gauges.
                        combo[extra_key] = extra_values[0]
                combos.append({k: combo.get(k, "") for k in self.label_names})
            return combos or [{}]

        # Fallback: Cartesian product of label_values + fallback_values.
        return cartesian_label_combinations(self.label_names, self.label_value_pool, fallback)

    def _create_metric(self, registry: CollectorRegistry):
        if self.metric_type == "gauge":
            return Gauge(self.name, self.help_text, self.label_names, registry=registry)
        if self.metric_type == "counter":
            # prometheus_client appends "_total" to counter base name in the
            # exposition, so we must NOT include "_total" in the constructor
            # name. Use without suffix and prometheus_client adds it.
            base = self.name[:-len("_total")] if self.name.endswith("_total") else self.name
            return Counter(base, self.help_text, self.label_names, registry=registry)
        if self.metric_type == "histogram":
            buckets = list(self.buckets or []) + [float("inf")]
            return Histogram(
                self.name,
                self.help_text,
                self.label_names,
                buckets=buckets,
                registry=registry,
            )
        if self.metric_type == "summary":
            return Summary(self.name, self.help_text, self.label_names, registry=registry)
        if self.metric_type == "info_gauge":
            # Info-style: emit as Gauge with always-on combos.
            return Gauge(self.name, self.help_text, self.label_names, registry=registry)
        raise ValueError(f"Unknown metric type: {self.metric_type}")

    # -- Update -----------------------------------------------------------

    def _label_tuple(self, combo: dict[str, str]) -> tuple:
        return tuple(combo.get(n, "") for n in self.label_names)

    def update(self) -> None:
        for combo in self.label_combos:
            label_tuple = self._label_tuple(combo)
            child = self.metric.labels(*label_tuple) if self.label_names else self.metric

            if self.metric_type in ("gauge", "info_gauge"):
                value = self._gauge_value(label_tuple)
                child.set(value)
            elif self.metric_type == "counter":
                if self.value_mode == "counter_rate_per_label":
                    inc = self.generator.counter_rate_per_label_increment(label_tuple, combo)
                else:
                    inc = self.generator.counter_rate_increment(label_tuple)
                if inc > 0:
                    child.inc(inc)
            elif self.metric_type == "histogram":
                samples = self._histogram_samples(label_tuple)
                for s in samples:
                    child.observe(s)
            elif self.metric_type == "summary":
                samples = self._summary_samples(label_tuple)
                for s in samples:
                    child.observe(s)

    def _gauge_value(self, label_tuple: tuple) -> float:
        mode = self.value_mode
        handler = getattr(self.generator, mode, None)
        if handler is None:
            return 0.0
        return float(handler(label_tuple))

    def _histogram_samples(self, label_tuple: tuple) -> list[float]:
        if self.value_mode == "histogram_lognormal":
            return self.generator.histogram_lognormal_samples(label_tuple)
        if self.value_mode == "histogram_constant":
            return self.generator.histogram_constant_samples(label_tuple)
        return []

    def _summary_samples(self, label_tuple: tuple) -> list[float]:
        if self.value_mode == "summary_uniform":
            return self.generator.summary_uniform_samples(label_tuple)
        return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    logger.info(
        "Starting motor-metrics-mock on port %d (profile=%s, specs_dir=%s, profiles_dir=%s)",
        LISTEN_PORT,
        PROFILE_NAME,
        SPECS_DIR,
        PROFILES_DIR,
    )

    try:
        profile = load_profile(PROFILE_NAME)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1

    spec_names = profile.get("specs", []) or [
        "motor",
        "http",
        "vllm",
        "coordinator_future",
        "kv_future",
        "npu",
    ]
    metrics_specs = load_spec_files(spec_names)

    registry = CollectorRegistry()
    dims = expand_instance_dimensions(profile)
    mock_metrics: list[MockMetric] = []
    for spec in metrics_specs:
        try:
            mm = MockMetric(spec, registry, profile, dims)
            mock_metrics.append(mm)
            logger.info(
                "Registered %s (%s) with %d label combinations",
                mm.name,
                mm.metric_type,
                len(mm.label_combos),
            )
        except Exception as exc:
            logger.exception("Failed to register metric %s: %s", spec.get("name"), exc)

    start_http_server(LISTEN_PORT, registry=registry)
    logger.info("Mock exporter listening on :%d/metrics", LISTEN_PORT)

    stop_event = threading.Event()

    def ticker() -> None:
        while not stop_event.is_set():
            for mm in mock_metrics:
                try:
                    mm.update()
                except Exception:
                    logger.exception("Failed to update metric %s", mm.name)
            stop_event.wait(TICK_INTERVAL_SEC)

    t = threading.Thread(target=ticker, daemon=True, name="mock-ticker")
    t.start()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop_event.set()
        logger.info("Shutting down")
        return 0


if __name__ == "__main__":
    sys.exit(main())
