"""
Aegis Base CLI Adapter

Provides the base abstraction class for agentic CLI adapters
(Gemini CLI, OpenCode, Antigravity CLI).
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from aegis.evidence_model import EvidenceEvent, EventStatus, EventType
from .adk_adapter import WorkerResult


class BaseCLIAdapter:
    """
    Abstract base adapter for agentic CLI wrappers.
    Normalizes command execution, parsing stdout/stderr, trace files,
    or session logs into Aegis structures.
    """

    def __init__(self, agent_id: str, binary_name: str, use_simulated: bool = False) -> None:
        self.agent_id = agent_id
        self.binary_name = binary_name
        self.use_simulated = use_simulated

    def run_and_collect(
        self,
        task_description: str,
        *,
        skip_steps: list[str] | None = None,
        **kwargs: Any,
    ) -> tuple[WorkerResult, list[EvidenceEvent]]:
        """
        Executes the agent CLI or simulates the run, then returns
        (WorkerResult, list[EvidenceEvent]).
        """
        raise NotImplementedError("Subclasses must implement run_and_collect")
