from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from motor.coordinator.main import on_become_standby, on_become_master, main


@pytest.fixture
def setup_modules(monkeypatch):
    modules = {}
    monkeypatch.setattr('motor.coordinator.main.modules', modules)
    return modules


@patch('motor.coordinator.main.logger')
def test_on_become_standby_normal(mock_logger, setup_modules):
    """
    Test the situation where the stop method is correctly called under normal circumstances
    """
    # Create a mock module with a 'stop' method
    mock_module = MagicMock()
    mock_module.stop = MagicMock()

    setup_modules['MetricsListener'] = mock_module

    on_become_standby()

    mock_module.stop.assert_called_once()
    mock_logger.info.assert_any_call("Stopping MetricsListener...")
    mock_logger.info.assert_any_call("Becoming standby, stopping all modules...")
    mock_logger.info.assert_called_with("All modules stopped.")


@patch('motor.coordinator.main.logger')
def test_on_become_standby_exception(mock_logger, setup_modules):
    """
    Test whether errors can be caught and logged when the stop method throws an exception.
    """
    # Create a mock module that will throw an exception when 'stop'
    mock_module = MagicMock()
    mock_module.stop.side_effect = Exception("Stop failed")

    setup_modules['MetricsListener'] = mock_module

    on_become_standby()

    mock_module.stop.assert_called_once()
    mock_logger.error.assert_called_with("Error stopping MetricsListener: Stop failed")
    mock_logger.info.assert_called_with("All modules stopped.")


@patch('motor.coordinator.main.logger')
def test_on_become_standby_no_stop_method(mock_logger, setup_modules):
    """
    Testing a module without a stop method will not cause an error.
    """
    # Create a mock module without a 'stop' method
    mock_module = MagicMock()
    del mock_module.stop

    setup_modules['MetricsListener'] = mock_module

    on_become_standby()

    assert not hasattr(mock_module, 'stop') or mock_module.stop.call_count == 0
    mock_logger.info.assert_called_with("All modules stopped.")


@patch('motor.coordinator.main.logger')
def test_on_become_master_normal(mock_logger, setup_modules):
    """
    Test the situation where the stop method is correctly called under normal circumstances
    """
    # Create a mock module with a 'start' method
    mock_module = MagicMock()
    mock_module.start = MagicMock()

    setup_modules['MetricsListener'] = mock_module

    on_become_master()

    mock_module.start.assert_called_once()
    mock_logger.info.assert_any_call("Becoming master, starting all modules...")
    mock_logger.info.assert_any_call("Starting MetricsListener...")

    mock_logger.info.assert_called_with("All modules started.")


@patch('motor.coordinator.main.logger')
def test_on_become_master_exception(mock_logger, setup_modules):
    """
    Test whether errors can be caught and logged when the start method throws an exception.
    """
    # Create a mock module that will throw an exception when 'stop'
    mock_module = MagicMock()
    mock_module.start.side_effect = Exception("Start failed")

    setup_modules['MetricsListener'] = mock_module

    on_become_master()

    mock_module.start.assert_called_once()
    mock_logger.error.assert_called_with("Error starting MetricsListener: Start failed")
    mock_logger.info.assert_called_with("All modules started.")


@patch('motor.coordinator.main.logger')
def test_on_become_master_instance(mock_logger, setup_modules):
    """
    Test the situation where the stop method is correctly called under normal circumstances
    """

    on_become_master()

    # mock_module.start.assert_called_once()
    mock_logger.info.assert_any_call("Becoming master, starting all modules...")
    mock_logger.info.assert_any_call("Initializing MetricsListener...")
    mock_logger.info.assert_any_call("Starting MetricsListener...")

    mock_logger.info.assert_called_with("All modules started.")

    assert "CoordinatorConfig" in setup_modules
    assert "InstanceManager" in setup_modules
    assert "RequestManager" in setup_modules
    assert "MetricsListener" in setup_modules
    assert "InstanceHealthChecker" in setup_modules
    assert "CoordinatorServer" in setup_modules


@pytest.mark.asyncio
async def test_main_standalone_mode_success():
    """
    测试场景：在非主备模式下正常启动服务
    """
    with patch('motor.coordinator.main.modules', {
        "CoordinatorConfig": MagicMock(config_file_path="/fake/path/config.yaml",
                                       standby_config=MagicMock(enable_master_standby=False)),
        "CoordinatorServer": AsyncMock(run=AsyncMock())
    }), \
            patch('motor.coordinator.main.os.path.exists', return_value=True), \
            patch('motor.coordinator.main.ConfigWatcher') as mock_config_watcher_class, \
            patch('motor.coordinator.main.initialize_components'), \
            patch('motor.coordinator.main.start_all_modules'), \
            patch('motor.coordinator.main.stop_all_modules'), \
            patch('motor.coordinator.main.logger') as mock_logger:
        mock_config_watcher_instance = MagicMock()
        mock_config_watcher_class.return_value = mock_config_watcher_instance

        await main()

        # 验证关键步骤被执行
        mock_logger.info.assert_any_call("Starting Motor Coordinator HTTP server...")
        mock_logger.info.assert_any_call("Master/standby feature is disabled, running in standalone mode")
        mock_config_watcher_instance.start.assert_called_once()
        mock_config_watcher_instance.stop.assert_called_once()


@pytest.mark.asyncio
async def test_main_master_standby_enabled():
    """
    测试场景：启用主备模式时的行为
    """
    with patch('motor.coordinator.main.modules', {
        "CoordinatorConfig": MagicMock(config_file_path="/fake/path/config.yaml",
                                       standby_config=MagicMock(enable_master_standby=True)),
        "CoordinatorServer": AsyncMock(run=AsyncMock())
    }), \
            patch('motor.coordinator.main.os.path.exists', return_value=True), \
            patch('motor.coordinator.main.ConfigWatcher'), \
            patch('motor.coordinator.main.StandbyManager') as mock_standby_manager_class, \
            patch('motor.coordinator.main.initialize_components'), \
            patch('motor.coordinator.main.on_become_master'), \
            patch('motor.coordinator.main.on_become_standby'), \
            patch('motor.coordinator.main.stop_all_modules'), \
            patch('motor.coordinator.main.logger') as mock_logger:
        mock_standby_manager_instance = MagicMock()
        mock_standby_manager_class.return_value = mock_standby_manager_instance

        await main()

        mock_logger.info.assert_any_call("Master/standby feature is enabled, running in master-standby mode")
        mock_standby_manager_instance.start.assert_called_once()
