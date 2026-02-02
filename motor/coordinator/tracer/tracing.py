# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import os
import re
import dataclasses
import threading
import time
from collections.abc import Mapping
from typing import Optional
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

# OpenTelemetry Related Introduction
from opentelemetry import context as context_api
from opentelemetry import trace as trace_api
from opentelemetry.sdk.environment_variables import OTEL_EXPORTER_OTLP_TRACES_PROTOCOL
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import NoOpTracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace.status import Status, StatusCode
from opentelemetry.util import types

from motor.common.utils.singleton import ThreadSafeSingleton
from motor.common.utils.logger import get_logger
from motor.config.coordinator import CoordinatorConfig

logger = get_logger(__name__)


class TracerManager(ThreadSafeSingleton):
    """Tracer Manager class, Singleton class"""

    _INSTRUMENTING_MODULE_NAME = "mindie.motor"
    _PROTOCOL_GRPC = "grpc"
    _PROTOCOL_HTTP = "http/protobuf"
    _TRACE_HEADERS = ("traceparent", "tracestate")
    _TEXTMAPPROPOGATOR = TraceContextTextMapPropagator()

    def __init__(self, config: CoordinatorConfig | None = None):
        """TracerManager init"""
        # If the instance manager is already initialized, return.
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.config_lock = threading.RLock()

        if config is None:
            config = CoordinatorConfig()

        self.endpoint = config.tracer_config.endpoint
        self.root_sampling_rate = config.tracer_config.root_sampling_rate
        self.remote_parent_sampled = config.tracer_config.remote_parent_sampled
        self.remote_parent_not_sampled = config.tracer_config.remote_parent_not_sampled
        self.local_parent_sampled = config.tracer_config.local_parent_sampled
        self.local_parent_not_sampled = config.tracer_config.local_parent_not_sampled

        self._protocol = self.get_protocol()
        enable = (len(self._protocol) > 0)
        self.tracer = self.init_tracer(enable)
        logger.info(f"TracerManager init.(enable:{enable},endpoint:{self.endpoint},protocol:{self._protocol})")

    def update_config(self, config: CoordinatorConfig) -> None:
        """Update configuration for the TracerManager"""
        with self.config_lock:
            self.endpoint = config.tracer_config.endpoint
            self.root_sampling_rate = config.tracer_config.root_sampling_rate
            self.remote_parent_sampled = config.tracer_config.remote_parent_sampled
            self.remote_parent_not_sampled = config.tracer_config.remote_parent_not_sampled
            self.local_parent_sampled = config.tracer_config.local_parent_sampled
            self.local_parent_not_sampled = config.tracer_config.local_parent_not_sampled
 
            self._protocol = self.get_protocol()
            enable = (len(self._protocol) > 0)
            self.tracer = self.init_tracer(enable)
            logger.info(f"TracerManager update.(enable:{enable},endpoint:{self.endpoint},protocol:{self._protocol})")

    def init_tracer(self, enabled=True) -> trace_api.Tracer:
        """Obtain a configured Tracer instance"""
        if enabled:
            sampler = ParentBased(
                root=TraceIdRatioBased(self.root_sampling_rate),
                remote_parent_sampled=TraceIdRatioBased(self.remote_parent_sampled),
                remote_parent_not_sampled=TraceIdRatioBased(self.remote_parent_not_sampled),
                local_parent_sampled=TraceIdRatioBased(self.local_parent_sampled),
                local_parent_not_sampled=TraceIdRatioBased(self.local_parent_not_sampled)
            )

            span_exporter = self.get_span_exporter()

            trace_provider = TracerProvider(sampler=sampler)
            trace_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        else:
            trace_provider = NoOpTracerProvider()

        trace_api.set_tracer_provider(trace_provider)
        return trace_api.get_tracer(self._INSTRUMENTING_MODULE_NAME)

    def get_span_exporter(self) -> SpanExporter:
        """Obtain the appropriate span exporter based on environment variables"""
        if self._protocol == self._PROTOCOL_GRPC:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        elif self._protocol == self._PROTOCOL_HTTP:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,  # type: ignore
            )
        else:
            raise ValueError(f"env OTEL_EXPORTER_OTLP_TRACES_PROTOCOL:'{self._protocol}' is invalid")

        return OTLPSpanExporter(endpoint=self.endpoint)

    def get_protocol(self) -> str:
        """get and check protocol config"""
        protocol = os.environ.get(OTEL_EXPORTER_OTLP_TRACES_PROTOCOL, self._PROTOCOL_GRPC)
        pattern = r'^(grpc://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:[0-9]{1,5})$'
        if protocol == self._PROTOCOL_HTTP:
            pattern = r'^(http://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:[0-9]{1,5}/v1/traces)$'

        if re.fullmatch(pattern, self.endpoint):
            return protocol
        else:
            logger.info(f"check: endpoint:{self.endpoint}, OTEL_EXPORTER_OTLP_TRACES_PROTOCOL:{protocol}")
            return ""

    def extract_trace_context(self, headers: Mapping[str, str] | None) -> context_api.Context:
        """Extract the trace context from headers"""
        headers = headers or {}
        tmp_headers = {
            h: headers[h] 
            for h in self._TRACE_HEADERS 
            if h in headers
        }

        return self._TEXTMAPPROPOGATOR.extract(tmp_headers)

    def inject_trace_context(self) -> Mapping[str, str]:
        """Inject the current trace context into headers"""
        headers = {}
        self._TEXTMAPPROPOGATOR.inject(headers)

        return headers

    def contains_trace_headers(self, headers: Mapping[str, str]) -> bool:
        """Check whether the headers contain the trace header"""
        return any(h in headers for h in self._TRACE_HEADERS)


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class TraceObj:
    """
    The trace object for distributed tracing, which includes the Span and trace header information.
    Attributes:
        span: The Span object currently being traced.
        meta_span: The Span object currently being traced.
        trace_headers: A dictionary of trace header information.
        meta_trace_headers: A dictionary of trace header information.
    """

    time_start: int = 0
    time_first_token: int = 0
    count_token: int = 0

    parent_context: Optional[context_api.Context] = None
    span: Optional[trace_api.Span] = None
    meta_span: Optional[trace_api.Span] = None
    trace_headers: Mapping[str, str] = dataclasses.field(default_factory=dict)
    meta_trace_headers: Mapping[str, str] = dataclasses.field(default_factory=dict)

    def set_time_start(self) -> None:
        """
        Sets an attribute on the trace span if the trace object and span are available.
        """
        self.time_start = time.time_ns()

    def set_time_first_token(self) -> None:
        """
        Sets an attribute on the trace span if the trace object and span are available.
        """
        self.time_first_token = time.time_ns()
        self.add_trace_event("Received the first token")

    def set_count_token(self, cnt: int) -> None:
        """
        Sets an attribute on the trace span if the trace object and span are available.
        """
        self.count_token = cnt

    def set_end_and_ttft_ttot(self) -> str:
        """
        Sets an attribute on the trace span if the trace object and span are available.
        """
        time_end = time.time_ns()
        ttft = (self.time_first_token - self.time_start) // 1_000_000
        ttot = (time_end - self.time_first_token) / (self.count_token * 1_000_000)
        self.set_trace_attribute("TTFT(ms)", f"{ttft}")
        self.set_trace_attribute("TTOT(ms)", f"{ttot}")
        self.set_trace_attribute("TOKEN_COUNT", f"{self.count_token}")
        return f"Tracer: TTFT: {ttft}ms, TTOT: {ttot}ms, count_token: {self.count_token}"

    def set_trace_attribute(
        self,
        key: str,
        value: types.AttributeValue,
        is_meta: bool = False
    ) -> None:
        """
        Sets an attribute on the trace span if the trace object and span are available.
        """
        tmp_span = self.meta_span if is_meta else self.span
        if tmp_span is None:
            return
        tmp_span.set_attribute(key, value)

    def add_trace_event(
        self, 
        name: str,
        attributes: types.Attributes = None,
        timestamp: Optional[int] = None,
        is_meta: bool = False
    ) -> None:
        """
        Adds an event to the trace span if the trace object and span are available.
        """
        tmp_span = self.meta_span if is_meta else self.span
        if tmp_span is None:
            return
        tmp_span.add_event(name, attributes, timestamp)
    
    def get_trace_headers_dict(
        self,
        is_meta: bool = False
    ) -> dict[str, str]:
        """
        Returns a copy of the trace headers as a dict.
        Returns an empty dict if trace_obj or trace_headers is not available.
        """
        tmp_trace_headers = self.meta_trace_headers if is_meta else self.trace_headers
        if tmp_trace_headers is None:
            return {}
        return dict(tmp_trace_headers)

    def set_trace_exception(
        self,
        exception: BaseException,
        is_meta: bool = False
    ) -> None:
        """
        Records an exception into the current trace span.
        If is_meta is True, the exception is recorded into meta_span; otherwise, it is recorded into span.
        Args:
        exception (BaseException): The exception object to be recorded.
        is_meta (bool, optional): Whether to use meta_span. Default is False.
        """
        tmp_span = self.meta_span if is_meta else self.span
        if tmp_span is None:
            return
        tmp_span.record_exception(exception)

    def set_trace_status(
        self,
        exception: BaseException,
        is_meta: bool = False
    ) -> None:
        """
        Set the status of the current span to ERROR, with the exception information included.
        If is_meta is True, set it to meta_span; otherwise, set it to span.
        Args:
        exception (BaseException): The exception object used to generate the status description.
        is_meta (bool, optional): Whether to use meta_span. Default is False.
        """
        tmp_span = self.meta_span if is_meta else self.span
        if tmp_span is None:
            return
        tmp_span.set_status(
            Status(
                status_code=StatusCode.ERROR,
                description=f"{type(exception).__name__}: {exception}",
            )
        )