import pytest
from unittest.mock import patch
from fastapi import HTTPException

from motor.controller.api_server import probe_api


def mock_get_controller_status(status_data):
    """Helper function to mock get_controller_status"""
    return status_data


@pytest.mark.asyncio
async def test_startup_endpoint():
    """Test startup endpoint returns correct message"""
    # Test the function directly instead of through HTTP
    result = await probe_api.startup()
    assert result == {"message": "Controller startup"}


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_standalone_healthy(mock_get_status):
    """Test readiness in standalone mode with healthy modules"""
    mock_get_status.return_value = {
        "deploy_mode": "standalone",
        "overall_healthy": True
    }

    # Test the function directly - should not raise exception for healthy case
    result = await probe_api.readiness()
    # readiness() should return success message for successful case (200 status)
    assert result == {"message": "Controller is ready"}


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_standalone_unhealthy(mock_get_status):
    """Test readiness in standalone mode with unhealthy modules"""
    mock_get_status.return_value = {
        "deploy_mode": "standalone",
        "overall_healthy": False,
    }

    # Test the function directly - should raise HTTPException for unhealthy case
    with pytest.raises(HTTPException) as exc_info:
        await probe_api.readiness()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["message"] == "Controller is not ready"
    assert exc_info.value.detail["reason"] == "Overall not healthy"


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_master_standby_master_healthy(mock_get_status):
    """Test readiness in master_standby mode as master with healthy modules"""
    mock_get_status.return_value = {
        "deploy_mode": "master_standby",
        "role": "master",
        "overall_healthy": True
    }

    # Test the function directly - should not raise exception for healthy master case
    result = await probe_api.readiness()
    assert result == {"message": "Controller is ready"}


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_master_standby_master_unhealthy(mock_get_status):
    """Test readiness in master_standby mode as master with unhealthy modules"""
    mock_get_status.return_value = {
        "deploy_mode": "master_standby",
        "overall_healthy": False
    }

    # Test the function directly - should raise HTTPException for unhealthy case
    with pytest.raises(HTTPException) as exc_info:
        await probe_api.readiness()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["message"] == "Controller is not ready"
    assert exc_info.value.detail["reason"] == "Overall not healthy"


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_master_standby_standby_healthy(mock_get_status):
    """Test readiness in master_standby mode as standby with healthy modules"""
    mock_get_status.return_value = {
        "deploy_mode": "master_standby",
        "overall_healthy": True
    }

    # Test the function directly - should raise HTTPException for healthy standby case
    with pytest.raises(HTTPException) as exc_info:
        await probe_api.readiness()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["message"] == "Controller is not ready"
    assert "Not master" in exc_info.value.detail["reason"]


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_master_standby_standby_unhealthy(mock_get_status):
    """Test readiness in master_standby mode as standby with unhealthy modules"""
    mock_get_status.return_value = {
        "deploy_mode": "master_standby",
        "overall_healthy": False
    }

    # Test the function directly - should raise HTTPException for unhealthy case
    with pytest.raises(HTTPException) as exc_info:
        await probe_api.readiness()

    # When unhealthy, it should return unhealthy reason first
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["reason"] == "Overall not healthy"


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_master_standby_invalid_role(mock_get_status):
    """Test readiness in master_standby mode with invalid role"""
    mock_get_status.return_value = {
        "deploy_mode": "master_standby",
        "overall_healthy": True
    }

    # Test the function directly - should raise HTTPException for invalid role case
    with pytest.raises(HTTPException) as exc_info:
        await probe_api.readiness()

    assert exc_info.value.status_code == 503
    assert "Not master" in exc_info.value.detail["reason"]


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_liveness_healthy(mock_get_status):
    """Test liveness when controller is healthy"""
    mock_get_status.return_value = {
        "overall_healthy": True,
        "deploy_mode": "standalone",
    }

    # Test the function directly - should return result for healthy case
    result = await probe_api.liveness()
    assert result == {"message": "Controller is alive"}


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_liveness_unhealthy(mock_get_status):
    """Test liveness when controller is unhealthy"""
    mock_get_status.return_value = {
        "overall_healthy": False,
        "deploy_mode": "standalone",
    }

    # Test the function directly - should raise HTTPException for unhealthy case
    with pytest.raises(HTTPException) as exc_info:
        await probe_api.liveness()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["message"] == "Controller is not alive"
    assert exc_info.value.detail["reason"] == "Overall not healthy"


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_liveness_standby_mode(mock_get_status):
    """Test liveness in standby mode (should still be alive)"""
    mock_get_status.return_value = {
        "overall_healthy": True,
        "deploy_mode": "master_standby",
    }

    # Test the function directly - should return result for healthy standby case
    result = await probe_api.liveness()
    assert result == {"message": "Controller is alive"}


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_liveness_standby_unhealthy(mock_get_status):
    """Test liveness in standby mode when unhealthy"""
    mock_get_status.return_value = {
        "overall_healthy": False,
        "deploy_mode": "master_standby",
    }

    # Test the function directly - should raise HTTPException for unhealthy case
    with pytest.raises(HTTPException) as exc_info:
        await probe_api.liveness()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["message"] == "Controller is not alive"
    assert exc_info.value.detail["reason"] == "Overall not healthy"


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_missing_overall_healthy(mock_get_status):
    """Test readiness when overall_healthy key is missing"""
    mock_get_status.return_value = {
        "deploy_mode": "standalone"
        # missing overall_healthy
    }

    # Test the function directly - should not raise exception when overall_healthy is missing (treated as healthy)
    result = await probe_api.readiness()
    assert result == {"message": "Controller is ready"}


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_readiness_missing_deploy_mode(mock_get_status):
    """Test readiness when deploy_mode key is missing"""
    mock_get_status.return_value = {
        "overall_healthy": True
        # missing deploy_mode
    }

    # Test the function directly - should not raise exception when deploy_mode is missing
    result = await probe_api.readiness()
    assert result == {"message": "Controller is ready"}


@pytest.mark.asyncio
@patch('motor.controller.main.get_controller_status')
async def test_liveness_missing_overall_healthy(mock_get_status):
    """Test liveness when overall_healthy key is missing"""
    mock_get_status.return_value = {
        "deploy_mode": "standalone"
        # missing overall_healthy
    }

    # Test the function directly - should return result when overall_healthy is missing (treated as healthy)
    result = await probe_api.liveness()
    assert result == {"message": "Controller is alive"}
