import pytest
from pytest import MonkeyPatch
import json
import os
from unittest.mock import patch, mock_open
from motor.config.coordinator import CoordinatorConfig
from motor.utils.singleton import ThreadSafeSingleton
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Complete configuration template
COMPLETE_CONFIG = {
    "http_config": {
        "predict_ip": "127.0.0.1",
        "predict_port": "8080",
        "manage_ip": "127.0.0.1",
        "manage_port": "8081",
        "alarm_port": "8082",
        "server_thread_num": 4,
        "client_thread_num": 2,
        "http_timeout_seconds": 10,
        "keep_alive_seconds": 180,
        "server_name": "test_server",
        "user_agent": "test_agent",
        "allow_all_zero_ip_listening": True
    },
    "metrics_config": {
        "enable": True,
        "trigger_size": 100
    },
    "prometheus_metrics_config": {
        "reuse_time": 3
    },
    "exception_config": {
        "max_retry": 5,
        "retry_delay": 0.2,
        "schedule_timeout": 60,
        "first_token_timeout": 60,
        "infer_timeout": 300,
        "tokenizer_timeout": 300
    },
    "request_limit": {
        "single_node_max_requests": 1000,
        "max_requests": 10000,
        "body_limit": 10485760
    },
    "tls_config": {
        "controller_server_tls_enable": True,
        "controller_server_tls_items": {
            "ca_cert": "ca.pem",
            "tls_cert": "server.pem",
            "tls_key": "server.key",
            "tls_passwd": "password",
            "tls_crl": "crl.pem",
            "kmcKsfMaster": "master_key",
            "kmcKsfStandby": "standby_key"
        }
    },
    "digs_scheduler_config": {
        "deploy_mode": "single_node",
        "scheduler_type": "digs_scheduler",
        "algorithm_type": "load_balance"
    },
    "string_token_rate": 4.2,
    "health_check_config": {
        "dummy_request_interval": 5.0,
        "max_consecutive_failures": 3,
        "dummy_request_timeout": 10.0,
        "controller_base_url": "http://localhost:10000"
    }
}

@pytest.fixture
def reset_singleton():
    """Reset singleton instance to ensure test isolation"""

    # Remove the CoordinatorConfig class from the _instances dictionary
    if CoordinatorConfig in ThreadSafeSingleton._instances:
        del ThreadSafeSingleton._instances[CoordinatorConfig]
    yield
    # Clean up after the test
    if CoordinatorConfig in ThreadSafeSingleton._instances:
        del ThreadSafeSingleton._instances[CoordinatorConfig]

def create_coordinator_with_config(config_data, env_vars=None):
    """Create CoordinatorConfig instance with mock configuration"""
    # Set up environment variables first if provided
    if env_vars:
        for key, value in env_vars.items():
            os.environ[key] = str(value)
    
    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.path.exists', return_value=True):
            return CoordinatorConfig()

def create_coordinator_with_file_not_found():
    """Create CoordinatorConfig instance when file doesn't exist"""
    with patch('os.path.exists', return_value=False):
        return CoordinatorConfig()

def create_coordinator_with_invalid_config(config_data):
    """Create CoordinatorConfig instance with invalid configuration, expecting exception"""
    with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
        with patch('os.path.exists', return_value=True):
            try:
                coordinator = CoordinatorConfig()
                return coordinator, None
            except Exception as e:
                return None, e

class TestCoordinatorConfig:
    
    @pytest.mark.usefixtures("reset_singleton")
    def test_init_success(self):
        """Test successful initialization"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.http_config.predict_ip == "127.0.0.1"
        assert coordinator.http_config.predict_port == "8080"
        assert coordinator.metrics_config.enable is True
        assert coordinator.metrics_config.trigger_size == 100
        assert coordinator.prometheus_metrics_config.reuse_time == 3
        assert coordinator.exception_config.max_retry == 5
        assert coordinator.req_limit.single_node_max_reqs == 1000
        assert coordinator.req_limit.max_reqs == 10000
        assert coordinator.req_limit.body_limit == 10485760
        assert coordinator.controller_server_tls.tls_enable is True
        assert coordinator.controller_server_tls.items == config["tls_config"]["controller_server_tls_items"]
        assert coordinator.scheduler_config == config["digs_scheduler_config"]
        assert coordinator.str_token_rate == 4.2
        assert coordinator.health_check_config.dummy_request_interval == 5.0

    @pytest.mark.usefixtures("reset_singleton") 
    def test_init_file_not_found(self):
        """Test configuration file not found scenario"""
        # This should raise FileNotFoundError during initialization
        with pytest.raises(FileNotFoundError) as exc_info:
            create_coordinator_with_file_not_found()
        assert "Configuration file not found" in str(exc_info.value)

    @pytest.mark.usefixtures("reset_singleton")
    def test_http_config(self):
        """Test HTTP configuration"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.http_config.predict_ip == "127.0.0.1"
        assert coordinator.http_config.predict_port == "8080"
        assert coordinator.http_config.manage_ip == "127.0.0.1"
        assert coordinator.http_config.manage_port == "8081"
        assert coordinator.http_config.alarm_port == "8082"
        assert coordinator.http_config.server_thread_num == 4
        assert coordinator.http_config.client_thread_num == 2
        assert coordinator.http_config.http_timeout_seconds == 10
        assert coordinator.http_config.keep_alive_seconds == 180
        assert coordinator.http_config.server_name == "test_server"
        assert coordinator.http_config.user_agent == "test_agent"
        assert coordinator.http_config.allow_all_zero_ip_listening is True

    @pytest.mark.usefixtures("reset_singleton")
    def test_metrics_config(self):
        """Test Metrics configuration"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.metrics_config.enable is True
        assert coordinator.metrics_config.trigger_size == 100
        assert coordinator.prometheus_metrics_config.reuse_time == 3

    @pytest.mark.usefixtures("reset_singleton")
    def test_exception_config(self):
        """Test exception configuration"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.exception_config.max_retry == 5
        assert coordinator.exception_config.schedule_timeout == 60
        assert coordinator.exception_config.first_token_timeout == 60
        assert coordinator.exception_config.infer_timeout == 300
        assert coordinator.exception_config.tokenizer_timeout == 300

    @pytest.mark.usefixtures("reset_singleton")
    def test_request_limit(self):
        """Test request limiting configuration"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.req_limit.single_node_max_reqs == 1000
        assert coordinator.req_limit.max_reqs == 10000
        assert coordinator.req_limit.body_limit == 10485760

    @pytest.mark.usefixtures("reset_singleton")
    def test_tls_config(self):
        """Test TLS configuration"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.controller_server_tls.tls_enable is True
        assert coordinator.controller_server_tls.items == config["tls_config"]["controller_server_tls_items"]

    @pytest.mark.usefixtures("reset_singleton")
    def test_scheduler_config(self):
        """Test Scheduler configuration"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.scheduler_config == config["digs_scheduler_config"]

    @pytest.mark.usefixtures("reset_singleton")
    def test_str_token_rate(self):
        """Test string token rate configuration"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.str_token_rate == 4.2

    @pytest.mark.usefixtures("reset_singleton")
    def test_health_check_config(self):
        """Test health check configuration"""
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config)
        
        assert coordinator.health_check_config.dummy_request_interval == 5.0
        assert coordinator.health_check_config.max_consecutive_failures == 3
        assert coordinator.health_check_config.dummy_request_timeout == 10.0

    @pytest.mark.usefixtures("reset_singleton")
    def test_env_vars_request_limit(self, monkeypatch: MonkeyPatch):
        """Test environment variable request limits"""
        # Set environment variables before creating coordinator
        env_vars = {
            "MINDIE_MS_COORDINATOR_CONFIG_SINGLE_NODE_MAX_REQ": "2000",
            "MINDIE_MS_COORDINATOR_CONFIG_MAX_REQ": "20000"
        }
        
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config, env_vars)
        
        assert coordinator.req_limit.single_node_max_reqs == 2000
        assert coordinator.req_limit.max_reqs == 20000

    @pytest.mark.usefixtures("reset_singleton")
    def test_invalid_env_vars_request_limit(self, monkeypatch: MonkeyPatch):
        """Test invalid environment variable request limits"""
        # Set invalid environment variables
        env_vars = {
            "MINDIE_MS_COORDINATOR_CONFIG_SINGLE_NODE_MAX_REQ": "invalid",
            "MINDIE_MS_COORDINATOR_CONFIG_MAX_REQ": "invalid"
        }
        
        config = COMPLETE_CONFIG.copy()
        coordinator = create_coordinator_with_config(config, env_vars)
        
        # Should use default values from config file since environment variables are invalid
        assert coordinator.req_limit.single_node_max_reqs == 1000
        assert coordinator.req_limit.max_reqs == 10000

    @pytest.mark.usefixtures("reset_singleton")
    def test_invalid_deploy_mode(self):
        """Test invalid deployment mode"""
        config = COMPLETE_CONFIG.copy()
        config["digs_scheduler_config"]["deploy_mode"] = "invalid_mode"
        
        coordinator, exception = create_coordinator_with_invalid_config(config)
        assert coordinator is None
        assert exception is not None

    @pytest.mark.usefixtures("reset_singleton")
    def test_invalid_scheduler_type(self):
        """Test invalid scheduler type"""
        config = COMPLETE_CONFIG.copy()
        config["digs_scheduler_config"]["scheduler_type"] = "invalid_scheduler"
        
        coordinator, exception = create_coordinator_with_invalid_config(config)
        assert coordinator is None
        assert exception is not None

    @pytest.mark.usefixtures("reset_singleton")
    def test_invalid_algorithm_type(self):
        """Test invalid algorithm type"""
        config = COMPLETE_CONFIG.copy()
        config["digs_scheduler_config"]["algorithm_type"] = "invalid_algorithm"
        
        coordinator, exception = create_coordinator_with_invalid_config(config)
        assert coordinator is None
        assert exception is not None

    @pytest.mark.usefixtures("reset_singleton")
    def test_missing_required_fields(self):
        """Test missing required fields"""
        config = COMPLETE_CONFIG.copy()
        config["digs_scheduler_config"] = {
            "deploy_mode": "single_node",
            "scheduler_type": "digs_scheduler"
            # Missing algorithm_type
        }
        
        coordinator, exception = create_coordinator_with_invalid_config(config)
        assert coordinator is None
        assert exception is not None

    @pytest.mark.usefixtures("reset_singleton")
    def test_invalid_str_token_rate(self):
        """Test invalid string token rate"""
        config = COMPLETE_CONFIG.copy()
        config["string_token_rate"] = "invalid"  # Should be a number
        
        coordinator, exception = create_coordinator_with_invalid_config(config)
        assert coordinator is None
        assert exception is not None

    @pytest.mark.usefixtures("reset_singleton")
    def test_out_of_range_str_token_rate(self):
        """Test out-of-range string token rate"""
        config = COMPLETE_CONFIG.copy()
        config["string_token_rate"] = 0.5  # Below minimum value
        
        coordinator, exception = create_coordinator_with_invalid_config(config)
        assert coordinator is None
        assert exception is not None

    @pytest.mark.usefixtures("reset_singleton")
    def test_default_values(self):
        """Test default values"""
        # Use minimal configuration without http_config to test defaults
        minimal_config = {
            "digs_scheduler_config": {
                "deploy_mode": "single_node", 
                "scheduler_type": "digs_scheduler",
                "algorithm_type": "load_balance"
            }
        }
        
        coordinator = create_coordinator_with_config(minimal_config)
        
        # Check default values - these should come from HttpConfig constructor defaults
        # since minimal_config doesn't have http_config section
        assert coordinator.http_config.server_thread_num == 1  # Default from HttpConfig
        assert coordinator.metrics_config.enable is False  # Default from MetricsConfig
        assert coordinator.exception_config.max_retry == 5  # Default from ExceptionConfig
        assert coordinator.str_token_rate == 4.2  # From minimal_config