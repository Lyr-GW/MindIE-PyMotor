#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.

import sys
from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse
import httpx

from motor.coordinator.models.request import RequestInfo, ReqState
from motor.coordinator.core.request_manager import RequestManager
from motor.config.coordinator import DeployMode, CoordinatorConfig
from motor.coordinator.router.base_router import BaseRouter
from motor.coordinator.router.pd_hybrid_router import PDHybridRouter
from motor.coordinator.router.separate_pd_router import SeparatePDRouter
from motor.coordinator.router.separate_cdp_router import SeparateCDPRouter
from motor.utils.logger import get_logger

logger = get_logger(__name__)

router_map: dict[DeployMode, type['BaseRouter']] = {
    DeployMode.CDP_SEPARATE: SeparateCDPRouter,
    DeployMode.PD_SEPARATE: SeparatePDRouter,
    DeployMode.SINGLE_NODE: PDHybridRouter,
}


async def handle_request(raw_request: Request) -> StreamingResponse:
    """Handle incoming requests and route them to appropriate router implementation
    
    Args:
        raw_request: The incoming FastAPI request object
        
    Returns:
        StreamingResponse: The response stream from the selected router implementation
        
    Raises:
        HTTPException: If request body is empty or request fail
    """
    request_body = await raw_request.body()
    if not request_body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty request body")
    
    request_json = await raw_request.json()
    if not request_json:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty request json")

    # Add request
    req_len = len(request_body)
    req_id = RequestManager().generate_request_id()
    req_info = RequestInfo(req_id=req_id, req_data=request_json.copy(), api="v1/chat/completions", 
                           req_len=req_len, state=ReqState.ARRIVE)

    deploy_mode_str = CoordinatorConfig().scheduler_config.get("deploy_mode")
    deploy_mode = DeployMode.from_string(deploy_mode_str)
    router_impl_class = router_map.get(deploy_mode)
    if not router_impl_class:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Unknown deploy mode: {deploy_mode_str}"
        )
        
    router_impl = router_impl_class(req_info)
    
    try:
        return await router_impl.handle_request()
    except Exception as e:
        import traceback
        exc_info = sys.exc_info()
        logger.error("Error occurred in proxy server"
              f" - {req_info.api} endpoint")
        logger.error(e)
        logger.error("".join(traceback.format_exception(*exc_info)))
        raise


async def handle_metaserver_request(raw_request: Request) -> httpx.Response:
    """Only for CDP mode
    Handle incoming requests from D Instance and route them to P instance
    
    Args:
        raw_request: The incoming FastAPI request object from D Instance
        
    Returns:
        httpx.Response: The non stream response from the selected P instance
        
    Raises:
        HTTPException: If request body is empty or request fail
    """
    request_body = await raw_request.body()
    if not request_body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty request body")
    
    request_json = await raw_request.json()
    if not request_json:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty request json")
    
    # Add request
    req_len = len(request_body)
    req_id = RequestManager().generate_request_id()
    req_info = RequestInfo(req_id=req_id, req_data=request_json.copy(), api="v1/chat/completions", 
                           req_len=req_len, state=ReqState.ARRIVE)
    
    deploy_mode_str = CoordinatorConfig().scheduler_config.get("deploy_mode")
    deploy_mode = DeployMode.from_string(deploy_mode_str)
    if not deploy_mode or deploy_mode != DeployMode.CDP_SEPARATE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Unsupport deploy mode: {deploy_mode_str}"
        )
    
    try:
        return await SeparateCDPRouter(req_info=req_info).handle_metaserver_request()
    except Exception as e:
        import traceback
        exc_info = sys.exc_info()
        logger.error("Error occurred in meta server"
              f" - {req_info.api} endpoint")
        logger.error(e)
        logger.error("".join(traceback.format_exception(*exc_info)))
        raise