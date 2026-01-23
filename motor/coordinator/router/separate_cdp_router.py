#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
import asyncio
import contextlib
from typing import Dict, AsyncGenerator, Any

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse, JSONResponse

from motor.common.resources.instance import PDRole
from motor.coordinator.core.request_manager import RequestManager
from motor.coordinator.models.contants import CHAT_COMPLETION_PREFIX, COMPLETION_PREFIX, COMPLETION_SUFFIX
from motor.coordinator.models.contants import REQUEST_ID_KEY
from motor.coordinator.models.request import ReqState
from motor.coordinator.router.base_router import BaseRouter


class SeparateCDPRouter(BaseRouter):

    @contextlib.asynccontextmanager
    async def _manage_request_context(self):
        """
        Lifecycle management for request in the RequestManager.
        Ensures request info is added and cleaned up.
        """
        RequestManager().add_req_info(self.req_info)
        try:
            yield
        finally:
            RequestManager().del_req_info(self.req_info.req_id)
            self._log_request_details()

    async def handle_request(self) -> StreamingResponse | JSONResponse:

        req_data = self._gen_d_request()

        if self.req_info.req_data.get("stream", False):
            return StreamingResponse(
                self._generate_stream(req_data),
                media_type="text/event-stream"
            )
        return await self._generate_post(req_data)

    async def handle_metaserver_request(self) -> Dict[str, Any]:
        """
        Handles the Prefill requests by metaserver
        """
        req_data = self._gen_p_request()
        try:
            # Schedule Prefill instance and forward the request
            async with self._manage_resource_context(PDRole.ROLE_P, self.release_all) as resource, \
                       self._manage_client_context(resource, 
                                                    self.config.exception_config.first_token_timeout
                                                   ) as client:

                self.req_info.set_client(client, PDRole.ROLE_P)
                response = await self.forward_post_request(req_data, client)
                resp_json = response.json()
                
                self.logger.debug("Prefill response received: %s", resp_json)
                self.req_info.update_state(ReqState.PREFILL_END)
                return resp_json

        except asyncio.CancelledError:
            self.logger.warning("Metaserver request was cancelled")
            await self.req_info.close_clients()
            raise
        except Exception as e:
            self.logger.error("Failed to forward Prefill request: %s", e)
            await self.req_info.close_clients()
            self.req_info.update_state(ReqState.EXCEPTION)
            raise e

    async def _generate_stream(self, req_data: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        Handles streaming Decode requests
        """
        self.logger.debug("Handling streaming Decode request")
        max_retry = self.config.exception_config.max_retry

        for attempt in range(max_retry):
            try:
                # Use context managers to ensure resource locking and client cleanup
                async with self._manage_request_context(), \
                           self._manage_resource_context(PDRole.ROLE_D, self.release_tokens) as resource, \
                           self._manage_client_context(resource, 
                                                        self.config.exception_config.first_token_timeout
                                                       ) as client:
                            
                    self.req_info.set_client(client, PDRole.ROLE_D)
                    
                    async for chunk in self.forward_stream_request(req_data, client):
                        yield chunk
                    
                    self.req_info.update_state(ReqState.DECODE_END)
                return

            except asyncio.CancelledError:
                self.logger.debug("The streaming request was terminated because of "
                                  "infer timeout or client disconnect.")
                await self.req_info.close_clients()
                raise
            except Exception as e:
                self.logger.error(
                    "Error in streaming Decode (attempt %d/%d): %s",
                    attempt + 1, max_retry, str(e), exc_info=True
                )
                await self.req_info.close_clients()

                # If chunk was already sent, cannot retry the HTTP stream.
                # Send error chunk and terminate.
                if self.first_chunk_sent or attempt == max_retry - 1:
                    self.req_info.update_state(ReqState.EXCEPTION)
                    yield self._generate_streaming_error_chunk(e)
                    return

                wait_time = self.config.exception_config.retry_delay * (2 ** attempt)
                self.logger.info("Retrying streaming request in %.2f seconds...", wait_time)
                await asyncio.sleep(wait_time)

    async def _generate_post(self, req_data: Dict[str, Any]) -> JSONResponse:
        """
        Handles non-streaming Decode requests
        """
        self.logger.debug("Handling non-streaming Decode request")
        max_retries = self.config.exception_config.max_retry

        for attempt in range(max_retries):
            try:
                async with self._manage_request_context(), \
                           self._manage_resource_context(PDRole.ROLE_D, self.release_tokens) as resource, \
                           self._manage_client_context(resource, 
                                                        self.config.exception_config.infer_timeout
                                                       ) as client:
                            
                    self.req_info.set_client(client, PDRole.ROLE_D)
                    response = await self.forward_post_request(req_data, client)
                    
                    self.req_info.update_state(ReqState.DECODE_END)
                    return JSONResponse(content=response.json())

            except asyncio.CancelledError:
                self.logger.debug("The non streaming request was terminated because of "
                                  "infer timeout or client disconnect.")
                await self.req_info.close_clients()
                raise
            except Exception as e:
                self.logger.error(
                    "Error in post Decode (attempt %d/%d): %s",
                    attempt + 1, max_retries, str(e)
                )
                await self.req_info.close_clients()

                if attempt < max_retries - 1:
                    wait_time = self.config.exception_config.retry_delay * (2 ** attempt)
                    self.logger.info("Retrying non-streaming request in %.2f seconds...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                self.logger.error("All retries failed for non-streaming decode request.")
                self.req_info.update_state(ReqState.EXCEPTION)
                raise e

    def _gen_d_request(self) -> dict:
        """Generate D request parameters"""
        # read management http config
        host = self.config.http_config.coordinator_api_host
        port = self.config.http_config.coordinator_api_mgmt_port

        if self.config.infer_tls_config.tls_enable:
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

    def _gen_p_request(self) -> dict:
        """Generate P request parameters"""
        kv_transfer_params = self.req_info.req_data.copy()

        # get origin req_info reference for update request state
        self.req_info = self._get_origin_request_info(kv_transfer_params)

        # Copy req_data before modify
        req_data = self.req_info.req_data.copy()
        req_data["stream"] = False
        req_data["max_tokens"] = 1
        req_data["kv_transfer_params"] = kv_transfer_params

        if "stream_options" in req_data:
            del req_data["stream_options"]

        return req_data

    def _get_origin_request_info(self, kv_transfer_params: dict):
        def trim_request_id_prefix(vllm_request_id: str) -> None:
            original_id = vllm_request_id
            if vllm_request_id.startswith(CHAT_COMPLETION_PREFIX):
                original_id = vllm_request_id.removeprefix(CHAT_COMPLETION_PREFIX)
            elif vllm_request_id.startswith(COMPLETION_PREFIX) and vllm_request_id.endswith(COMPLETION_SUFFIX):
                original_id = vllm_request_id.removeprefix(COMPLETION_PREFIX).removesuffix(COMPLETION_SUFFIX)
            return original_id
        request_id = trim_request_id_prefix(kv_transfer_params["request_id"])

        req_info = RequestManager().get_req_info(request_id)
        if not req_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail=f"Request ID {request_id} not found in RequestManager"
            )
        # update real req_id as prefix for logger adaptor
        if isinstance(self.logger.extra, dict):
            self.logger.extra[REQUEST_ID_KEY] = req_info.req_id

        return req_info