"""
Aegis ADK Adapter

Native Google ADK integration.

Responsibilities:
  - Run or wrap an ADK worker agent flow
  - Collect plan summary (if available from ADK)
  - Collect tool calls and outputs from ADK session
  - Connect tracing to Arize/Phoenix via OpenInference instrumentation
  - Normalize evidence into Aegis EvidenceEvent format

For MVP the ADK runner is simulated (can run without live ADK/API keys)
with a SimulatedADKWorker. Real ADK is hooked in via RealADKWorker when
`google-adk` is installed.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from aegis.evidence_model import (
    Artifact,
    EvidenceEvent,
    EventStatus,
    EventType,
)
from .trace_adapter import TraceAdapter

try:
    from .real_adk_worker import RealADKWorker
    HAS_REAL_ADK = True
except ImportError:
    HAS_REAL_ADK = False


# ---------------------------------------------------------------------------
# Worker result container
# ---------------------------------------------------------------------------


class WorkerResult:
    """Container for the output of an ADK worker run."""

    def __init__(
        self,
        trace_id: str,
        agent_id: str,
        claimed_success: bool,
        summary: str,
        tool_calls: list[dict[str, Any]],
        raw_spans: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.agent_id = agent_id
        self.claimed_success = claimed_success
        self.summary = summary
        self.tool_calls = tool_calls
        self.raw_spans = raw_spans or []
        self.metadata = metadata or {}


# ---------------------------------------------------------------------------
# Simulated ADK Worker (self-contained demo, no API needed)
# ---------------------------------------------------------------------------


class SimulatedADKWorker:
    """
    A fully simulated ADK worker that produces realistic but controlled output.

    Used for the MVP demo scenario so the full Aegis loop can be demonstrated
    without live API keys or a running ADK agent.

    The simulation intentionally leaves some criteria unmet so Aegis can
    detect the drift and propose repairs.
    """

    def __init__(self, agent_id: str = "simulated-adk-worker") -> None:
        self.agent_id = agent_id

    def run(self, task_description: str, *, skip_steps: list[str] | None = None) -> WorkerResult:
        """
        Simulate running an ADK agent on a task.

        Args:
            task_description: What the agent is supposed to do.
            skip_steps: Steps to intentionally skip (for demo drift injection).

        Returns:
            A WorkerResult with simulated traces.
        """
        skip = set(skip_steps or [])
        trace_id = str(uuid.uuid4())
        tool_calls: list[dict[str, Any]] = []

        # Simulate: read the file
        if "read" not in skip:
            tool_calls.append({
                "name": "read_file",
                "capability_id": "read_file",
                "input": "auth/login.py",
                "output": "def validate_login(user, pwd): ...",
                "status": "success",
                "artifacts": [{"type": "file", "path": "auth/login.py"}],
            })

        # Simulate: apply the fix
        if "fix" not in skip:
            tool_calls.append({
                "name": "write_file",
                "capability_id": "write_file",
                "input": "auth/login.py [patched]",
                "output": "File written: auth/login.py",
                "status": "success",
                "artifacts": [{"type": "file", "path": "auth/login.py"}],
            })

        # Simulate: run tests
        if "test" not in skip:
            tool_calls.append({
                "name": "run_shell_command",
                "capability_id": "pytest_runner",
                "input": "pytest tests/test_auth.py -v",
                "output": "4 passed in 0.8s",
                "status": "success",
                "artifacts": [{"type": "test_report", "description": "4 tests passed"}],
            })

        # Docs intentionally SKIPPED in default demo to trigger drift detection
        # (unless "docs" is not in skip)
        if "docs" not in skip and "skip_docs" not in skip:
            pass  # intentionally skip docs for demo

        # PR intentionally SKIPPED in default demo
        # (unless explicitly included)
        if "include_pr" in (skip_steps or []):
            tool_calls.append({
                "name": "git_create_pr",
                "capability_id": "git_create_pr",
                "input": "gh pr create --title 'Fix login validation'",
                "output": "https://github.com/org/repo/pull/42",
                "status": "success",
                "artifacts": [
                    {"type": "pr", "url": "https://github.com/org/repo/pull/42",
                     "description": "PR #42: Fix login validation"}
                ],
            })

        summary = (
            f"ADK worker completed task: '{task_description[:80]}'. "
            f"Executed {len(tool_calls)} tool call(s). "
            "Tests passed. Claimed success."
        )

        return WorkerResult(
            trace_id=trace_id,
            agent_id=self.agent_id,
            claimed_success=True,
            summary=summary,
            tool_calls=tool_calls,
        )


# ---------------------------------------------------------------------------
# ADK Adapter
# ---------------------------------------------------------------------------


class ADKAdapter:
    """
    Adapts an ADK worker run into Aegis EvidenceEvents.

    Can wrap either a SimulatedADKWorker (for demo/testing) or a real
    ADK agent runner when `google-adk` is available.
    """

    def __init__(
        self,
        worker: SimulatedADKWorker | RealADKWorker | None = None,
        agent_id: str = "adk-worker",
        use_real_adk: bool = False,
    ) -> None:
        self.use_real_adk = use_real_adk
        if worker is not None:
            self._worker = worker
        elif use_real_adk and HAS_REAL_ADK:
            self._worker = RealADKWorker(agent_id=agent_id)
        else:
            self._worker = SimulatedADKWorker(agent_id=agent_id)
        self._agent_id = agent_id

    def run_and_collect(
        self,
        task_description: str,
        *,
        skip_steps: list[str] | None = None,
    ) -> tuple[WorkerResult, list[EvidenceEvent]]:
        """
        Run the worker and return both the WorkerResult and normalized events.

        Args:
            task_description: The task to run.
            skip_steps: Steps to skip (for demo drift injection).

        Returns:
            (WorkerResult, list[EvidenceEvent])
        """
        if hasattr(self._worker, "run_async"):
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import asyncio.runners
                    result = asyncio.run_coroutine_threadsafe(
                        self._worker.run_async(task_description), loop
                    ).result()
                else:
                    result = loop.run_until_complete(self._worker.run_async(task_description))
            except RuntimeError:
                result = asyncio.run(self._worker.run_async(task_description))
        else:
            result = self._worker.run(task_description, skip_steps=skip_steps)

        events = self._normalize(result)
        return result, events

    def _normalize(self, result: WorkerResult) -> list[EvidenceEvent]:
        """Convert a WorkerResult into Aegis EvidenceEvents."""
        adapter = TraceAdapter(
            agent_id=result.agent_id,
            trace_id=result.trace_id,
        )

        events: list[EvidenceEvent] = []

        # Normalize tool calls
        events.extend(adapter.from_tool_call_list(
            result.tool_calls, trace_id=result.trace_id
        ))

        # Normalize raw OpenInference spans if present
        if result.raw_spans:
            events.extend(adapter.from_openinference_spans(result.raw_spans))

        # Deduplicate events by event_id
        seen: set[str] = set()
        unique: list[EvidenceEvent] = []
        for ev in events:
            if ev.event_id not in seen:
                unique.append(ev)
                seen.add(ev.event_id)

        return unique
