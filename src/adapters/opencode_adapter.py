"""
Aegis OpenCode CLI Adapter

Normalizes OpenCode CLI execution traces, tool calls, and model calls
into Aegis EvidenceEvents.
"""

from __future__ import annotations

import os
import re
import uuid
import subprocess
from datetime import datetime, timezone
from typing import Any

from aegis.evidence_model import (
    Artifact,
    EvidenceEvent,
    EventStatus,
    EventType,
    NormalizedExecutionBundle,
    WorkerResult,
)
from .base_cli_adapter import BaseCLIAdapter


class OpenCodeAdapter(BaseCLIAdapter):
    """
    Adapter for OpenCode CLI agent runs.
    Parses OpenCode console agent outputs and MCP calls.
    """

    def __init__(self, agent_id: str = "opencode-agent", use_simulated: bool = False) -> None:
        super().__init__(agent_id=agent_id, binary_name="opencode", use_simulated=use_simulated)

    def run_and_collect(
        self,
        task_description: str,
        *,
        skip_steps: list[str] | None = None,
        **kwargs: Any,
    ) -> NormalizedExecutionBundle:
        trace_id = str(uuid.uuid4())
        
        # Check if we should use simulation
        binary_exists = False
        if not self.use_simulated:
            try:
                subprocess.run([self.binary_name, "--version"], capture_output=True, text=True, timeout=2)
                binary_exists = True
            except (FileNotFoundError, subprocess.SubprocessError):
                binary_exists = False

        if self.use_simulated or not binary_exists:
            worker_result, events = self._run_simulated(task_description, trace_id, skip_steps)
        else:
            # Run real CLI command
            worker_result, events = self._run_real(task_description, trace_id)

        return NormalizedExecutionBundle(worker_result=worker_result, events=events)

    def _run_real(self, task_description: str, trace_id: str) -> tuple[WorkerResult, list[EvidenceEvent]]:
        cmd = [self.binary_name, "agent", "run", task_description]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            
            events = self._parse_cli_output(stdout + "\n" + stderr, trace_id)
            
            claimed_success = result.returncode == 0
            summary = (
                f"OpenCode CLI run completed. Return code: {result.returncode}. "
                f"Parsed {len(events)} events from logs."
            )
            
            worker_result = WorkerResult(
                trace_id=trace_id,
                agent_id=self.agent_id,
                claimed_success=claimed_success,
                summary=summary,
                tool_calls=[],
                metadata={"stdout": stdout, "stderr": stderr},
            )
            return worker_result, events

        except subprocess.TimeoutExpired:
            timeout_event = EvidenceEvent(
                event_type=EventType.COMMAND,
                trace_id=trace_id,
                agent_id=self.agent_id,
                input_summary=" ".join(cmd),
                output_summary="",
                status=EventStatus.ERROR,
                error="OpenCode CLI command timed out",
            )
            worker_result = WorkerResult(
                trace_id=trace_id,
                agent_id=self.agent_id,
                claimed_success=False,
                summary="OpenCode CLI execution timed out",
                tool_calls=[],
            )
            return worker_result, [timeout_event]

    def _parse_cli_output(self, output: str, trace_id: str) -> list[EvidenceEvent]:
        events: list[EvidenceEvent] = []
        lines = output.splitlines()
        
        current_tool_name = None
        current_tool_args = None
        
        for line in lines:
            line_str = line.strip()
            
            # Parse OpenCode agent steps
            # Pattern: [Agent] Request: ...
            req_match = re.search(r"\[Agent\]\s*Request:\s*(.*)", line_str, re.I)
            if req_match:
                events.append(
                    EvidenceEvent(
                        event_type=EventType.SPAN,
                        trace_id=trace_id,
                        agent_id=self.agent_id,
                        input_summary="Task Request",
                        output_summary=req_match.group(1),
                        status=EventStatus.SUCCESS,
                    )
                )
                continue

            # Pattern: [Agent] Executing tool: <name> <args>
            tool_match = re.search(r"\[Agent\]\s*Executing tool:\s*(\w+)\s*(.*)", line_str, re.I)
            if tool_match:
                current_tool_name = tool_match.group(1)
                current_tool_args = tool_match.group(2)
                continue

            # Pattern: [Agent] Tool response: ...
            res_match = re.search(r"\[Agent\]\s*Tool response:\s*(.*)", line_str, re.I)
            if res_match and current_tool_name:
                response_content = res_match.group(1)
                
                ev_type = EventType.TOOL_CALL
                artifacts = []
                if "file" in current_tool_name.lower() or "write" in current_tool_name.lower():
                    ev_type = EventType.FILE_CHANGE
                    # Try to extract path
                    path_match = re.search(r"path=[\"']?([^\"'\s]+)[\"']?", current_tool_args or "")
                    if path_match:
                        artifacts.append(Artifact(type="file", path=path_match.group(1)))
                elif "test" in current_tool_name.lower() or (current_tool_args and "test" in current_tool_args.lower()):
                    ev_type = EventType.TEST_RESULT

                events.append(
                    EvidenceEvent(
                        event_type=ev_type,
                        trace_id=trace_id,
                        agent_id=self.agent_id,
                        capability_id=current_tool_name,
                        input_summary=f"{current_tool_name}({current_tool_args})",
                        output_summary=response_content,
                        status=EventStatus.SUCCESS,
                        artifacts=artifacts,
                    )
                )
                current_tool_name = None
                current_tool_args = None
                continue

        return events

    def _run_simulated(
        self, task_description: str, trace_id: str, skip_steps: list[str] | None = None
    ) -> tuple[WorkerResult, list[EvidenceEvent]]:
        skip = set(skip_steps or [])
        events: list[EvidenceEvent] = []

        # OpenCode span event
        events.append(
            EvidenceEvent(
                event_type=EventType.SPAN,
                trace_id=trace_id,
                agent_id=self.agent_id,
                input_summary="Task Request",
                output_summary=task_description,
                status=EventStatus.SUCCESS,
            )
        )

        if "read" not in skip:
            events.append(
                EvidenceEvent(
                    event_type=EventType.FILE_CHANGE,
                    trace_id=trace_id,
                    agent_id=self.agent_id,
                    capability_id="read_file",
                    input_summary="read_file path='auth/login.py'",
                    output_summary="def validate_login(user, pwd): ...",
                    status=EventStatus.SUCCESS,
                    artifacts=[Artifact(type="file", path="auth/login.py")],
                )
            )

        if "fix" not in skip:
            events.append(
                EvidenceEvent(
                    event_type=EventType.FILE_CHANGE,
                    trace_id=trace_id,
                    agent_id=self.agent_id,
                    capability_id="write_file",
                    input_summary="write_file path='auth/login.py' data='...'",
                    output_summary="File written: auth/login.py",
                    status=EventStatus.SUCCESS,
                    artifacts=[Artifact(type="file", path="auth/login.py")],
                )
            )

        if "test" not in skip:
            events.append(
                EvidenceEvent(
                    event_type=EventType.TEST_RESULT,
                    trace_id=trace_id,
                    agent_id=self.agent_id,
                    capability_id="pytest_runner",
                    input_summary="pytest_runner config='tests/test_auth.py'",
                    output_summary="4 passed in 0.8s",
                    status=EventStatus.SUCCESS,
                    artifacts=[Artifact(type="test_report", description="4 tests passed")],
                )
            )

        if "include_pr" in (skip_steps or []):
            events.append(
                EvidenceEvent(
                    event_type=EventType.EXTERNAL_ACTION,
                    trace_id=trace_id,
                    agent_id=self.agent_id,
                    capability_id="git_create_pr",
                    input_summary="git_create_pr title='Fix login validation'",
                    output_summary="https://github.com/org/repo/pull/42",
                    status=EventStatus.SUCCESS,
                    artifacts=[
                        Artifact(
                            type="pr",
                            url="https://github.com/org/repo/pull/42",
                            description="PR #42: Fix login validation",
                        )
                    ],
                )
            )

        summary = (
            f"Simulated OpenCode agent completed task: '{task_description[:80]}'. "
            f"Logged {len(events)} trace events."
        )

        worker_result = WorkerResult(
            trace_id=trace_id,
            agent_id=self.agent_id,
            claimed_success=True,
            summary=summary,
            tool_calls=[],
        )
        return worker_result, events
