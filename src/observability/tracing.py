"""Tracing — re-export from the app's OpenTelemetry setup."""

from __future__ import annotations

from apps.api.app.observability.otel import traced_operation

__all__ = ["traced_operation"]
