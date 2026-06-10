"""
Aegis Trace Adapter

Normalizes raw trace data from Arize Phoenix / OpenInference / OTLP spans
into Aegis EvidenceEvents.

This lives in the adapters/ layer because trace normalization is an
adapter-boundary concern: it translates runtime-specific span format
into the runtime-agnostic Aegis evidence model.

Supports:
  - OpenInference span dicts (from Phoenix)
  - OTLP-style span objects (from opentelemetry-sdk)
  - Raw dict traces (for testing / stub adapters)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aegis.evidence_model import (
    Artifact,
    EvidenceEvent,
    EventStatus,
    EventType,
    TokenUsage,
)

# ---------------------------------------------------------------------------
# OpenInference attribute key constants (subset)
# ---------------------------------------------------------------------------

OI_INPUT_VALUE = "input.value"
OI_OUTPUT_VALUE = "output.value"
OI_LLM_TOKEN_INPUT = "llm.token_count.prompt"
OI_LLM_TOKEN_OUTPUT = "llm.token_count.completion"
OI_LLM_TOKEN_TOTAL = "llm.token_count.total"
OI_TOOL_NAME = "tool.name"
OI_STATUS = "openinference.span.kind"
OI_SPAN_KIND = "openinference.span.kind"

# OpenInference span kinds → EventType
_OI_KIND_MAP: dict[str, EventType] = {
    "LLM": EventType.MODEL_CALL,
    "TOOL": EventType.TOOL_CALL,
    "CHAIN": EventType.SPAN,
    "RETRIEVER": EventType.SPAN,
    "EMBEDDING": EventType.MODEL_CALL,
    "AGENT": EventType.SPAN,
    "RERANKER": EventType.SPAN,
}


class TraceAdapter:
    """
    Normalizes OpenInference / Phoenix / OTLP spans into Aegis EvidenceEvents.

    Usage::

        adapter = TraceAdapter(agent_id="my-adk-worker")
        events = adapter.from_openinference_spans(spans)
    """

    def __init__(self, agent_id: str, trace_id: str | None = None) -> None:
        self.agent_id = agent_id
        self.trace_id = trace_id or "unknown-trace"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def from_openinference_spans(
        self,
        spans: list[dict[str, Any]],
    ) -> list[EvidenceEvent]:
        """
        Convert a list of OpenInference span dicts (as returned by Phoenix)
        into Aegis EvidenceEvents.
        """
        events = []
        for span in spans:
            event = self._span_to_event(span)
            if event:
                events.append(event)
        return events

    def from_dict_trace(
        self,
        trace: dict[str, Any],
    ) -> list[EvidenceEvent]:
        """
        Convert a raw dict-format trace (e.g. from mock/demo adapters)
        into Aegis EvidenceEvents.

        Expected keys: trace_id, spans (list of span dicts)
        """
        trace_id = trace.get("trace_id", self.trace_id)
        adapter = TraceAdapter(agent_id=self.agent_id, trace_id=trace_id)
        spans = trace.get("spans", [])
        return adapter.from_openinference_spans(spans)

    def from_tool_call_list(
        self,
        tool_calls: list[dict[str, Any]],
        trace_id: str | None = None,
    ) -> list[EvidenceEvent]:
        """
        Convert a simple list of tool call dicts (name, input, output, status)
        into Aegis EvidenceEvents. Useful for ADK / simple agent adapters.
        """
        events = []
        effective_trace_id = trace_id or self.trace_id
        for call in tool_calls:
            status_raw = call.get("status", "success").lower()
            status = EventStatus(status_raw) if status_raw in EventStatus._value2member_map_ else EventStatus.SUCCESS  # type: ignore
            event = EvidenceEvent(
                event_type=EventType.TOOL_CALL,
                trace_id=effective_trace_id,
                agent_id=self.agent_id,
                capability_id=call.get("capability_id"),
                input_summary=str(call.get("input", ""))[:500],
                output_summary=str(call.get("output", ""))[:500],
                status=status,
                error=call.get("error"),
                metadata=call.get("metadata", {}),
            )
            artifacts = call.get("artifacts", [])
            for art in artifacts:
                event.artifacts.append(
                    Artifact(
                        type=art.get("type", "unknown"),
                        path=art.get("path"),
                        url=art.get("url"),
                        description=art.get("description", ""),
                    )
                )
            events.append(event)
        return events

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _span_to_event(self, span: dict[str, Any]) -> EvidenceEvent | None:
        attrs = span.get("attributes", {})
        if not attrs and not span.get("name"):
            return None

        span_kind = attrs.get(OI_SPAN_KIND, "CHAIN").upper()
        event_type = _OI_KIND_MAP.get(span_kind, EventType.SPAN)

        # Status
        status_str = str(span.get("status", {}).get("status_code", "OK")).upper()
        if status_str in ("OK", "UNSET"):
            status = EventStatus.SUCCESS
        elif status_str == "ERROR":
            status = EventStatus.FAILURE
        else:
            status = EventStatus.SUCCESS

        # Timestamps
        start_ns = span.get("start_time") or span.get("start_time_unix_nano", 0)
        end_ns = span.get("end_time") or span.get("end_time_unix_nano", 0)
        start_dt = self._ns_to_dt(start_ns)
        end_dt = self._ns_to_dt(end_ns) if end_ns else None

        # Tokens
        token_usage = None
        inp_tok = attrs.get(OI_LLM_TOKEN_INPUT, 0)
        out_tok = attrs.get(OI_LLM_TOKEN_OUTPUT, 0)
        if inp_tok or out_tok:
            token_usage = TokenUsage(
                input_tokens=int(inp_tok),
                output_tokens=int(out_tok),
            )

        # Span / trace IDs
        span_ctx = span.get("context", {})
        span_id = str(span_ctx.get("span_id", "")) or span.get("span_id", "")
        trace_id = str(span_ctx.get("trace_id", "")) or span.get("trace_id", self.trace_id)
        parent_span_id = str(span.get("parent_id", "") or "") or None

        return EvidenceEvent(
            event_type=event_type,
            trace_id=trace_id or self.trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent_id=self.agent_id,
            capability_id=attrs.get(OI_TOOL_NAME),
            input_summary=str(attrs.get(OI_INPUT_VALUE, ""))[:500],
            output_summary=str(attrs.get(OI_OUTPUT_VALUE, ""))[:500],
            status=status,
            timestamp=start_dt,
            end_timestamp=end_dt,
            token_usage=token_usage,
            error=span.get("status", {}).get("description"),
            metadata={"span_name": span.get("name", ""), "span_kind": span_kind},
        )

    @staticmethod
    def _ns_to_dt(ns: int | float | None) -> datetime:
        if not ns:
            return datetime.now(tz=timezone.utc)
        # Handle both nanoseconds and seconds
        if ns > 1e12:
            seconds = ns / 1e9
        else:
            seconds = float(ns)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
