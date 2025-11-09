import os
import time
import json
import pytest
import tempfile
from unittest.mock import patch, MagicMock

from motor.config.controller import (
    ControllerConfig,
    find_config_file,
    set_config_path,
    get_config_path
)


@pytest.fixture
def temp_json_file():
    """Fixture for temporary JSON file that gets cleaned up."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = f.name

    yield temp_path

    # Cleanup
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def temp_dir():
    """Fixture for temporary directory that gets cleaned up."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def reset_config_path():
    """Fixture to reset config path override after each test."""
    yield
    # Reset after test
    import motor.config.controller as config_module
    config_module.CONFIG_PATH_OVERRIDE = None


def test_default_config_initialization():
    """Test default configuration initialization"""
    config = ControllerConfig()

    # Verify default values
    assert config.instance_assemble_timeout == 600
    assert config.instance_assembler_check_internal == 1
    assert config.instance_assembler_cmd_send_internal == 1
    assert config.max_link_number == 768
    assert config.send_cmd_retry_times == 3
    assert config.instance_manager_check_internal == 1
    assert config.instance_heartbeat_timeout == 5
    assert config.instance_expired_timeout == 300
    assert config.controller_api_host == '127.0.0.1'
    assert config.controller_api_port == 8000
    assert config.enable_tls is False
    assert config.cert_path == 'security/controller/cert/server.crt'
    assert config.key_path == 'security/controller/keys/server.key'
    assert config.enable_fault_tolerance is True
    assert config.strategy_center_check_internal == 1


def test_config_validation_success():
    """Test successful configuration validation"""
    config = ControllerConfig(
        instance_assemble_timeout=300,
        instance_heartbeat_timeout=10,
        instance_expired_timeout=600,
        controller_api_port=9000,
        max_link_number=1000,
        send_cmd_retry_times=5
    )
    # If no exception is raised, validation passed
    assert config.controller_api_port == 9000


@pytest.mark.parametrize("param,value,expected_error", [
    ("instance_assemble_timeout", -1, "instance_assemble_timeout must be greater than 0"),
    ("instance_heartbeat_timeout", 0, "instance_heartbeat_timeout must be greater than 0"),
    ("instance_assembler_check_internal", -1, "instance_assembler_check_internal must be greater than 0"),
    ("controller_api_port", 0, "controller_api_port must be in range 1-65535"),
    ("controller_api_port", 65536, "controller_api_port must be in range 1-65535"),
    ("send_cmd_retry_times", -1, "send_cmd_retry_times cannot be negative"),
    ("max_link_number", 0, "max_link_number must be greater than 0"),
])
def test_config_validation_errors(param, value, expected_error):
    """Test various configuration validation errors"""
    with pytest.raises(ValueError, match=expected_error):
        ControllerConfig(**{param: value})


def test_config_validation_multiple_errors():
    """Test multiple configuration errors"""
    with pytest.raises(ValueError) as exc_info:
        ControllerConfig(
            instance_assemble_timeout=-1,
            controller_api_port=0,
            max_link_number=-1
        )
    error_msg = str(exc_info.value)
    assert "instance_assemble_timeout must be greater than 0" in error_msg
    assert "controller_api_port must be in range 1-65535" in error_msg
    assert "max_link_number must be greater than 0" in error_msg


def test_from_json_success(temp_json_file):
    """Test loading configuration from valid JSON file"""
    test_config = {
        "controller_api_host": "192.168.1.1",
        "controller_api_port": 9000,
        "instance_assemble_timeout": 300,
        "max_link_number": 1000,
        "enable_fault_tolerance": False
    }

    with open(temp_json_file, 'w') as f:
        json.dump(test_config, f)

    config = ControllerConfig.from_json(temp_json_file)
    assert config.controller_api_host == "192.168.1.1"
    assert config.controller_api_port == 9000
    assert config.instance_assemble_timeout == 300
    assert config.max_link_number == 1000
    assert config.enable_fault_tolerance is False
    assert config.config_path == temp_json_file
    assert config.last_modified is not None


def test_from_json_file_not_exists(temp_dir):
    """Test loading configuration from non-existent JSON file (using default values)"""
    non_existent_path = os.path.join(temp_dir, "non_existent.json")
    config = ControllerConfig.from_json(non_existent_path)

    # Should use default values
    assert config.controller_api_host == '127.0.0.1'
    assert config.controller_api_port == 8000
    assert config.config_path == non_existent_path
    assert config.last_modified is None


def test_from_json_invalid_json(temp_json_file):
    """Test loading configuration from invalid JSON file"""
    with open(temp_json_file, 'w') as f:
        f.write("invalid json content")

    with pytest.raises(ValueError, match="Configuration file.*format error"):
        ControllerConfig.from_json(temp_json_file)


def test_reload_config_file_not_exists(temp_dir):
    """Test reloading non-existent configuration file"""
    config = ControllerConfig()
    non_existent_path = os.path.join(temp_dir, "non_existent.json")
    config.config_path = non_existent_path
    assert config.reload() is False


def test_reload_config_file_not_modified(temp_json_file):
    """Test reloading unmodified configuration file"""
    test_config = {"controller_api_port": 8000}
    with open(temp_json_file, 'w') as f:
        json.dump(test_config, f)

    config = ControllerConfig.from_json(temp_json_file)
    # First reload should succeed (file not modified)
    assert config.reload() is True


def test_reload_config_file_modified(temp_json_file):
    """Test reloading modified configuration file"""
    test_config = {"controller_api_port": 8000}
    modified_config = {"controller_api_port": 9000}

    with open(temp_json_file, 'w') as f:
        json.dump(test_config, f)

    config = ControllerConfig.from_json(temp_json_file)
    original_port = config.controller_api_port

    # Wait a short time to ensure different file modification time
    time.sleep(0.1)

    # Modify file
    with open(temp_json_file, 'w') as f:
        json.dump(modified_config, f)

    # Reload configuration
    assert config.reload() is True
    assert config.controller_api_port == 9000
    assert config.controller_api_port != original_port


def test_reload_config_invalid_json(temp_json_file):
    """Test reloading invalid JSON configuration file"""
    test_config = {"controller_api_port": 8000}
    with open(temp_json_file, 'w') as f:
        json.dump(test_config, f)

    config = ControllerConfig.from_json(temp_json_file)

    time.sleep(0.01)

    # Write invalid JSON
    with open(temp_json_file, 'w') as f:
        f.write("invalid json")

    # Manually update file modification time
    current_time = time.time()
    os.utime(temp_json_file, (current_time, current_time))

    assert config.reload() is False


def test_to_dict():
    """Test conversion to dictionary"""
    config = ControllerConfig(
        controller_api_host="192.168.1.1",
        controller_api_port=9000,
        instance_assemble_timeout=300
    )

    config_dict = config.to_dict()

    assert config_dict["controller_api_host"] == "192.168.1.1"
    assert config_dict["controller_api_port"] == 9000
    assert config_dict["instance_assemble_timeout"] == 300
    assert "_config_path" not in config_dict
    assert "_last_modified" not in config_dict


def test_save_to_json_success(temp_json_file):
    """Test successful saving configuration to JSON file"""
    config = ControllerConfig(controller_api_port=9000)

    result = config.save_to_json(temp_json_file)
    assert result is True

    # Verify file content
    with open(temp_json_file, 'r') as f:
        saved_config = json.load(f)
    assert saved_config["controller_api_port"] == 9000


def test_save_to_json_no_path():
    """Test saving configuration to unspecified path"""
    config = ControllerConfig()
    assert config.save_to_json() is False


def test_save_to_json_write_error(temp_dir):
    """Test write error when saving configuration"""
    config = ControllerConfig()
    test_path = os.path.join(temp_dir, "config.json")
    config.config_path = test_path

    with patch('builtins.open', side_effect=PermissionError("Permission denied")):
        assert config.save_to_json() is False


def test_get_config_summary():
    """Test getting configuration summary"""
    config = ControllerConfig(
        controller_api_host="192.168.1.1",
        controller_api_port=9000,
        instance_assemble_timeout=300,
        max_link_number=1000,
        enable_fault_tolerance=False
    )
    # Use a temporary path for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        test_path = os.path.join(temp_dir, "config.json")
        config.config_path = test_path

        summary = config.get_config_summary()

        assert "192.168.1.1:9000" in summary
        assert "300 seconds" in summary
        assert "1000" in summary
        assert "Disabled" in summary
        assert test_path in summary


def test_get_config_summary_no_path():
    """Test getting configuration summary (no path)"""
    config = ControllerConfig()
    summary = config.get_config_summary()
    assert "Not set" in summary


def test_find_config_file_scenarios():
    """Test various scenarios for finding configuration file"""
    os_path_exists, os_path_dirname = 'os.path.exists', 'os.path.dirname'
    # Test when package config exists
    with patch(os_path_exists, return_value=True) as mock_exists:
        with patch(os_path_dirname, return_value="/mock/package/dir"):
            result = find_config_file()
            assert result == "/mock/package/dir/controller_config.json"

    # Test fallback to project root when package config doesn't exist
    def mock_exists_fallback(path):
        return "motor/config" not in path and "controller_config.json" in path

    with patch(os_path_exists, side_effect=mock_exists_fallback):
        with patch(os_path_dirname) as mock_dirname:
            def mock_dirname_side_effect(path):
                if "motor/config" in path:
                    return "/mock/project/root/motor/config"
                elif path == "/mock/project/root/motor/config":
                    return "/mock/project/root/motor"
                elif path == "/mock/project/root/motor":
                    return "/mock/project/root"
                return "/mock/project/root"

            mock_dirname.side_effect = mock_dirname_side_effect
            result = find_config_file()
            assert "controller_config.json" in result

    # Test when no config file is found
    with patch(os_path_exists, return_value=False):
        with patch(os_path_dirname, return_value="/mock/package/dir"):
            result = find_config_file()
            assert result == "/mock/package/dir/controller_config.json"


def test_config_boundary_values():
    """Test boundary value configuration"""
    # Test minimum valid values
    config_min = ControllerConfig(
        instance_assemble_timeout=1,
        instance_heartbeat_timeout=1,
        instance_expired_timeout=1,
        controller_api_port=1,
        max_link_number=1,
        send_cmd_retry_times=0
    )
    assert config_min.controller_api_port == 1
    assert config_min.max_link_number == 1
    assert config_min.send_cmd_retry_times == 0

    # Test maximum valid values
    config_max = ControllerConfig(
        controller_api_port=65535,
        max_link_number=999999,
        send_cmd_retry_times=100
    )
    assert config_max.controller_api_port == 65535
    assert config_max.max_link_number == 999999
    assert config_max.send_cmd_retry_times == 100


def test_config_partial_json_loading():
    """Test partial JSON configuration loading"""
    partial_config = {
        "controller_api_port": 9000,
        "instance_assemble_timeout": 300
        # Other fields use default values
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(partial_config, f)
        temp_path = f.name

    try:
        config = ControllerConfig.from_json(temp_path)
        assert config.controller_api_port == 9000
        assert config.instance_assemble_timeout == 300
        # Other fields should be default values
        assert config.controller_api_host == '127.0.0.1'
        assert config.max_link_number == 768
        assert config.enable_tls is False
        assert config.cert_path == 'security/controller/cert/server.crt'
        assert config.key_path == 'security/controller/keys/server.key'
    finally:
        os.unlink(temp_path)


def test_config_extra_fields_in_json():
    """Test extra fields in JSON"""
    config_with_extra = {
        "controller_api_port": 9000,
        "extra_field": "should_be_ignored",
        "another_extra": 123
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config_with_extra, f)
        temp_path = f.name

    try:
        config = ControllerConfig.from_json(temp_path)
        assert config.controller_api_port == 9000
        # Extra fields should be ignored
        assert not hasattr(config, 'extra_field')
        assert not hasattr(config, 'another_extra')
    finally:
        os.unlink(temp_path)


def test_config_reload_preserves_internal_fields():
    """Test that reloading configuration preserves internal fields"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"controller_api_port": 8000}, f)
        temp_path = f.name

    try:
        config = ControllerConfig.from_json(temp_path)
        original_path = config.config_path
        original_modified = config.last_modified

        # Use a shorter wait time and manually touch the file to ensure different modification time
        time.sleep(0.01)

        # Modify configuration
        with open(temp_path, 'w') as f:
            json.dump({"controller_api_port": 9000}, f)

        # Manually update file modification time to ensure it's different
        current_time = time.time()
        os.utime(temp_path, (current_time, current_time))

        config.reload()

        # Internal fields should be updated
        assert config.config_path == original_path
        assert config.last_modified >= original_modified
    finally:
        os.unlink(temp_path)


def test_config_validation_with_none_values():
    """Test handling None values in configuration validation"""
    # These tests ensure validation logic correctly handles various edge cases
    with pytest.raises(TypeError):
        ControllerConfig(instance_assemble_timeout=None)


def test_config_unicode_handling():
    """Test Unicode character handling"""
    unicode_config = {
        "controller_api_host": "Test Host",
        "controller_api_port": 8000
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(unicode_config, f, ensure_ascii=False)
        temp_path = f.name

    try:
        config = ControllerConfig.from_json(temp_path)
        assert config.controller_api_host == "Test Host"
    finally:
        os.unlink(temp_path)


def test_config_path_override_operations(temp_dir, reset_config_path):
    """Test various config path override operations"""
    test_path = os.path.join(temp_dir, "config.json")
    override_path = os.path.join(temp_dir, "override.json")

    # Test setting path override
    set_config_path(test_path)
    assert get_config_path() == test_path

    # Test find_config_file with override
    set_config_path(override_path)
    assert find_config_file() == override_path

    # Test find_config_file without override
    import motor.config.controller as config_module
    config_module.CONFIG_PATH_OVERRIDE = None
    result = find_config_file()
    assert result is not None
    assert "controller_config.json" in result

    # Test multiple set operations
    set_config_path(test_path)
    assert get_config_path() == test_path

    set_config_path(override_path)
    assert get_config_path() == override_path

    # Test logging
    with patch('motor.config.controller.logger') as mock_logger:
        set_config_path(test_path)
        mock_logger.info.assert_called_with(f"Configuration path override set to: {test_path}")

    # Test priority over auto-detection
    set_config_path(override_path)
    assert find_config_file() == override_path


def test_config_path_override_persistence(temp_dir, reset_config_path):
    """Test that config path override persists across calls"""
    test_path = os.path.join(temp_dir, "persistent.json")
    set_config_path(test_path)

    # Multiple calls should return the same override
    assert get_config_path() == test_path
    assert find_config_file() == test_path
    assert get_config_path() == test_path


def test_find_config_file_fallback_behavior(reset_config_path):
    """Test find_config_file fallback behavior without override"""
    result = find_config_file()

    # Should return a valid path (even if file doesn't exist)
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0


def test_tls_config_default_values():
    """Test TLS configuration default values"""
    config = ControllerConfig()
    
    assert config.enable_tls is False
    assert config.cert_path == 'security/controller/cert/server.crt'
    assert config.key_path == 'security/controller/keys/server.key'


def test_tls_config_from_json(temp_json_file):
    """Test loading TLS configuration from JSON file"""
    test_config = {
        "enable_tls": True,
        "cert_path": "/custom/path/cert.pem",
        "key_path": "/custom/path/key.pem",
        "controller_api_port": 8443
    }

    with open(temp_json_file, 'w') as f:
        json.dump(test_config, f)

    config = ControllerConfig.from_json(temp_json_file)
    assert config.enable_tls is True
    assert config.cert_path == "/custom/path/cert.pem"
    assert config.key_path == "/custom/path/key.pem"
    assert config.controller_api_port == 8443


def test_tls_config_partial_loading(temp_json_file):
    """Test partial TLS configuration loading (only enable_tls)"""
    test_config = {
        "enable_tls": True
        # cert_path and key_path should use default values
    }

    with open(temp_json_file, 'w') as f:
        json.dump(test_config, f)

    config = ControllerConfig.from_json(temp_json_file)
    assert config.enable_tls is True
    assert config.cert_path == 'security/controller/cert/server.crt'
    assert config.key_path == 'security/controller/keys/server.key'


def test_tls_config_to_dict():
    """Test TLS configuration in to_dict output"""
    config = ControllerConfig(
        enable_tls=True,
        cert_path="/custom/cert.pem",
        key_path="/custom/key.pem"
    )

    config_dict = config.to_dict()
    
    assert config_dict["enable_tls"] is True
    assert config_dict["cert_path"] == "/custom/cert.pem"
    assert config_dict["key_path"] == "/custom/key.pem"


def test_tls_config_save_to_json(temp_json_file):
    """Test saving TLS configuration to JSON file"""
    config = ControllerConfig(
        enable_tls=True,
        cert_path="/custom/cert.pem",
        key_path="/custom/key.pem"
    )

    result = config.save_to_json(temp_json_file)
    assert result is True

    # Verify file content
    with open(temp_json_file, 'r') as f:
        saved_config = json.load(f)
    
    assert saved_config["enable_tls"] is True
    assert saved_config["cert_path"] == "/custom/cert.pem"
    assert saved_config["key_path"] == "/custom/key.pem"


def test_tls_config_reload(temp_json_file):
    """Test reloading TLS configuration"""
    initial_config = {
        "enable_tls": False,
        "cert_path": "/initial/cert.pem",
        "key_path": "/initial/key.pem"
    }
    modified_config = {
        "enable_tls": True,
        "cert_path": "/modified/cert.pem",
        "key_path": "/modified/key.pem"
    }

    with open(temp_json_file, 'w') as f:
        json.dump(initial_config, f)

    config = ControllerConfig.from_json(temp_json_file)
    assert config.enable_tls is False
    assert config.cert_path == "/initial/cert.pem"
    assert config.key_path == "/initial/key.pem"

    # Wait a short time to ensure different file modification time
    time.sleep(0.1)

    # Modify file
    with open(temp_json_file, 'w') as f:
        json.dump(modified_config, f)

    # Reload configuration
    assert config.reload() is True
    assert config.enable_tls is True
    assert config.cert_path == "/modified/cert.pem"
    assert config.key_path == "/modified/key.pem"


def test_tls_config_boolean_values(temp_json_file):
    """Test TLS enable_tls with different boolean representations"""
    # Test with true (lowercase)
    test_config = {"enable_tls": True}
    with open(temp_json_file, 'w') as f:
        json.dump(test_config, f)
    config = ControllerConfig.from_json(temp_json_file)
    assert config.enable_tls is True

    # Test with false (lowercase)
    test_config = {"enable_tls": False}
    with open(temp_json_file, 'w') as f:
        json.dump(test_config, f)
    config = ControllerConfig.from_json(temp_json_file)
    assert config.enable_tls is False


def test_tls_config_path_strings():
    """Test TLS certificate and key path configurations with various string values"""
    # Test with absolute paths
    config = ControllerConfig(
        cert_path="/absolute/path/to/cert.crt",
        key_path="/absolute/path/to/key.key"
    )
    assert config.cert_path == "/absolute/path/to/cert.crt"
    assert config.key_path == "/absolute/path/to/key.key"

    # Test with relative paths
    config = ControllerConfig(
        cert_path="relative/cert.crt",
        key_path="relative/key.key"
    )
    assert config.cert_path == "relative/cert.crt"
    assert config.key_path == "relative/key.key"

    # Test with empty strings (should be allowed, validation happens at usage)
    config = ControllerConfig(
        cert_path="",
        key_path=""
    )
    assert config.cert_path == ""
    assert config.key_path == ""
