"""
Aegis Real ADK Worker

Runs a real ADK agent utilizing the Google GenAI SDK and instruments the run
using openinference-instrumentation-google-adk to export OpenInference-compliant spans.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any
from .adk_adapter import WorkerResult

HAS_ADK_DEPS = False
try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from openinference.instrumentation.google_adk import GoogleADKInstrumentor
    HAS_ADK_DEPS = True
except ImportError:
    pass


class AegisTracingSetup:
    """
    Sets up OpenTelemetry tracing with OpenInference instrumentation for Google ADK.
    Allows capturing spans in memory and optionally exporting them to Phoenix.
    """

    def __init__(self, trace_to_phoenix: bool = True) -> None:
        self.memory_exporter = None
        self.tracer_provider = None
        if not HAS_ADK_DEPS:
            return

        self.memory_exporter = InMemorySpanExporter()
        self.tracer_provider = TracerProvider()
        self.tracer_provider.add_span_processor(SimpleSpanProcessor(self.memory_exporter))

        # Optional OTLP export to Arize/Phoenix if collector endpoint is configured
        phoenix_endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if trace_to_phoenix and phoenix_endpoint:
            try:
                # Phoenix typically listens on /v1/traces
                if not phoenix_endpoint.endswith("/v1/traces") and "localhost" in phoenix_endpoint:
                    phoenix_endpoint = phoenix_endpoint.rstrip("/") + "/v1/traces"
                otlp_exporter = OTLPSpanExporter(endpoint=phoenix_endpoint)
                self.tracer_provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))
            except Exception:
                # Silent fallback if exporter setup fails (e.g. connection refused)
                pass

        # Apply OpenInference instrumentation for Google ADK
        # This MUST be called before we import and use google.adk
        GoogleADKInstrumentor().instrument(tracer_provider=self.tracer_provider)


class RealADKWorker:
    """
    A real Google ADK agent runner that executes tasks and collects tracing spans.
    """

    def __init__(self, agent_id: str = "real-adk-worker", use_phoenix: bool = True) -> None:
        self.agent_id = agent_id
        self.use_phoenix = use_phoenix
        self._tracing_setup = None
        if HAS_ADK_DEPS:
            self._tracing_setup = AegisTracingSetup(trace_to_phoenix=use_phoenix)

    async def run_async(self, task_description: str) -> WorkerResult:
        if not HAS_ADK_DEPS:
            raise RuntimeError(
                "ADK dependencies not installed. Ensure openinference-instrumentation-google-adk, "
                "google-adk, and opentelemetry-sdk are installed."
            )

        # Import ADK modules dynamically after instrumentor is set up
        from google.adk.agents import Agent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        # Define 2 simple tools to demonstrate capability execution
        def calculate_addition(a: float, b: float) -> float:
            """Add two numbers together. Use this tool for simple math addition."""
            return a + b

        def calculate_multiplication(a: float, b: float) -> float:
            """Multiply two numbers together. Use this tool for simple math multiplication."""
            return a * b

        # Build a simple ADK agent
        agent = Agent(
            model="gemini-2.5-flash",
            instruction=(
                "You are an Aegis Worker Agent. Accomplish the task given by the user. "
                "Always use your tools when math is needed. When done, write a short summary of what you did."
            ),
            tools=[calculate_addition, calculate_multiplication],
        )

        session_service = InMemorySessionService()
        session = await session_service.create_session(app_name="aegis-real-demo", user_id="aegis")
        runner = Runner(agent=agent, app_name="aegis-real-demo", session_service=session_service)

        message = types.Content(role="user", parts=[types.Part(text=task_description)])

        claimed_success = False
        final_text = ""

        try:
            async for event in runner.run_async(
                session_id=session.id,
                user_id="aegis",
                new_message=message,
            ):
                if event.is_final_response():
                    final_text = event.content.parts[0].text
                    claimed_success = True
        except Exception as e:
            final_text = f"Agent failed with error: {e}"
            claimed_success = False

        # Collect and convert spans from our memory exporter
        raw_spans = self.collect_and_convert_spans()

        # Extract tool calls from spans
        tool_calls = []
        for span in raw_spans:
            attrs = span.get("attributes", {})
            if attrs.get("openinference.span.kind") == "TOOL":
                tool_calls.append({
                    "name": attrs.get("tool.name") or span.get("name", "unknown"),
                    "capability_id": attrs.get("tool.name"),
                    "input": attrs.get("input.value", ""),
                    "output": attrs.get("output.value", ""),
                    "status": "success" if span.get("status", {}).get("status_code") == "OK" else "failure",
                    "artifacts": [],
                })

        trace_id = ""
        if raw_spans:
            trace_id = raw_spans[0].get("context", {}).get("trace_id", "")
        if not trace_id:
            trace_id = str(uuid.uuid4())

        return WorkerResult(
            trace_id=trace_id,
            agent_id=self.agent_id,
            claimed_success=claimed_success,
            summary=final_text,
            tool_calls=tool_calls,
            raw_spans=raw_spans,
        )

    def collect_and_convert_spans(self) -> list[dict[str, Any]]:
        if not self._tracing_setup or not self._tracing_setup.memory_exporter:
            return []

        spans = self._tracing_setup.memory_exporter.get_finished_spans()
        converted = []
        for span in spans:
            converted.append(self._convert_span(span))
        return converted

    def _convert_span(self, span: Any) -> dict[str, Any]:
        # Hex encode span context attributes
        span_id_hex = ""
        trace_id_hex = ""
        if hasattr(span, "context") and span.context:
            span_id = span.context.span_id
            trace_id = span.context.trace_id
            span_id_hex = f"{span_id:016x}" if isinstance(span_id, int) else span_id.hex() if hasattr(span_id, "hex") else str(span_id)
            trace_id_hex = f"{trace_id:032x}" if isinstance(trace_id, int) else trace_id.hex() if hasattr(trace_id, "hex") else str(trace_id)

        parent_span_id_hex = None
        if hasattr(span, "parent") and span.parent and hasattr(span.parent, "span_id"):
            parent_id = span.parent.span_id
            parent_span_id_hex = f"{parent_id:016x}" if isinstance(parent_id, int) else parent_id.hex() if hasattr(parent_id, "hex") else str(parent_id)

        # Status Code mapping
        from opentelemetry.trace import StatusCode
        status_code = "UNSET"
        status_desc = ""
        if hasattr(span, "status") and span.status:
            if span.status.status_code == StatusCode.OK:
                status_code = "OK"
            elif span.status.status_code == StatusCode.ERROR:
                status_code = "ERROR"
            status_desc = span.status.description or ""

        # Attributes mapping
        attrs = {}
        if hasattr(span, "attributes") and span.attributes:
            for k, v in span.attributes.items():
                attrs[str(k)] = v

        return {
            "name": getattr(span, "name", "span"),
            "attributes": attrs,
            "context": {
                "span_id": span_id_hex,
                "trace_id": trace_id_hex,
            },
            "parent_id": parent_span_id_hex,
            "status": {
                "status_code": status_code,
                "description": status_desc,
            },
            "start_time": getattr(span, "start_time", 0),
            "end_time": getattr(span, "end_time", 0),
        }
