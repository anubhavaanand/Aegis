"""
Aegis Generic Wrapper Adapter (Stub)

Future generic subprocess wrapper for any agent runtime.
Wraps any command-line agent and captures stdout/stderr as evidence.

Currently a stub — ADK is the first-class integration.
"""

from __future__ import annotations

import subprocess
from typing import Any

from aegis.evidence_model import EvidenceEvent, EventStatus, EventType


class WrapperAdapter:
    """
    Generic wrapper adapter for command-line agent runtimes.

    Runs an agent command as a subprocess and wraps its stdout/stderr
    output as a single EvidenceEvent. For agents that produce structured
    output (JSON, YAML), the output can be parsed into richer events.

    Currently a stub — extend for specific runtimes as needed.
    """

    def __init__(self, agent_id: str = "wrapped-agent") -> None:
        self.agent_id = agent_id

    def run_command(
        self,
        command: list[str],
        trace_id: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> tuple[int, list[EvidenceEvent]]:
        """
        Run a command and return (exit_code, events).

        TODO: Parse structured output for richer event extraction.
        """
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            status = EventStatus.SUCCESS if result.returncode == 0 else EventStatus.FAILURE
            event = EvidenceEvent(
                event_type=EventType.COMMAND,
                trace_id=trace_id,
                agent_id=self.agent_id,
                input_summary=" ".join(command)[:500],
                output_summary=(result.stdout or result.stderr or "")[:500],
                status=status,
                error=result.stderr[:200] if result.returncode != 0 else None,
            )
            return result.returncode, [event]
        except subprocess.TimeoutExpired:
            event = EvidenceEvent(
                event_type=EventType.COMMAND,
                trace_id=trace_id,
                agent_id=self.agent_id,
                input_summary=" ".join(command)[:500],
                output_summary="",
                status=EventStatus.ERROR,
                error=f"Command timed out after {timeout}s",
            )
            return -1, [event]
