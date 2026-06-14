"""
Aegis Gemini CLI Adapter

Normalizes Gemini CLI execution traces, tool calls, and cognitive thinking spans
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


class GeminiCLIAdapter(BaseCLIAdapter):
    """
    Adapter for Gemini CLI agent runs.
    Parses live console outputs, tool call logs, and cognitive thinking steps.
    """

    def __init__(self, agent_id: str = "gemini-cli-agent", use_simulated: bool = False) -> None:
        super().__init__(agent_id=agent_id, binary_name="gemini-cli", use_simulated=use_simulated)

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
                # Check if gemini-cli is installed
                subprocess.run([self.binary_name, "--version"], capture_output=True, text=True, timeout=2)
                binary_exists = True
            except (FileNotFoundError, subprocess.SubprocessError):
                binary_exists = False

        if self.use_simulated or not binary_exists:
            worker_result, events = self._run_simulated(task_description, trace_id, skip_steps)
        else:
            # Run real CLI command as subprocess
            worker_result, events = self._run_real(task_description, trace_id)

        return NormalizedExecutionBundle(worker_result=worker_result, events=events)

    def _run_real(self, task_description: str, trace_id: str) -> tuple[WorkerResult, list[EvidenceEvent]]:
        cmd = [self.binary_name, "run", task_description]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            
            # Parse events from output logs
            events = self._parse_cli_output(stdout + "\n" + stderr, trace_id)
            
            claimed_success = result.returncode == 0
            summary = (
                f"Gemini CLI run completed. Return code: {result.returncode}. "
                f"Parsed {len(events)} events from logs."
            )
            
            worker_result = WorkerResult(
                trace_id=trace_id,
                agent_id=self.agent_id,
                claimed_success=claimed_success,
                summary=summary,
                tool_calls=[], # tool_calls already normalized as events
                metadata={"stdout": stdout, "stderr": stderr},
            )
            return worker_result, events

        except subprocess.TimeoutExpired as e:
            timeout_event = EvidenceEvent(
                event_type=EventType.COMMAND,
                trace_id=trace_id,
                agent_id=self.agent_id,
                input_summary=" ".join(cmd),
                output_summary="",
                status=EventStatus.ERROR,
                error="Gemini CLI command timed out",
            )
            worker_result = WorkerResult(
                trace_id=trace_id,
                agent_id=self.agent_id,
                claimed_success=False,
                summary="Gemini CLI execution timed out",
                tool_calls=[],
            )
            return worker_result, [timeout_event]

    def _parse_cli_output(self, output: str, trace_id: str) -> list[EvidenceEvent]:
        events: list[EvidenceEvent] = []
        lines = output.splitlines()
        
        current_tool_name = None
        current_tool_args = None
        current_tool_input_line = None
        
        for line in lines:
            line_str = line.strip()
            
            # 1. Parse thinking spans
            think_match = re.search(r"(?:Thinking|Cognitive step):\s*(.*)", line_str, re.I)
            if think_match:
                events.append(
                    EvidenceEvent(
                        event_type=EventType.SPAN,
                        trace_id=trace_id,
                        agent_id=self.agent_id,
                        input_summary="Thinking step",
                        output_summary=think_match.group(1),
                        status=EventStatus.SUCCESS,
                    )
                )
                continue

            # 2. Parse tool calls initiation
            tool_call_match = re.search(r"Calling tool:\s*(\w+)\((.*)\)", line_str, re.I)
            if tool_call_match:
                current_tool_name = tool_call_match.group(1)
                current_tool_args = tool_call_match.group(2)
                current_tool_input_line = line_str
                continue

            # 3. Parse tool outputs
            tool_output_match = re.search(r"Tool Output:\s*(.*)", line_str, re.I)
            if tool_output_match and current_tool_name:
                output_content = tool_output_match.group(1)
                
                # Determine event type based on tool name
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
                        output_summary=output_content,
                        status=EventStatus.SUCCESS,
                        artifacts=artifacts,
                    )
                )
                
                # Reset tool tracking
                current_tool_name = None
                current_tool_args = None
                current_tool_input_line = None
                continue

        return events

    def _run_simulated(
        self, task_description: str, trace_id: str, skip_steps: list[str] | None = None
    ) -> tuple[WorkerResult, list[EvidenceEvent]]:
        skip = set(skip_steps or [])
        events: list[EvidenceEvent] = []

        # Simulate Gemini cognitive steps
        events.append(
            EvidenceEvent(
                event_type=EventType.SPAN,
                trace_id=trace_id,
                agent_id=self.agent_id,
                input_summary="Thinking step",
                output_summary=f"Plan to execute request: {task_description}",
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
                    input_summary="read_file(path='auth/login.py')",
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
                    input_summary="write_file(path='auth/login.py', content='...')",
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
                    input_summary="run_shell_command(command='pytest tests/test_auth.py')",
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
                    input_summary="git_create_pr(title='Fix login validation')",
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
            f"Simulated Gemini CLI agent completed task: '{task_description[:80]}'. "
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
