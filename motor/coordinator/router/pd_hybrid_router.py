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
from typing import Dict, Any
import asyncio
import sys

from fastapi.responses import StreamingResponse, JSONResponse

from motor.coordinator.models.request import ReqState
from motor.coordinator.router.base_router import BaseRouter
from motor.common.resources.instance import PDRole
from motor.coordinator.tracer.tracing import TracerManager


class PDHybridRouter(BaseRouter):
    """Handle request with a single PD hybrid instance"""
    
    async def handle_request(self) -> StreamingResponse | JSONResponse:

        req_data = self.req_info.req_data.copy()

        if self.req_info.req_data.get("stream", False):
            return await self._generate_stream(req_data)
        return await self._generate_post(req_data)

    async def _generate_stream(self, req_data: Dict[str, Any]) -> StreamingResponse:
        """
        Handling hybrid streaming requests
        """
        trace_obj = self.req_info.trace_obj
        span_ctx = TracerManager().tracer.start_as_current_span(
            "PDHybrid_stream", context=trace_obj.parent_context
        )
        with span_ctx as span:
            trace_obj.set_time_start()
            trace_obj.span = span
            trace_obj.trace_headers = TracerManager().inject_trace_context()
            trace_obj.set_trace_attribute("requestId", self.req_info.req_id)
            trace_obj.set_trace_attribute("stream", True)

            self.logger.debug("Handling hybrid streaming request")
            max_retry = self.config.exception_config.max_retry
            
            for attempt in range(max_retry):
                # Initialize context variables to None
                resource_ctx = None
                client_ctx = None
                
                try:
                    # Initialize resource context
                    resource_ctx = self._manage_resource_context(PDRole.ROLE_P, self.release_all)
                    resource = await resource_ctx.__aenter__()
                    client_ctx = self._manage_client_context(resource)
                    client = await client_ctx.__aenter__()
                    
                    generator = await self.forward_stream_request(
                        req_data, client, self.config.exception_config.first_token_timeout
                    )
                    
                    async def create_stream(generator, resource_ctx, client_ctx):
                        try:
                            async for chunk in generator():
                                yield chunk
                        except asyncio.CancelledError:
                            self.logger.info("The streaming request was terminated because of "
                                            "infer timeout or client disconnect.")
                            raise
                        except Exception as e:
                            self.logger.error("Error in streaming: %s", str(e), exc_info=True)
                            trace_obj.set_trace_status(e)
                            self.req_info.update_state(ReqState.EXCEPTION)
                            # If chunk was already sent, cannot retry the HTTP stream.
                            # Send error chunk and terminate.
                            yield self._generate_streaming_error_chunk(e)
                        finally:
                            # The cleanup order is reverse of the inital order.
                            await client_ctx.__aexit__(None, None, None)
                            await resource_ctx.__aexit__(None, None, None)
                        return

                    self.req_info.update_state(ReqState.DECODE_END)
                    self.logger.info(trace_obj.set_end_and_ttft_tpot())
                    return StreamingResponse(
                        create_stream(generator, resource_ctx, client_ctx),
                        media_type="text/event-stream"
                    )
                except Exception as e:
                    self.logger.error(
                        "Error in streaming (attempt %d/%d): %s",
                        attempt + 1, max_retry, str(e), exc_info=(attempt == 0)
                    )

                    # The cleanup order is reverse of the inital order.
                    if client_ctx is not None:
                        await client_ctx.__aexit__(*sys.exc_info())
                    if resource_ctx is not None:
                        await resource_ctx.__aexit__(*sys.exc_info())

                    if attempt == max_retry - 1:
                        trace_obj.set_trace_status(e)
                        self.logger.error("All retries failed for streaming hybrid request.")
                        self.req_info.update_state(ReqState.EXCEPTION)
                        raise e
                
                    wait_time = self.config.exception_config.retry_delay * (2 ** attempt)
                    self.logger.info("Retrying streaming request in %.2f seconds...", wait_time)
                    await asyncio.sleep(wait_time)

    async def _generate_post(self, req_data: Dict[str, Any]) -> JSONResponse:
        """
        Handling hybrid non-streaming requests
        """
        trace_obj = self.req_info.trace_obj
        span_ctx = TracerManager().tracer.start_as_current_span(
            "PDHybrid", context=trace_obj.parent_context
        )
        with span_ctx as span:
            trace_obj.span = span
            trace_obj.trace_headers = TracerManager().inject_trace_context()
            trace_obj.set_trace_attribute("requestId", self.req_info.req_id)
            trace_obj.set_trace_attribute("stream", False)

            self.logger.debug("Handling hybrid non-streaming request")
            max_retries = self.config.exception_config.max_retry

            for attempt in range(max_retries):
                try:
                    async with self._manage_resource_context(PDRole.ROLE_P, self.release_all) as resource, \
                                self._manage_client_context(resource) as client:

                        response = await self.forward_request(
                                req_data, client, self.config.exception_config.infer_timeout
                            )

                        self.req_info.update_state(ReqState.DECODE_END)
                        return JSONResponse(content=response.json())

                except asyncio.CancelledError:
                    self.logger.debug("Post request was cancelled")
                    raise
                except Exception as e:
                    self.logger.error("Error in post (attempt %d/%d): %s", attempt + 1, max_retries, str(e))

                    trace_obj.set_trace_exception(e)
                    if attempt < max_retries - 1:
                        wait_time = self.config.exception_config.retry_delay * (2 ** attempt)
                        self.logger.info("Retrying non-streaming request in %.2f seconds...", wait_time)
                        await asyncio.sleep(wait_time)
                        continue

                    self.logger.error("All retries failed for non-streaming decode request.")
                    self.req_info.update_state(ReqState.EXCEPTION)
                    raise e
