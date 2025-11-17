#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
import json
import pytest
import sys
import asyncio
from unittest.mock import MagicMock, Mock
from fastapi import FastAPI, Request, Response
from starlette.responses import JSONResponse, StreamingResponse
from starlette.testclient import TestClient


@pytest.fixture(autouse=True, scope="module")
def mock_logger_module():
    """Mock logger module completely to intercept all logger-related imports during import phase"""
    # First check and save original modules (if they exist)
    original_modules = {}
    logger_module_name = 'motor.engine_server.utils.logger'
    
    if logger_module_name in sys.modules:
        original_modules[logger_module_name] = sys.modules[logger_module_name]
    
    # Create a minimal mock for LogConfig to avoid permission checks
    class MockLogConfig:
        def __init__(self):
            pass
        def build_config(self):
            pass
        def build_log_path(self):
            pass
    
    # Create mock logger module
    mock_logger = Mock()
    mock_logger.get_logger = MagicMock(return_value=Mock())
    mock_logger.LogConfig = MockLogConfig
    
    # Replace module in sys.modules
    sys.modules[logger_module_name] = mock_logger
    
    # Build dictionary of mock objects to return
    mock_objects = {
        'run_log': mock_logger.get_logger.return_value
    }
    
    # Provide mock objects to tests
    yield mock_objects
    
    # Cleanup: restore original modules or remove mock modules
    if logger_module_name in original_modules:
        sys.modules[logger_module_name] = original_modules[logger_module_name]
    elif logger_module_name in sys.modules:
        del sys.modules[logger_module_name]


@pytest.fixture(autouse=True, scope="module")
def mock_vllm_module():
    """Mock vllm module and its submodules completely to intercept all vllm-related imports during import phase"""
    # First check and save original modules (if they exist)
    original_modules = {}
    vllm_related_modules = [
        'vllm',
        'vllm.engine',
        'vllm.engine.async_llm_engine',
        'motor.engine_server.utils.ranktable'
    ]

    # Save original modules
    for module_name in vllm_related_modules:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]

    # Create mock module structure for vllm
    mock_vllm = Mock()
    mock_vllm.engine = Mock()
    mock_vllm.engine.async_llm_engine = Mock()
    mock_vllm.engine.async_llm_engine.AsyncLLMEngine = MagicMock()

    # Mock AsyncLLMEngine methods
    mock_async_llm_engine = MagicMock()
    mock_async_llm_engine.generate = MagicMock()
    mock_async_llm_engine.generate_async = MagicMock()
    mock_async_llm_engine.generate_stream = MagicMock()
    mock_async_llm_engine.generate_stream_async = MagicMock()
    mock_async_llm_engine.create_async_engine = MagicMock(return_value=mock_async_llm_engine)
    mock_async_llm_engine.from_engine_args = MagicMock(return_value=mock_async_llm_engine)
    mock_vllm.engine.async_llm_engine.AsyncLLMEngine = mock_async_llm_engine

    # Mock ranktable
    mock_ranktable = Mock()
    mock_ranktable.get_data_parallel_address = MagicMock(return_value="127.0.0.1")

    # Replace modules in sys.modules
    sys.modules['vllm'] = mock_vllm
    sys.modules['vllm.engine'] = mock_vllm.engine
    sys.modules['vllm.engine.async_llm_engine'] = mock_vllm.engine.async_llm_engine
    sys.modules['motor.engine_server.utils.ranktable'] = mock_ranktable

    # Build dictionary of mock objects to return
    mock_objects = {
        'vllm_module': mock_vllm,
        'async_llm_engine': mock_async_llm_engine,
        'get_data_parallel_address': mock_ranktable.get_data_parallel_address
    }

    # Provide mock objects to tests
    yield mock_objects

    # Cleanup: restore original modules or remove mock modules
    for module_name in vllm_related_modules:
        if module_name in original_modules:
            sys.modules[module_name] = original_modules[module_name]
        elif module_name in sys.modules:
            del sys.modules[module_name]


# Import modules after mocking logger and vllm
from motor.engine_server.constants.constants import (
    APPLICATION_JSON,
    DATA_PREFIX,
    DATA_DONE,
    COMPLETIONS_PATH,
    TEXT_EVENT_STREAM,
    JSON_ID_FIELD,
    COMPLETION_PREFIX
)
from motor.engine_server.core.vllm.vllm_adaptor import (
    trim_request_for_stream,
    trim_request_for_non_stream,
    create_single_chunk_iter,
    trim_id_prefix,
    VllmMiddleware
)


@pytest.fixture
def logger_mock(mock_logger_module):
    return mock_logger_module['run_log']


@pytest.fixture
def vllm_middleware():
    return VllmMiddleware(app=MagicMock())


@pytest.fixture
def test_app():
    return FastAPI()


@pytest.fixture
def test_client(test_app):
    return TestClient(test_app)


class TestVLLMUtils:
    def test_trim_id_prefix(self):
        # Test with chat completion prefix
        data = {"id": "chatcmpl-123", "other": "value"}
        trim_id_prefix(data)
        assert data["id"] == "123"
        
        # Test with completion prefix
        data = {"id": "cmpl-123", "other": "value"}
        trim_id_prefix(data)
        assert data["id"] == "123"
        
        # Test with no prefix
        data = {"id": "123", "other": "value"}
        trim_id_prefix(data)
        assert data["id"] == "123"
        
        # Test with no id field
        data = {"other": "value"}
        trim_id_prefix(data)
        assert "id" not in data
    
    @pytest.mark.asyncio
    async def test_create_single_chunk_iter(self):
        content = b"test content"
        result = []
        async for chunk in create_single_chunk_iter(content):
            result.append(chunk)
        assert len(result) == 1
        assert result[0] == content
    
    @pytest.mark.asyncio
    async def test_trim_request_for_non_stream(self):
        # Test with valid JSON containing chat completion prefix
        content = b'{"id": "chatcmpl-123", "choices": []}'
        result = await trim_request_for_non_stream(content, "application/json")
        assert b'"id": "123"' in result
        
        # Test with valid JSON containing completion prefix
        content = b'{"id": "cmpl-123", "choices": []}'
        result = await trim_request_for_non_stream(content, "application/json")
        assert b'"id": "123"' in result
        
        # Test with invalid content type
        content = b'{"id": "chatcmpl-123"}'
        result = await trim_request_for_non_stream(content, "text/plain")
        assert result == content
    
    @pytest.mark.asyncio
    async def test_trim_request_for_stream(self):
        # Mock async iterable
        async def mock_iterable():
            yield b'data: {"id": "chatcmpl-123", "choices": []}\n\n'
            yield b'data: {"id": "cmpl-456", "choices": []}\n'
            yield b'data: [DONE]\n'
            yield b'other: not a data chunk\n'
        
        result = []
        async for chunk in trim_request_for_stream(mock_iterable()):
            result.append(chunk)
        
        assert len(result) == 4
        assert b'"id":"123"' in result[0]
        assert b'"id":"456"' in result[1]
        assert b'data: [DONE]\n' in result[2]
        assert b'other: not a data chunk\n' in result[3]

class TestVllmMiddleware:
    def test_init(self, vllm_middleware):
        assert isinstance(vllm_middleware, VllmMiddleware)
    


def test_middleware_id_with_prefix(test_app, test_client):
    @test_app.post(COMPLETIONS_PATH)
    async def with_prefix_id():
        return JSONResponse({JSON_ID_FIELD: f'{COMPLETION_PREFIX}123', "content": "test"})
    
    response = test_client.post(COMPLETIONS_PATH)
    data = response.json()
    assert data[JSON_ID_FIELD] == f'{COMPLETION_PREFIX}123'  # Prefix is not removed

def test_middleware_id_without_prefix(test_app, test_client):
    @test_app.post(COMPLETIONS_PATH)
    async def no_prefix_id():
        return JSONResponse({JSON_ID_FIELD: "12345", "content": "test"})
    
    response = test_client.post(COMPLETIONS_PATH)
    data = response.json()
    assert data[JSON_ID_FIELD] == "12345"  # Should remain unchanged

def test_middleware_stream_without_newlines(test_app, test_client):
    @test_app.post(COMPLETIONS_PATH)
    async def stream_no_newlines():
        async def generator():
            yield f"{DATA_PREFIX}{json.dumps({JSON_ID_FIELD: f'{COMPLETION_PREFIX}123'})}"
            yield f"{DATA_PREFIX}{json.dumps({JSON_ID_FIELD: f'{COMPLETION_PREFIX}123'})}\n"
            yield f"{DATA_DONE}"
        return StreamingResponse(generator(), media_type=TEXT_EVENT_STREAM)
    
    response = test_client.post(COMPLETIONS_PATH)
    content = response.text
    assert DATA_PREFIX in content and DATA_DONE in content
    assert f'"id": "{COMPLETION_PREFIX}123"' in content