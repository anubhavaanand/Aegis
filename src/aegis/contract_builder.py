"""
Aegis Contract Builder

Converts a raw user request into a structured TaskContract with inferred
success criteria, constraints, and risk assessment.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from .evidence_model import (
    RiskLevel,
    SuccessCriterion,
    TaskContract,
    VerifierType,
)

# Pydantic models for Gemini structured output schemas
class LLMSuccessCriterion(BaseModel):
    description: str
    verifier_type: str
    verifier_config: dict[str, Any] = {}
    required: bool = True

class LLMTaskContract(BaseModel):
    goal: str
    constraints: list[str] = []
    success_criteria: list[LLMSuccessCriterion]
    expected_state_changes: list[str] = []
    risk_level: str
    approval_required_for: list[str] = []

# ---------------------------------------------------------------------------
# Heuristic keyword maps
# ---------------------------------------------------------------------------

_CRITERION_PATTERNS: list[tuple[re.Pattern, str, VerifierType, dict[str, Any]]] = [
    (
        re.compile(r"\b(fix|patch|resolve|debug|repair)\b", re.I),
        "Bug is fixed: source code diff exists with the change",
        VerifierType.FILE_DIFF,
        {},
    ),
    (
        re.compile(r"\b(test|tests|pytest|unittest|spec)\b", re.I),
        "Tests pass: all relevant tests complete without failure",
        VerifierType.TEST_PASS,
        {},
    ),
    (
        re.compile(r"\b(doc|docs|documentation|readme|changelog|docstring)\b", re.I),
        "Documentation updated: relevant doc sections exist and are current",
        VerifierType.DOC_SECTION,
        {},
    ),
    (
        re.compile(r"\b(pr|pull.request|merge.request|open.*pr|create.*pr)\b", re.I),
        "Pull request created or exists in the repository",
        VerifierType.PR_EXISTS,
        {},
    ),
    (
        re.compile(r"\b(deploy|release|publish|ship)\b", re.I),
        "Deployment or release action completed successfully",
        VerifierType.COMMAND_OUTPUT,
        {"expected_pattern": "success|deployed|released"},
    ),
    (
        re.compile(r"\b(refactor|clean|migrate)\b", re.I),
        "Code changes exist and tests still pass after refactoring",
        VerifierType.FILE_DIFF,
        {},
    ),
]

_RISK_KEYWORDS: dict[RiskLevel, list[str]] = {
    RiskLevel.CRITICAL: ["production", "live", "deploy", "database", "credential", "secret", "auth"],
    RiskLevel.HIGH: ["pr", "merge", "release", "delete", "remove", "drop"],
    RiskLevel.MEDIUM: ["refactor", "migrate", "update", "patch", "fix"],
    RiskLevel.LOW: ["test", "doc", "readme", "comment", "format", "lint"],
}

_APPROVAL_TRIGGERS: list[str] = ["deploy", "release", "delete", "merge", "production", "pr"]


# ---------------------------------------------------------------------------
# ContractBuilder
# ---------------------------------------------------------------------------


class ContractBuilder:
    """
    Converts a user request string into a validated TaskContract.

    Uses heuristic pattern matching to infer:
    - Goal (distilled intent)
    - Success criteria (with verifier types)
    - Risk level
    - Approval triggers
    - Expected state changes

    For production use, this can be backed by an LLM call. For MVP it uses
    fast deterministic heuristics so the demo is always runnable offline.
    """

    def build(self, user_request: str, *, extra_criteria: list[dict] | None = None) -> TaskContract:
        """
        Build a TaskContract from a user request.

        Args:
            user_request: The raw user request string.
            extra_criteria: Optional additional criteria to inject.

        Returns:
            A validated TaskContract.
        """
        mode = os.environ.get("AEGIS_CONTRACT_MODE", "heuristic").lower()
        if mode == "llm":
            try:
                return self._build_llm(user_request, extra_criteria=extra_criteria)
            except Exception as e:
                print(f"[aegis.warn] LLM contract building failed ({e}). Falling back to heuristic builder.")

        # Fallback / Default Heuristic Builder
        goal = self._extract_goal(user_request)
        criteria = self._infer_criteria(user_request)
        if extra_criteria:
            for c in extra_criteria:
                criteria.append(
                    SuccessCriterion(
                        description=c["description"],
                        verifier_type=c.get("verifier_type", VerifierType.MANUAL),
                        verifier_config=c.get("verifier_config", {}),
                        required=c.get("required", True),
                    )
                )
        # Guarantee at least one criterion
        if not criteria:
            criteria.append(
                SuccessCriterion(
                    description="Task completed without errors",
                    verifier_type=VerifierType.MANUAL,
                )
            )

        risk = self._assess_risk(user_request)
        approvals = self._approval_triggers(user_request)
        changes = self._expected_changes(user_request)

        return TaskContract(
            user_request=user_request,
            goal=goal,
            success_criteria=criteria,
            expected_state_changes=changes,
            risk_level=risk,
            approval_required_for=approvals,
        )

    def _build_llm(self, user_request: str, *, extra_criteria: list[dict] | None = None) -> TaskContract:
        """
        Build a TaskContract using the Gemini LLM with structured output.
        """
        # Lazy imports so we don't depend on Google GenAI SDK unless LLM mode is active
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is not set.")

        client = genai.Client()

        prompt = f"""
You are an expert software agent coordinator.
Your task is to analyze the following user request and generate a structured verification contract (TaskContract).
This contract defines the goal, constraints, expected state changes, risk level, and verifiable success criteria for a software task.

Success criteria should map to one of these verifier types:
- `file_diff`: If the task requires modifying code/files (e.g. "fix bug", "refactor").
- `test_pass`: If the task requires running tests (e.g. "run pytest", "ensure tests pass").
- `doc_section`: If the task requires updating documentation files (e.g. "update readme", "add docstrings").
- `pr_exists`: If the task requires opening a pull request (e.g. "create PR").
- `command_output`: If the task requires running a shell command and checking for success.
- `manual`: For tasks that can only be verified manually.

Risk level must be one of: `low`, `medium`, `high`, `critical`.
Include trigger terms in `approval_required_for` if the request mentions risky operations like deleting, deploying, releasing, or dropping databases.

User Request:
"{user_request}"
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LLMTaskContract,
                temperature=0.1,
            ),
        )

        data = json.loads(response.text)

        # Map risk level to Enum
        risk_str = data.get("risk_level", "medium").lower()
        if risk_str == "low":
            risk = RiskLevel.LOW
        elif risk_str == "high":
            risk = RiskLevel.HIGH
        elif risk_str == "critical":
            risk = RiskLevel.CRITICAL
        else:
            risk = RiskLevel.MEDIUM

        criteria = []
        for c in data.get("success_criteria", []):
            criteria.append(
                SuccessCriterion(
                    description=c.get("description", "Criterion"),
                    verifier_type=c.get("verifier_type", VerifierType.MANUAL),
                    verifier_config=c.get("verifier_config", {}),
                    required=c.get("required", True),
                )
            )

        if extra_criteria:
            for c in extra_criteria:
                criteria.append(
                    SuccessCriterion(
                        description=c["description"],
                        verifier_type=c.get("verifier_type", VerifierType.MANUAL),
                        verifier_config=c.get("verifier_config", {}),
                        required=c.get("required", True),
                    )
                )

        # Guarantee at least one criterion
        if not criteria:
            criteria.append(
                SuccessCriterion(
                    description="Task completed without errors",
                    verifier_type=VerifierType.MANUAL,
                )
            )

        return TaskContract(
            user_request=user_request,
            goal=data.get("goal", user_request),
            constraints=data.get("constraints", []),
            success_criteria=criteria,
            expected_state_changes=data.get("expected_state_changes", []),
            risk_level=risk,
            approval_required_for=data.get("approval_required_for", []),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_goal(self, request: str) -> str:
        """Distil the user request to a concise goal statement."""
        # Remove filler phrases and trim
        goal = request.strip()
        for prefix in ["please ", "can you ", "i want you to ", "i need you to "]:
            if goal.lower().startswith(prefix):
                goal = goal[len(prefix):]
        # Capitalise and truncate
        goal = goal[:300]
        return goal[0].upper() + goal[1:] if goal else request

    def _infer_criteria(self, request: str) -> list[SuccessCriterion]:
        """Map keyword patterns in the request to verifiable success criteria."""
        seen_types: set[VerifierType] = set()
        criteria: list[SuccessCriterion] = []
        for pattern, description, verifier_type, config in _CRITERION_PATTERNS:
            if pattern.search(request) and verifier_type not in seen_types:
                criteria.append(
                    SuccessCriterion(
                        description=description,
                        verifier_type=verifier_type,
                        verifier_config=config,
                    )
                )
                seen_types.add(verifier_type)
        return criteria

    def _assess_risk(self, request: str) -> RiskLevel:
        """Score the risk level of a request."""
        lower = request.lower()
        for level in [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW]:
            if any(kw in lower for kw in _RISK_KEYWORDS[level]):
                return level
        return RiskLevel.LOW

    def _approval_triggers(self, request: str) -> list[str]:
        lower = request.lower()
        return [kw for kw in _APPROVAL_TRIGGERS if kw in lower]

    def _expected_changes(self, request: str) -> list[str]:
        changes: list[str] = []
        lower = request.lower()
        if any(w in lower for w in ["fix", "patch", "debug", "repair"]):
            changes.append("Source files modified")
        if any(w in lower for w in ["test", "tests"]):
            changes.append("Test files updated or added")
        if any(w in lower for w in ["doc", "docs", "documentation", "readme"]):
            changes.append("Documentation updated")
        if any(w in lower for w in ["pr", "pull request"]):
            changes.append("Pull request opened")
        return changes
