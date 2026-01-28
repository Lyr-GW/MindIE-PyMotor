#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
# MindIE is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#         http://license.coscl.org.cn/MulanPSL2
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

from fastapi.responses import StreamingResponse

from motor.coordinator.models.request import ReqState
from motor.coordinator.router.base_router import BaseRouter
from motor.coordinator.models.request import ScheduledResource
from motor.common.resources.instance import PDRole


class PDHybridRouter(BaseRouter):
    """Handle request with a single PD hybrid instance"""
    
    async def handle_request(self) -> StreamingResponse:
        """Handle request with PD hybrid instance"""
        resource: ScheduledResource = None
        try:
            # Schedule PD instance
            resource = await self.prepare_resource(PDRole.ROLE_U)
            
            # Forward request to PD hybrid instance
            return StreamingResponse(self.__forward_pd_hybrid_request(resource),
                                     media_type="application/json")
        except Exception as e:
            self.logger.error("Error occurred while forwarding PD hybrid request: %s", e)
            raise e
        finally:
            self.release_all(resource)
    
    async def __forward_pd_hybrid_request(self, resource: ScheduledResource):
        """Forward request to PD hybrid instance"""
        try:
            # For PD hybrid instances, we forward the original request directly
            req_data = self.req_info.req_data.copy()
            
            self.logger.info(f"PD hybrid request data: {req_data}")
            
            release_kv = False
            async for chunk in self.forward_stream_request(req_data=req_data, 
                                                           resource=resource,
                                                           timeout=self.config.exception_config.first_token_timeout
                                                           ):
                if not release_kv and chunk:
                    release_kv = True
                    self.release_kv(resource)
                yield chunk
        except Exception as e:
            self.logger.error("Error occurred while forwarding PD hybrid request: %s", e)
            raise e
        
        # Release tokens after streaming is complete
        self.req_info.update_state(ReqState.DECODE_END)
        self.release_tokens(resource)
        self.logger.info(f"Completed streaming for PD hybrid request {self.req_info.req_id}")