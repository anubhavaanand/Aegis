"""
Aegis Evidence Model — Pydantic v2 schemas for all runtime evidence.

This module is the single source of truth for all data structures that flow
through Aegis: task contracts, evidence events (aligned with OpenInference/
Phoenix span model), capability records, and reconciliation reports.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    FILE_CHANGE = "file_change"
    TEST_RESULT = "test_result"
    COMMAND = "command"
    EXTERNAL_ACTION = "external_action"
    SPAN = "span"


class EventStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    PARTIAL = "partial"
    ERROR = "error"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReconciliationStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    DRIFTED = "drifted"
    FAILED = "failed"
    SUBOPTIMAL = "suboptimal"
    CORRECTED = "corrected"


class EvidenceQuality(str, Enum):
    STRONG = "strong"
    WEAK = "weak"
    ABSENT = "absent"


class CapabilityType(str, Enum):
    LOCAL_TOOL = "local_tool"
    SHELL_COMMAND = "shell_command"
    MCP_TOOL = "mcp_tool"
    SKILL = "skill"
    PLUGIN = "plugin"
    WORKFLOW = "workflow"
    SUBAGENT = "subagent"
    TEMPLATE = "template"
    EXTERNAL_API = "external_api"


class VerifierType(str, Enum):
    FILE_DIFF = "file_diff"
    TEST_PASS = "test_pass"
    DOC_SECTION = "doc_section"
    PR_EXISTS = "pr_exists"
    COMMAND_OUTPUT = "command_output"
    MANUAL = "manual"


class RepairPriority(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class MissedCapabilityImpact(str, Enum):
    CRITICAL = "critical"
    SIGNIFICANT = "significant"
    MINOR = "minor"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Task Contract
# ---------------------------------------------------------------------------


class SuccessCriterion(BaseModel):
    """A single verifiable success criterion for a task."""

    criterion_id: str = Field(default_factory=_new_id)
    description: str
    verifier_type: VerifierType
    verifier_config: dict[str, Any] = Field(default_factory=dict)
    required: bool = True

    model_config = {"use_enum_values": True}


class TaskContract(BaseModel):
    """
    Structured contract representing a user task and its verification criteria.

    Created by ContractBuilder from a raw user request. Every downstream
    component works from this contract — the reconciliation engine compares
    actual execution evidence against it.
    """

    task_id: str = Field(default_factory=_new_id)
    user_request: str
    goal: str
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    expected_state_changes: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    approval_required_for: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    tags: list[str] = Field(default_factory=list)

    model_config = {"use_enum_values": True}

    @field_validator("success_criteria")
    @classmethod
    def must_have_criteria(cls, v: list[SuccessCriterion]) -> list[SuccessCriterion]:
        if not v:
            raise ValueError("A TaskContract must have at least one success criterion.")
        return v


# ---------------------------------------------------------------------------
# Capability Registry Entry
# ---------------------------------------------------------------------------


class Capability(BaseModel):
    """A normalized capability entry in the Aegis registry."""

    capability_id: str = Field(default_factory=_new_id)
    name: str
    type: CapabilityType
    source: str
    description: str
    preferred_use_cases: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Evidence Event (OpenInference / Phoenix span-aligned)
# ---------------------------------------------------------------------------


class Artifact(BaseModel):
    """An artifact produced or referenced by an evidence event."""

    type: str  # e.g. "file", "pr", "test_report", "url"
    path: str | None = None
    url: str | None = None
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    """Token usage for model call events."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @model_validator(mode="after")
    def compute_total(self) -> TokenUsage:
        if self.total_tokens == 0 and (self.input_tokens or self.output_tokens):
            object.__setattr__(self, "total_tokens", self.input_tokens + self.output_tokens)
        return self


class EvidenceEvent(BaseModel):
    """
    A normalized evidence event from any agent runtime.

    Aligned with the OpenInference semantic conventions and Phoenix span model.
    Every adapter (ADK, Antigravity, generic wrapper) normalizes its trace
    output into this format before passing to the reconciliation engine.
    """

    event_id: str = Field(default_factory=_new_id)
    event_type: EventType
    trace_id: str
    span_id: str = Field(default_factory=_new_id)
    parent_span_id: str | None = None

    # Identity
    agent_id: str
    capability_id: str | None = None

    # Content
    input_summary: str = ""
    output_summary: str = ""

    # Outcome
    status: EventStatus
    artifacts: list[Artifact] = Field(default_factory=list)
    error: str | None = None

    # Timing
    timestamp: datetime = Field(default_factory=_now)
    end_timestamp: datetime | None = None
    latency_ms: int | None = None

    # Model-specific
    token_usage: TokenUsage | None = None

    # Catch-all
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}

    @model_validator(mode="after")
    def compute_latency(self) -> EvidenceEvent:
        if self.latency_ms is None and self.end_timestamp and self.timestamp:
            delta = (self.end_timestamp - self.timestamp).total_seconds()
            object.__setattr__(self, "latency_ms", int(delta * 1000))
        return self


# ---------------------------------------------------------------------------
# Reconciliation Report
# ---------------------------------------------------------------------------


class UnmetCriterion(BaseModel):
    """A success criterion that was not satisfactorily met."""

    criterion_id: str
    description: str
    evidence_quality: EvidenceQuality
    notes: str = ""


class MissedCapability(BaseModel):
    """A capability that was available but not used, potentially suboptimally."""

    capability_id: str
    name: str
    reason: str  # Why it should have been used
    impact: MissedCapabilityImpact
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


class RepairStep(BaseModel):
    """A single step in a corrective repair plan."""

    repair_id: str = Field(default_factory=_new_id)
    description: str
    targets_criterion: str  # criterion_id this repair addresses
    capability_id: str | None = None
    action: str = ""  # Human-readable action description
    priority: RepairPriority = RepairPriority.REQUIRED
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


class EvidenceSummary(BaseModel):
    """Summary statistics over the collected evidence events."""

    total_events: int = 0
    successful_events: int = 0
    failed_events: int = 0
    tool_calls: int = 0
    model_calls: int = 0
    file_changes: int = 0
    test_results: int = 0
    capabilities_used: list[str] = Field(default_factory=list)
    traces: list[str] = Field(default_factory=list)


class ReconciliationReport(BaseModel):
    """
    The complete output of the Aegis reconciliation engine.

    Produced by comparing a TaskContract against collected EvidenceEvents.
    Drives the approval gate and repair planning.
    """

    task_id: str
    status: ReconciliationStatus
    unmet_criteria: list[UnmetCriterion] = Field(default_factory=list)
    weak_evidence: list[UnmetCriterion] = Field(default_factory=list)
    missed_capabilities: list[MissedCapability] = Field(default_factory=list)
    recommended_repairs: list[RepairStep] = Field(default_factory=list)
    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)
    created_at: datetime = Field(default_factory=_now)

    model_config = {"use_enum_values": True}

    @property
    def is_successful(self) -> bool:
        return self.status in (ReconciliationStatus.COMPLETE, ReconciliationStatus.CORRECTED)

    @property
    def needs_repair(self) -> bool:
        return bool(self.unmet_criteria or self.weak_evidence)

    @property
    def has_missed_capabilities(self) -> bool:
        return bool(self.missed_capabilities)
