"""Tests for GeminiCLIAdapter, OpenCodeAdapter, and AntigravityAdapter."""

from __future__ import annotations

import pytest
from aegis.evidence_model import EventType, EventStatus
from adapters.gemini_cli_adapter import GeminiCLIAdapter
from adapters.opencode_adapter import OpenCodeAdapter
from adapters.antigravity_adapter import AntigravityAdapter


class TestGeminiCLIAdapter:
    def test_simulated_normalization(self):
        adapter = GeminiCLIAdapter(use_simulated=True)
        bundle = adapter.run_and_collect(
            "Refactor code and run tests",
            skip_steps=["read"],
            include_pr=["include_pr"]
        )
        res = bundle.worker_result
        events = bundle.events

        assert res.claimed_success is True
        assert res.agent_id == "gemini-cli-agent"
        
        # Checking events list
        assert len(events) > 0
        
        # First event is thinking span
        assert events[0].event_type == EventType.SPAN
        assert "Thinking step" in events[0].input_summary
        
        # Verify read is skipped, but write is there
        write_events = [e for e in events if e.capability_id == "write_file"]
        assert len(write_events) == 1
        assert write_events[0].event_type == EventType.FILE_CHANGE
        
        # Verify test runner
        test_events = [e for e in events if e.capability_id == "pytest_runner"]
        assert len(test_events) == 1
        assert test_events[0].event_type == EventType.TEST_RESULT

    def test_log_parser(self):
        adapter = GeminiCLIAdapter()
        logs = (
            "Cognitive step: Thinking about task\n"
            "Calling tool: read_file(path='auth.py')\n"
            "Tool Output: file contents\n"
            "Calling tool: run_shell_command(command='pytest tests/')\n"
            "Tool Output: 5 passed\n"
        )
        events = adapter._parse_cli_output(logs, "trace-123")
        
        assert len(events) == 3
        assert events[0].event_type == EventType.SPAN
        assert events[0].output_summary == "Thinking about task"
        
        assert events[1].event_type == EventType.FILE_CHANGE
        assert events[1].capability_id == "read_file"
        assert events[1].output_summary == "file contents"
        
        assert events[2].event_type == EventType.TEST_RESULT
        assert events[2].capability_id == "run_shell_command"
        assert events[2].output_summary == "5 passed"


class TestOpenCodeAdapter:
    def test_simulated_normalization(self):
        adapter = OpenCodeAdapter(use_simulated=True)
        bundle = adapter.run_and_collect("Analyze code")
        res = bundle.worker_result
        events = bundle.events
        
        assert res.claimed_success is True
        assert len(events) > 0
        assert events[0].event_type == EventType.SPAN
        assert events[1].capability_id == "read_file"

    def test_log_parser(self):
        adapter = OpenCodeAdapter()
        logs = (
            "[Agent] Request: Perform optimization\n"
            "[Agent] Executing tool: write_file path='main.py'\n"
            "[Agent] Tool response: File successfully updated\n"
        )
        events = adapter._parse_cli_output(logs, "trace-123")
        
        assert len(events) == 2
        assert events[0].event_type == EventType.SPAN
        assert events[0].output_summary == "Perform optimization"
        
        assert events[1].event_type == EventType.FILE_CHANGE
        assert events[1].capability_id == "write_file"
        assert events[1].output_summary == "File successfully updated"


class TestAntigravityAdapter:
    def test_simulated_normalization(self):
        adapter = AntigravityAdapter(use_simulated=True)
        bundle = adapter.run_and_collect("Repair bugs")
        res = bundle.worker_result
        events = bundle.events
        
        assert res.claimed_success is True
        assert len(events) > 0
        
    def test_log_parser(self):
        adapter = AntigravityAdapter()
        logs = (
            "[Engine] Intent: Run tests\n"
            "[Engine] Invoking: pytest_runner config='tests/'\n"
            "[Engine] Result: All tests passed\n"
        )
        events = adapter._parse_cli_output(logs, "trace-123")
        
        assert len(events) == 2
        assert events[0].event_type == EventType.SPAN
        assert events[0].output_summary == "Run tests"
        
        assert events[1].event_type == EventType.TEST_RESULT
        assert events[1].capability_id == "pytest_runner"
        assert events[1].output_summary == "All tests passed"

    def test_collect_events_compat(self):
        adapter = AntigravityAdapter()
        events = adapter.collect_events("session-123")
        assert len(events) > 0
