import signal
import pytest
from unittest.mock import MagicMock, patch

from motor.controller.main import (
    parse_arguments, stop_all_modules, signal_handler,
    attach_observer, start_modules, main, modules
)


@pytest.fixture(autouse=True)
def cleanup_modules():
    """Clean up global modules dictionary"""
    modules.clear()
    yield
    modules.clear()


def test_parse_arguments_default():
    """Test default argument parsing"""
    with patch('sys.argv', ['main.py']):
        args = parse_arguments()
        assert args.config is None


def test_parse_arguments_with_config():
    """Test specified config file parameter"""
    config_path = "/path/to/config.json"
    with patch('sys.argv', ['main.py', '--config', config_path]):
        args = parse_arguments()
        assert args.config == config_path

    with patch('sys.argv', ['main.py', '-c', config_path]):
        args = parse_arguments()
        assert args.config == config_path


def test_stop_all_modules():
    """Test stopping all modules"""
    # Create mock modules
    mock_module1 = MagicMock()
    mock_module2 = MagicMock()
    mock_module3 = MagicMock()

    # Set up modules dictionary
    modules.update({
        "Module1": mock_module1,
        "Module2": mock_module2,
        "Module3": mock_module3
    })

    stop_all_modules()

    # Verify all modules' stop methods are called
    mock_module1.stop.assert_called_once()
    mock_module2.stop.assert_called_once()
    mock_module3.stop.assert_called_once()


def test_stop_all_modules_no_stop_method():
    """Test stopping modules without stop method"""
    # Create mock modules
    mock_module1 = MagicMock()
    mock_module2 = MagicMock()
    del mock_module2.stop  # Remove stop method

    modules.update({
        "Module1": mock_module1,
        "Module2": mock_module2
    })

    # Should not raise exception
    stop_all_modules()

    mock_module1.stop.assert_called_once()
    assert not hasattr(mock_module2, 'stop')


@patch('sys.exit')
def test_signal_handler(mock_exit):
    """Test signal handler"""
    with patch('motor.controller.main.stop_all_modules') as mock_stop:
        signal_handler(signal.SIGINT, None)

        mock_stop.assert_called_once()
        mock_exit.assert_called_once_with(0)


@patch('motor.controller.main.logger')
def test_attach_observer_success(mock_logger):
    """Test successful observer attachment"""
    # Create mock instance manager
    mock_instance_manager = MagicMock()
    mock_observer1 = MagicMock()
    mock_observer2 = MagicMock()

    modules.update({
        "InstanceManager": mock_instance_manager,
        "InstanceAssembler": mock_observer1,
        "EventPusher": mock_observer2
    })

    attach_observer()

    # Verify observers are attached
    mock_instance_manager.attach.assert_any_call(mock_observer1)
    mock_instance_manager.attach.assert_any_call(mock_observer2)
    assert mock_instance_manager.attach.call_count == 2


@patch('motor.controller.main.logger')
def test_attach_observer_no_manager(mock_logger):
    """Test case when instance manager is not available"""
    # Clear modules
    modules.clear()

    # Should not raise exception
    attach_observer()

    mock_logger.error.assert_called_once()


@patch('motor.controller.main.logger')
def test_start_modules(mock_logger):
    """Test starting modules"""
    # Create mock modules
    mock_module1 = MagicMock()
    mock_module2 = MagicMock()
    mock_module3 = MagicMock()

    modules.update({
        "Module1": mock_module1,
        "Module2": mock_module2,
        "Module3": mock_module3
    })

    start_modules()

    # Verify all modules' start methods are called
    mock_module1.start.assert_called_once()
    mock_module2.start.assert_called_once()
    mock_module3.start.assert_called_once()


def test_start_modules_no_start_method():
    """Test starting modules without start method"""
    # Create mock modules
    mock_module1 = MagicMock()
    mock_module2 = MagicMock()
    del mock_module2.start  # Remove start method

    modules.update({
        "Module1": mock_module1,
        "Module2": mock_module2
    })

    # Should not raise exception
    start_modules()

    mock_module1.start.assert_called_once()
    assert not hasattr(mock_module2, 'start')


@patch('builtins.input')
@patch('motor.controller.main.logger')
@patch('motor.controller.main.start_modules')
@patch('motor.controller.main.attach_observer')
@patch('signal.signal')
def test_main_success_flow(mock_signal, mock_attach, mock_start, mock_logger, mock_input):
    """Test main function success flow"""
    config_path = "/path/to/config.json"

    with patch('sys.argv', ['main.py', '--config', config_path]), \
         patch('motor.controller.main.ControllerConfig.from_json') as mock_from_json, \
         patch('motor.controller.main.InstanceManager') as mock_im_class, \
         patch('motor.controller.main.InstanceAssembler') as mock_ia_class, \
         patch('motor.controller.main.EventPusher') as mock_ep_class, \
         patch('motor.controller.main.ControllerAPI') as mock_api_class:

        mock_config = MagicMock()
        mock_from_json.return_value = mock_config
        mock_config.enable_fault_tolerance = False

        # Simulate user input 'stop' to exit loop
        mock_input.side_effect = ['stop']

        main()

        # Verify configuration loading
        mock_from_json.assert_called_once_with(config_path)
        mock_logger.info.assert_any_call("Using configuration file: %s", config_path)

        # Verify signal registration
        assert mock_signal.call_count == 2

        # Verify module initialization
        mock_im_class.assert_called_once_with(mock_config)
        mock_ia_class.assert_called_once_with(mock_config)
        mock_ep_class.assert_called_once_with(mock_config)
        mock_api_class.assert_called_once_with(mock_config)

        # Verify flow execution
        mock_attach.assert_called_once()
        mock_start.assert_called_once()


@patch('builtins.input')
@patch('motor.controller.main.logger')
def test_main_auto_config_load(mock_logger, mock_input):
    """Test automatic configuration loading"""
    with patch('sys.argv', ['main.py']), \
         patch('motor.controller.main.ControllerConfig') as mock_config_class, \
         patch('motor.controller.main.find_config_file', return_value="auto_config.json"), \
         patch('motor.controller.main.InstanceManager'), \
         patch('motor.controller.main.InstanceAssembler'), \
         patch('motor.controller.main.EventPusher'), \
         patch('motor.controller.main.ControllerAPI'), \
         patch('motor.controller.main.attach_observer'), \
         patch('motor.controller.main.start_modules'):

        mock_config = MagicMock()
        mock_config_class.from_json.return_value = mock_config
        mock_config.enable_fault_tolerance = False

        # Simulate user input 'stop' to exit loop
        mock_input.side_effect = ['stop']

        main()

        # Verify automatic config file detection
        mock_config_class.from_json.assert_called_once_with("auto_config.json")
        mock_logger.info.assert_any_call("Using auto-detected configuration file")


@patch('builtins.input')
@patch('motor.controller.main.logger')
def test_main_fault_tolerance_enabled(mock_logger, mock_input):
    """Test enabling fault tolerance"""
    with patch('sys.argv', ['main.py']), \
         patch('motor.controller.main.ControllerConfig.from_json') as mock_from_json, \
         patch('motor.controller.main.InstanceManager') as mock_im_class, \
         patch('motor.controller.main.InstanceAssembler') as mock_ia_class, \
         patch('motor.controller.main.EventPusher') as mock_ep_class, \
         patch('motor.controller.main.ControllerAPI') as mock_api_class, \
         patch('motor.controller.ft.fault_manager.FaultManager') as mock_fm_class, \
         patch('motor.controller.main.attach_observer'), \
         patch('motor.controller.main.start_modules'):

        mock_config = MagicMock()
        mock_from_json.return_value = mock_config
        mock_config.enable_fault_tolerance = True

        # Simulate user input 'stop' to exit loop
        mock_input.side_effect = ['stop']

        main()

        # Verify FaultManager is initialized
        mock_fm_class.assert_called_once_with(mock_config)


@patch('builtins.input')
@patch('motor.controller.main.logger')
def test_main_invalid_command(mock_logger, mock_input):
    """Test invalid command handling"""
    with patch('sys.argv', ['main.py']), \
         patch('motor.controller.main.ControllerConfig.from_json') as mock_from_json, \
         patch('motor.controller.main.ControllerConfig') as mock_config_class, \
         patch('motor.controller.main.InstanceManager'), \
         patch('motor.controller.main.InstanceAssembler'), \
         patch('motor.controller.main.EventPusher'), \
         patch('motor.controller.main.ControllerAPI'), \
         patch('motor.controller.main.attach_observer'), \
         patch('motor.controller.main.start_modules'):

        mock_config = MagicMock()
        mock_from_json.return_value = mock_config
        mock_config.enable_fault_tolerance = False

        # Input invalid command first, then 'stop' to exit
        mock_input.side_effect = ['invalid_cmd', 'stop']

        main()

        # Verify error logging
        mock_logger.error.assert_any_call("Unknown command: %s", 'invalid_cmd')


@patch('builtins.input')
@patch('motor.controller.main.logger')
def test_main_eof_handling(mock_logger, mock_input):
    """Test EOF handling (non-interactive environment)"""
    with patch('sys.argv', ['main.py']), \
         patch('motor.controller.main.ControllerConfig.from_json') as mock_from_json, \
         patch('motor.controller.main.ControllerConfig') as mock_config_class, \
         patch('motor.controller.main.InstanceManager'), \
         patch('motor.controller.main.InstanceAssembler'), \
         patch('motor.controller.main.EventPusher'), \
         patch('motor.controller.main.ControllerAPI'), \
         patch('motor.controller.main.attach_observer'), \
         patch('motor.controller.main.start_modules'), \
         patch('time.sleep') as mock_sleep:

        mock_config = MagicMock()
        mock_from_json.return_value = mock_config
        mock_config.enable_fault_tolerance = False

        # Simulate EOFError, then exit via KeyboardInterrupt
        mock_input.side_effect = EOFError

        # Set sleep counter, raise KeyboardInterrupt on second call
        call_count = 0
        def stop_after_two_calls(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt

        mock_sleep.side_effect = stop_after_two_calls

        main()

        # Verify entering non-interactive mode and sleep was called
        assert call_count >= 1
