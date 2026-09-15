"""Tracing — OpenTelemetry setup and the `traced_operation` context manager."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None


def setup_otel(*, service_name: str, endpoint: str | None) -> None:
    """Call once at app startup."""
    global _provider
    if not endpoint:
        return  # tracing disabled
    if _provider is not None:
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _provider = provider


class TracedOperation:
    """Context manager supporting both synchronous 'with' and asynchronous 'async with'."""

    def __init__(self, name: str, **attributes: Any) -> None:
        self.name = name
        self.attributes = attributes
        self._cm: Any = None
        self.span: trace.Span | None = None

    def __enter__(self) -> trace.Span:
        tracer = trace.get_tracer(__name__)
        self._cm = tracer.start_as_current_span(self.name)
        self.span = self._cm.__enter__()
        for k, v in self.attributes.items():
            with suppress(Exception):
                self.span.set_attribute(k, v)
        return self.span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        if self._cm is not None:
            return self._cm.__exit__(exc_type, exc_val, exc_tb)
        return False

    async def __aenter__(self) -> trace.Span:
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self.__exit__(exc_type, exc_val, exc_tb)


def traced_operation(name: str, **attributes: Any) -> TracedOperation:
    """Context manager that creates a span and sets attributes on it. Supports sync and async."""
    return TracedOperation(name, **attributes)
