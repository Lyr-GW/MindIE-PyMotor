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

import asyncio
import time
import sys
from typing import Any

import anyio
from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse, JSONResponse

from motor.common.resources.instance import PDRole
from motor.coordinator.models.constants import CHAT_COMPLETION_PREFIX, COMPLETION_PREFIX, COMPLETION_SUFFIX
from motor.coordinator.models.constants import REQUEST_ID_KEY
from motor.coordinator.models.request import ReqState
from motor.coordinator.router.base_router import BaseRouter
from motor.coordinator.tracer.tracing import TracerManager


class SeparateCDPRouter(BaseRouter):

    async def handle_request(self) -> StreamingResponse | JSONResponse:

        req_data = self._gen_d_request()

        if self.req_info.req_data.get("stream", False):
            return await self._generate_stream_response(req_data)
        return await self._generate_response(req_data)

    async def handle_metaserver_request(self) -> dict[str, Any]:
        """
        Handles the Prefill requests by metaserver
        """
        self.is_meta = True
        req_data = await self._gen_p_request()
        trace_obj = self.req_info.trace_obj
        headers = trace_obj.get_trace_headers_dict()
        if headers:
            trace_context = TracerManager().extract_trace_context(headers)
        else:
            trace_context = trace_obj.parent_context
        span_ctx = TracerManager().tracer.start_as_current_span("CDP_Prefill", context=trace_context)
        t0_metaserver = time.perf_counter()
        try:
            with span_ctx as span:
                trace_obj.meta_span = span
                trace_obj.meta_trace_headers = TracerManager().inject_trace_context()
                trace_obj.set_trace_attribute("requestId", self.req_info.req_id, is_meta=True)
                trace_obj.set_trace_attribute("stream", False, is_meta=True)
                # Schedule Prefill instance and forward the request
                async with self._manage_resource_context(PDRole.ROLE_P, self.release_all) as resource, \
                           self._manage_client_context(resource) as client:

                    cancel_scope = anyio.CancelScope()
                    self.req_info.set_cancel_scope(cancel_scope)
                    with cancel_scope:
                        response = await self.forward_request(
                                req_data, client, self.config.exception_config.first_token_timeout
                            )
                        resp_json = response.json()

                        self.logger.debug("Prefill response received: %s", resp_json)
                        self.req_info.update_state(ReqState.PREFILL_END)
                        elapsed_ms = (time.perf_counter() - t0_metaserver) * 1000
                        self.logger.info(
                            "Scheduling latency stage=metaserver_request_total elapsed_ms=%.2f role=ROLE_P",
                            elapsed_ms
                        )
                        return resp_json
                    if self.req_info.is_cancelled:
                        raise Exception("exception occurred in Decode request")
        except asyncio.CancelledError:
            self.logger.info("Metaserver request was cancelled")
            raise
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0_metaserver) * 1000
            self.logger.info(
                "Scheduling latency stage=metaserver_request_total elapsed_ms=%.2f error=%s",
                elapsed_ms, e
            )
            self.req_info.update_state(ReqState.EXCEPTION)
            self.req_info.set_last_exception(e)
            raise e
        finally:
            self.req_info.finish_prefill()

    async def _generate_stream_response(self, req_data: dict[str, Any]) -> StreamingResponse:
        """
        Handles streaming Decode requests
        """
        trace_obj = self.req_info.trace_obj
        span_ctx = TracerManager().tracer.start_as_current_span(
            "CDP_Decode_stream", context=trace_obj.parent_context
        )
        with span_ctx as span:
            trace_obj.set_time_start()
            trace_obj.span = span
            trace_obj.trace_headers = TracerManager().inject_trace_context()
            trace_obj.set_trace_attribute("requestId", self.req_info.req_id)
            trace_obj.set_trace_attribute("stream", True)
            self.logger.debug("Handling streaming Decode request")
            max_retry = self.config.exception_config.max_retry
            for attempt in range(max_retry):
                # Initialize context variables to None
                request_ctx = None
                resource_ctx = None
                client_ctx = None
                
                try:
                    # Initialize resource context
                    request_ctx = self._manage_request_context()
                    await request_ctx.__aenter__()
                    resource_ctx = self._manage_resource_context(PDRole.ROLE_D, self.release_tokens)
                    resource = await resource_ctx.__aenter__()
                    client_ctx = self._manage_client_context(resource)
                    client = await client_ctx.__aenter__()

                    self.req_info.reset_event()
                    
                    generator = await self.forward_stream_request(
                        req_data, client, self.config.exception_config.first_token_timeout
                    )
                    # wait for prefill process
                    await asyncio.wait_for(
                        self.req_info.wait_for_prefill(), 
                        timeout=self.config.exception_config.first_token_timeout
                    )
                    if self.req_info.get_last_exception():
                        last_exception = self.req_info.get_last_exception()
                        self.logger.error(f"Prefill failed, error response: {last_exception}")
                        raise last_exception
                    
                    # streaming decode response
                    self.logger.info("finish prefill start decode...")
                    
                    async def create_stream(generator, request_ctx, resource_ctx, client_ctx):
                        try:
                            async for chunk in generator():
                                yield chunk

                            self.req_info.update_state(ReqState.DECODE_END)
                            self.logger.info(trace_obj.set_end_and_ttft_tpot())
                        except asyncio.CancelledError:
                            self.logger.info("The streaming request was terminated because of "
                                            "infer timeout or client disconnect.")
                            self.req_info.cancel_scope()
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
                            await request_ctx.__aexit__(None, None, None)
                        return
                    return StreamingResponse(
                        content=create_stream(generator, request_ctx, resource_ctx, client_ctx),
                        media_type="text/event-stream"
                    )
                except Exception as e:
                    if isinstance(e, asyncio.TimeoutError):
                        self.logger.error(
                            "Wait for Prefill finish timeout (attempt %d/%d): %s",
                            attempt + 1, max_retry, str(e)
                        )
                    else:
                        self.logger.error(
                            "Error in streaming Decode (attempt %d/%d): %s",
                            attempt + 1, max_retry, str(e), exc_info=(attempt == 0)
                        )
                    self.req_info.cancel_scope()
                    # The cleanup order is reverse of the inital order.
                    if client_ctx is not None:
                        await client_ctx.__aexit__(*sys.exc_info())
                    if resource_ctx is not None:
                        await resource_ctx.__aexit__(*sys.exc_info())
                    if request_ctx is not None:
                        await request_ctx.__aexit__(*sys.exc_info())

                    if attempt == max_retry - 1:
                        trace_obj.set_trace_status(e)
                        self.logger.error("All retries failed for streaming decode request.")
                        self.req_info.update_state(ReqState.EXCEPTION)
                        raise e

                    wait_time = self.config.exception_config.retry_delay * (2 ** attempt)
                    self.logger.info("Retrying streaming request in %.2f seconds...", wait_time)
                    await asyncio.sleep(wait_time)

    async def _generate_response(self, req_data: dict[str, Any]) -> JSONResponse:
        """
        Handles non-streaming Decode requests
        """
        trace_obj = self.req_info.trace_obj
        span_ctx = TracerManager().tracer.start_as_current_span(
            "CDP_Decode", context=trace_obj.parent_context
        )
        with span_ctx as span:
            trace_obj.span = span
            trace_obj.trace_headers = TracerManager().inject_trace_context()
            trace_obj.set_trace_attribute("requestId", self.req_info.req_id)
            trace_obj.set_trace_attribute("stream", False)
            self.logger.debug("Handling non-streaming Decode request")
            max_retries = self.config.exception_config.max_retry
            for attempt in range(max_retries):
                try:
                    async with self._manage_request_context(), \
                            self._manage_resource_context(PDRole.ROLE_D, self.release_tokens) as resource, \
                            self._manage_client_context(resource) as client:
                        
                        self.req_info.reset_event()
                        
                        response = await self.forward_request(
                            req_data, client, self.config.exception_config.infer_timeout
                        )
                        
                        # wait for prefill process
                        await asyncio.wait_for(
                            self.req_info.wait_for_prefill(), 
                            timeout=self.config.exception_config.first_token_timeout
                        )
                        if self.req_info.get_last_exception():
                            last_exception = self.req_info.get_last_exception()
                            self.logger.error(f"Prefill failed, error response: {last_exception}")
                            raise last_exception

                        self.req_info.update_state(ReqState.DECODE_END)
                        return JSONResponse(content=response.json())
                except asyncio.CancelledError:
                    self.logger.info("The non streaming request was terminated because of "
                                    "infer timeout or client disconnect.")
                    self.req_info.cancel_scope()
                    raise
                except Exception as e:
                    if isinstance(e, asyncio.TimeoutError):
                        self.logger.error(
                            "Wait for Prefill finish timeout (attempt %d/%d): %s",
                            attempt + 1, max_retries, str(e)
                        )
                    else:
                        self.logger.error(
                            "Error in post Decode (attempt %d/%d): %s",
                            attempt + 1, max_retries, str(e), exc_info=(attempt == 0)
                        )
                    self.req_info.cancel_scope()
                    trace_obj.set_trace_exception(e)

                    if attempt < max_retries - 1:
                        wait_time = self.config.exception_config.retry_delay * (2 ** attempt)
                        self.logger.info("Retrying non-streaming request in %.2f seconds...", wait_time)
                        await asyncio.sleep(wait_time)
                        continue

                    self.logger.error("All retries failed for non-streaming decode request.")
                    self.req_info.update_state(ReqState.EXCEPTION)
                    raise e

    def _gen_d_request(self) -> dict:
        """Generate D request parameters.
        D direct to Worker metaserver: when worker_metaserver_port is set (multiprocess + CDP),
        use this Worker's metaserver URL so D hits this process and get_req_info succeeds.
        """
        host = self.config.http_config.coordinator_api_host
        worker_port = getattr(self.config, "worker_metaserver_port", None)
        if worker_port is not None:
            # D calls this Worker's metaserver (no TLS on internal Worker port)
            url = f"http://{host}:{worker_port}/v1/metaserver"
        else:
            # Mgmt process metaserver: mgmt port, use mgmt TLS
            port = self.config.http_config.coordinator_api_mgmt_port
            if self.config.mgmt_tls_config.enable_tls:
                url = f"https://{host}:{port}/v1/metaserver"
            else:
                url = f"http://{host}:{port}/v1/metaserver"
        req_data = self.req_info.req_data.copy()
        req_data['kv_transfer_params'] = {
            "do_remote_decode": False,
            "do_remote_prefill": True,
            "metaserver": url
        }
        return req_data

    async def _gen_p_request(self) -> dict:
        """Generate P request parameters"""
        kv_transfer_params = self.req_info.req_data.copy()

        # get origin req_info reference for update request state
        self.req_info = await self._get_origin_request_info(kv_transfer_params)

        # Copy req_data before modify
        req_data = self.req_info.req_data.copy()
        req_data["stream"] = False
        req_data["max_tokens"] = 1
        req_data["min_tokens"] = 1
        req_data["kv_transfer_params"] = kv_transfer_params

        if "stream_options" in req_data:
            del req_data["stream_options"]

        return req_data

    async def _get_origin_request_info(self, kv_transfer_params: dict):
        def trim_request_id_prefix(vllm_request_id: str) -> str:
            original_id = vllm_request_id
            if vllm_request_id.startswith(CHAT_COMPLETION_PREFIX):
                original_id = vllm_request_id.removeprefix(CHAT_COMPLETION_PREFIX)
            elif vllm_request_id.startswith(COMPLETION_PREFIX) and vllm_request_id.endswith(COMPLETION_SUFFIX):
                original_id = vllm_request_id.removeprefix(COMPLETION_PREFIX).removesuffix(COMPLETION_SUFFIX)
            return original_id
        request_id = trim_request_id_prefix(kv_transfer_params["request_id"])

        req_info = await self._request_manager.get_req_info(request_id)
        if not req_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail=f"Request ID {request_id} not found in RequestManager"
            )
        # update real req_id as prefix for logger adaptor
        if isinstance(self.logger.extra, dict):
            self.logger.extra[REQUEST_ID_KEY] = req_info.req_id

        return req_info
    