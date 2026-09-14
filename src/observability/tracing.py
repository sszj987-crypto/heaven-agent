"""Privacy-safe OpenTelemetry primitives used by the agent runtime.

The module intentionally records only operational metadata. Prompts, replies,
memory contents, and voice instructions must never be added to span attributes.
Applications may configure any OpenTelemetry exporter; without one, the API is
a low-overhead no-op.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator, Mapping

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, Tracer


_REQUEST_ID: ContextVar[str | None] = ContextVar("heaven_request_id", default=None)


def get_agent_tracer() -> Tracer:
    """Return the stable tracer used by the agent execution pipeline."""
    return trace.get_tracer("heaven_agent.agent", "0.2.0")


def bind_request_id(request_id: str) -> Token[str | None]:
    """Bind an HTTP request id to the current async context."""
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request id after the request completes."""
    _REQUEST_ID.reset(token)


def current_request_id() -> str | None:
    """Read the request id propagated through the current async context."""
    return _REQUEST_ID.get()


def mark_span_error(span: Span, exc: BaseException) -> None:
    """Mark failure without recording exception messages that may contain PII."""
    span.set_attribute("error.type", type(exc).__name__)
    span.set_status(Status(StatusCode.ERROR))


@contextmanager
def start_agent_span(
    tracer: Tracer,
    name: str,
    *,
    parent: Span | None = None,
    attributes: Mapping[str, object] | None = None,
) -> Iterator[Span]:
    """Start and finish a span without binding context across stream yields.

    Agent replies are async generators. OpenTelemetry's current-span context
    manager cannot safely remain attached while control is yielded to an SSE
    consumer, so parentage is passed explicitly instead.
    """
    parent_context = trace.set_span_in_context(parent) if parent is not None else None
    span = tracer.start_span(name, context=parent_context, attributes=attributes)
    try:
        yield span
    except Exception as exc:
        mark_span_error(span, exc)
        raise
    finally:
        span.end()
