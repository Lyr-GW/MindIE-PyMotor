# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "deployer"
    / "startup"
    / "roles"
    / "kv_store_backends"
    / "memcache"
    / "memcache_meta_service.py"
)


def _load_module(monkeypatch):
    captured = SimpleNamespace(config=None)

    class FakeMetaConfig:
        pass

    class FakeMetaService:
        @staticmethod
        def setup(config):
            captured.config = config

        @staticmethod
        def main():
            pass

    fake_dependency = SimpleNamespace(MetaService=FakeMetaService, MetaConfig=FakeMetaConfig)
    monkeypatch.setitem(sys.modules, "memcache_hybrid", fake_dependency)
    spec = importlib.util.spec_from_file_location("memcache_meta_service", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, captured


def test_main_brackets_ipv6_service_urls(monkeypatch):
    module, captured = _load_module(monkeypatch)
    monkeypatch.setenv("POD_IP", "2001:db8::8")
    monkeypatch.setenv("KV_CACHE_STORE_PORT", "50088")
    monkeypatch.setenv("MMC_CONFIG_STORE_URL", "tcp://0.0.0.0:50089")
    monkeypatch.setenv("MMC_METRICS_URL", "http://0.0.0.0:50090")

    module.main()

    assert captured.config.meta_service_url == "tcp://[2001:db8::8]:50088"
    assert captured.config.config_store_url == "tcp://[2001:db8::8]:50089"
    assert captured.config.metrics_url == "http://[2001:db8::8]:50090"
