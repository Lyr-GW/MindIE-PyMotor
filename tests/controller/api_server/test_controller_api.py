import os
import pytest
import threading
import logging
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

import motor.controller.api_server.controller_api as controller_api


@pytest.fixture(autouse=True)
def setup():
    """Setup TestClient for all tests"""
    pass  # The client is created in each test that needs it


@pytest.fixture
def client():
    """Create TestClient instance"""
    from motor.config.controller import ControllerConfig
    config = ControllerConfig()
    api_instance = controller_api.ControllerAPI(config)
    return TestClient(api_instance.app)

def test_validate_cert_and_key_success(tmp_path) -> None:
    cert_file = tmp_path / "server.crt"
    key_file = tmp_path / "server.key"
    cert_file.write_text("-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n")
    key_file.write_text("-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----\n")
    # No exception makes this case pass
    controller_api.validate_cert_and_key(str(cert_file), str(key_file))

def test_validate_cert_and_key_file_not_exist(tmp_path) -> None:
    cert_file = tmp_path / "not_exist.crt"
    key_file = tmp_path / "not_exist.key"
    with pytest.raises(FileNotFoundError):
        controller_api.validate_cert_and_key(str(cert_file), str(key_file))

def test_validate_cert_and_key_format_error(tmp_path) -> None:
    cert_file = tmp_path / "bad.crt"
    key_file = tmp_path / "bad.key"
    cert_file.write_text("INVALID CERT DATA\n")
    key_file.write_text("-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----\n")
    with pytest.raises(ValueError):
        controller_api.validate_cert_and_key(str(cert_file), str(key_file))
    # cert is pass but key is wrong
    cert_file.write_text("-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n")
    key_file.write_text("INVALID KEY DATA\n")
    with pytest.raises(ValueError):
        controller_api.validate_cert_and_key(str(cert_file), str(key_file))

@patch('motor.controller.api_server.controller_api.HeartbeatMsg')
@patch('motor.controller.api_server.controller_api.InstanceManager')
def test_heartbeat_success(mock_instance_manager, mock_heartbeat_msg, client) -> None:
    mock_heartbeat_msg.return_value = MagicMock()
    mock_instance_manager.return_value.handle_heartbeat.return_value = 'ok'
    data = {'foo': 'bar'}
    response = client.post('/controller/heartbeat', json=data)
    assert response.status_code == 200
    assert 'result' in response.json()

@patch('motor.controller.api_server.controller_api.HeartbeatMsg', side_effect=Exception('parse error'))
def test_heartbeat_invalid(mock_heartbeat_msg, client) -> None:
    data = {'foo': 'bar'}
    response = client.post('/controller/heartbeat', json=data)
    assert response.status_code == 200
    assert response.json()['error'] == 'Invalid HeartbeatMsg format'

@patch('motor.controller.api_server.controller_api.RegisterMsg')
@patch('motor.controller.api_server.controller_api.InstanceAssembler')
def test_register_success(mock_assembler, mock_register_msg, client) -> None:
    mock_register_msg.return_value = MagicMock()
    mock_assembler.return_value.register.return_value = 'ok'
    data = {'foo': 'bar'}
    response = client.post('/controller/register', json=data)
    assert response.status_code == 200
    assert 'result' in response.json()

@patch('motor.controller.api_server.controller_api.RegisterMsg')
@patch('motor.controller.api_server.controller_api.InstanceAssembler')
def test_register_already_registered(mock_assembler, mock_register_msg, client) -> None:
    mock_register_msg.return_value = MagicMock()
    mock_assembler.return_value.register.return_value = -1
    data = {'foo': 'bar'}
    response = client.post('/controller/register', json=data)
    assert response.status_code == 200
    assert response.json()['error'] == 'Instance already registered'

@patch('motor.controller.api_server.controller_api.RegisterMsg', side_effect=Exception('parse error'))
def test_register_invalid(mock_register_msg, client) -> None:
    data = {'foo': 'bar'}
    response = client.post('/controller/register', json=data)
    assert response.status_code == 200
    assert response.json()['error'] == 'Invalid RegisterMsg format'

@patch('motor.controller.api_server.controller_api.ReregisterMsg')
@patch('motor.controller.api_server.controller_api.InstanceAssembler')
def test_reregister_success(mock_assembler, mock_reregister_msg, client) -> None:
    mock_reregister_msg.return_value = MagicMock()
    mock_assembler.return_value.reregister.return_value = 'ok'
    data = {'foo': 'bar'}
    response = client.post('/controller/reregister', json=data)
    assert response.status_code == 200
    assert 'result' in response.json()

@patch('motor.controller.api_server.controller_api.ReregisterMsg')
@patch('motor.controller.api_server.controller_api.InstanceAssembler')
def test_reregister_already_registered(mock_assembler, mock_reregister_msg, client) -> None:
    mock_reregister_msg.return_value = MagicMock()
    mock_assembler.return_value.reregister.return_value = -1
    data = {'foo': 'bar'}
    response = client.post('/controller/reregister', json=data)
    assert response.status_code == 200
    assert response.json()['error'] == 'Instance already registered'

@patch('motor.controller.api_server.controller_api.ReregisterMsg', side_effect=Exception('parse error'))
def test_reregister_invalid(mock_reregister_msg, client) -> None:
    data = {'foo': 'bar'}
    response = client.post('/controller/reregister', json=data)
    assert response.status_code == 200
    assert response.json()['error'] == 'Invalid ReregisterMsg format'

def test_controller_api_thread_start() -> None:
    from motor.config.controller import ControllerConfig
    config = ControllerConfig()
    with patch.object(threading.Thread, 'start') as mock_start:
        api = controller_api.ControllerAPI(config, '127.0.0.1', 12345)
        api.start()  # Now we need to explicitly call start()
        mock_start.assert_called_once()

def test_api_access_filter_non_uvicorn_access() -> None:
    """Test non uvicorn.access log should return True"""
    filter_instance = controller_api.ApiAccessFilter({"/controller/heartbeat": logging.ERROR})
    record = logging.LogRecord(
        name="other.logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="some message",
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record) is True

def test_api_access_filter_uvicorn_access_non_filtered_path() -> None:
    """Test uvicorn.access log but not contain filtered path should return True"""
    filter_instance = controller_api.ApiAccessFilter({"/controller/heartbeat": logging.ERROR})
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "GET /status HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record) is True

def test_api_access_filter_uvicorn_access_filtered_path_info() -> None:
    """Test uvicorn.access log contain filtered path and level < configured level should return False"""
    filter_instance = controller_api.ApiAccessFilter({"/controller/heartbeat": logging.ERROR})
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/heartbeat HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record) is False

def test_api_access_filter_uvicorn_access_filtered_path_warning() -> None:
    """Test uvicorn.access log contain filtered path and level WARNING < ERROR should return False"""
    filter_instance = controller_api.ApiAccessFilter({"/controller/heartbeat": logging.ERROR})
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/heartbeat HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record) is False

def test_api_access_filter_uvicorn_access_filtered_path_error() -> None:
    """Test uvicorn.access log contain filtered path and level ERROR >= configured level should return True"""
    filter_instance = controller_api.ApiAccessFilter({"/controller/heartbeat": logging.ERROR})
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/heartbeat HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record) is True

def test_api_access_filter_uvicorn_access_filtered_path_critical() -> None:
    """Test uvicorn.access log contain filtered path and level CRITICAL >= configured level should return True"""
    filter_instance = controller_api.ApiAccessFilter({"/controller/heartbeat": logging.ERROR})
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.CRITICAL,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/heartbeat HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record) is True

def test_api_access_filter_getmessage_exception() -> None:
    """Test getMessage to raise exception should return True"""
    filter_instance = controller_api.ApiAccessFilter({"/controller/heartbeat": logging.ERROR})
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/heartbeat HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    # Mock getMessage to raise exception
    record.getMessage = MagicMock(side_effect=Exception("test exception"))
    assert filter_instance.filter(record) is True


def test_api_access_filter_multiple_paths() -> None:
    """Test filtering with multiple API paths configured"""
    api_filters = {
        "/controller/heartbeat": logging.ERROR,
        "/controller/register": logging.WARNING,
        "/controller/reregister": logging.INFO,
    }
    filter_instance = controller_api.ApiAccessFilter(api_filters)

    # Test heartbeat path with INFO level (should be filtered out since INFO < ERROR)
    record_heartbeat = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/heartbeat HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record_heartbeat) is False

    # Test register path with INFO level (should be filtered out since INFO < WARNING)
    record_register = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/register HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record_register) is False

    # Test register path with WARNING level (should be allowed through since WARNING >= WARNING)
    record_register_warning = logging.LogRecord(
        name="uvicorn.access",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/register HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record_register_warning) is True

    # Test reregister path with INFO level (should be allowed through since INFO >= INFO)
    record_reregister = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/reregister HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record_reregister) is True


def test_api_access_filter_empty_config() -> None:
    """Test filter with empty configuration allows all logs through"""
    filter_instance = controller_api.ApiAccessFilter({})

    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/heartbeat HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record) is True


def test_api_access_filter_default_config() -> None:
    """Test filter with default (None) configuration allows all logs through"""
    filter_instance = controller_api.ApiAccessFilter()

    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1:12345 - "POST /controller/heartbeat HTTP/1.1" 200',
        args=(),
        exc_info=None
    )
    assert filter_instance.filter(record) is True


def test_update_config():
    """Test update_config method updates configuration reference"""
    from motor.config.controller import ControllerConfig

    # Create ControllerAPI instance
    config = ControllerConfig()
    api_instance = controller_api.ControllerAPI(config)

    # Store original config
    original_config = api_instance.config

    # Create new config with different settings
    new_config = ControllerConfig()
    new_config.api_config.controller_api_port = 9090
    new_config.api_config.controller_api_dns = "new-api.example.com"

    # Update config
    api_instance.update_config(new_config)

    # Verify config reference was updated
    assert api_instance.config is new_config
    assert api_instance.config.api_config.controller_api_port == 9090
    assert api_instance.config.api_config.controller_api_dns == "new-api.example.com"
