#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.

from fastapi.responses import StreamingResponse

from motor.coordinator.models.request import ReqState
from motor.coordinator.router.base_router import BaseRouter
from motor.coordinator.models.request import ScheduledResource
from motor.resources.instance import PDRole
from motor.utils.logger import get_logger

logger = get_logger(__name__)


class PDHybridRouter(BaseRouter):
    """Handle request with a single PD hybrid instance"""
    
    async def handle_request(self) -> StreamingResponse:
        """Handle request with PD hybrid instance"""
        resource: ScheduledResource = None
        try:
            # Schedule PD instance
            resource = self.prepare_resource(PDRole.ROLE_U)
            
            # Forward request to PD hybrid instance
            return StreamingResponse(self.__forward_pd_hybrid_request(resource),
                                     media_type="application/json")
        except Exception as e:
            logger.error("Error occurred while forwarding PD hybrid request: %s", e)
            raise e
        finally:
            self.release_all(resource)
    
    async def __forward_pd_hybrid_request(self, resource: ScheduledResource):
        """Forward request to PD hybrid instance"""
        try:
            # For PD hybrid instances, we forward the original request directly
            req_data = self.req_info.req_data.copy()
            
            logger.info(f"PD hybrid request data: {req_data}")
            
            release_kv = False
            async for chunk in self.forward_stream_request(req_data=req_data, resource=resource):
                if not release_kv and chunk:
                    release_kv = True
                    self.release_kv(resource)
                yield chunk
        except Exception as e:
            logger.error("Error occurred while forwarding PD hybrid request: %s", e)
            raise e
        
        # Release tokens after streaming is complete
        self.req_info.update_state(ReqState.DECODE_END)
        self.release_tokens(resource)
        logger.info(f"Completed streaming for PD hybrid request {self.req_info.req_id}")