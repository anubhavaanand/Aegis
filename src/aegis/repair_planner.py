"""
Aegis Repair Planner

Generates the smallest useful corrective sub-plan targeting only unmet
criteria or clearly suboptimal execution steps.

Rules:
  - Do NOT rerun everything
  - Only target unmet criteria or suboptimal steps
  - Prefer specialized capabilities from the registry
  - Mark each repair step as REQUIRED or OPTIONAL
  - Never include steps that would duplicate successful evidence
"""

from __future__ import annotations

from .capability_registry import CapabilityRegistry
from .evidence_model import (
    MissedCapability,
    ReconciliationReport,
    ReconciliationStatus,
    RepairPriority,
    RepairStep,
    UnmetCriterion,
    VerifierType,
)

# Verifier type → default repair action template
_REPAIR_TEMPLATES: dict[str, tuple[str, str]] = {
    VerifierType.FILE_DIFF.value: (
        "Apply the missing code change",
        "Identify the file(s) that need updating, apply the fix, and commit the change.",
    ),
    VerifierType.TEST_PASS.value: (
        "Run the test suite",
        "Execute the full test suite (pytest / equivalent) and ensure all tests pass.",
    ),
    VerifierType.DOC_SECTION.value: (
        "Update documentation",
        "Update the relevant documentation section to reflect the completed change.",
    ),
    VerifierType.PR_EXISTS.value: (
        "Create pull request",
        "Open a pull request with the committed changes for review.",
    ),
    VerifierType.COMMAND_OUTPUT.value: (
        "Re-run required command",
        "Execute the command and verify the output matches the expected pattern.",
    ),
    VerifierType.MANUAL.value: (
        "Manual verification required",
        "A human must verify this criterion — no automated repair available.",
    ),
}


class RepairPlanner:
    """
    Generates minimal corrective sub-plans from a ReconciliationReport.

    Only generates repair steps for UNMET or WEAKLY-MET criteria.
    Steps for successfully verified criteria are never included.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def plan(
        self,
        report: ReconciliationReport,
        contract_criteria_map: dict[str, object],
    ) -> list[RepairStep]:
        """
        Generate a list of RepairSteps from a reconciliation report.

        Args:
            report: The ReconciliationReport from the engine.
            contract_criteria_map: Dict of criterion_id → SuccessCriterion
                                   (for verifier_type lookup).

        Returns:
            Minimal list of RepairStep objects, ordered by priority.
        """
        if report.status == ReconciliationStatus.COMPLETE:
            return []  # Nothing to repair

        steps: list[RepairStep] = []

        # 1. Required repairs for fully unmet criteria
        for unmet in report.unmet_criteria:
            step = self._repair_for_criterion(
                unmet,
                contract_criteria_map,
                priority=RepairPriority.REQUIRED,
            )
            if step:
                steps.append(step)

        # 2. Optional repairs for weakly-met criteria
        for weak in report.weak_evidence:
            step = self._repair_for_criterion(
                weak,
                contract_criteria_map,
                priority=RepairPriority.OPTIONAL,
            )
            if step:
                steps.append(step)

        # 3. Optional: use better capabilities for missed-capability findings
        for missed in report.missed_capabilities:
            step = self._repair_for_missed(missed)
            if step:
                steps.append(step)

        # Sort: REQUIRED first, then OPTIONAL
        steps.sort(
            key=lambda s: 0 if s.priority == RepairPriority.REQUIRED else 1
        )

        return steps

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _repair_for_criterion(
        self,
        criterion: UnmetCriterion,
        criteria_map: dict[str, object],
        priority: RepairPriority,
    ) -> RepairStep | None:
        source = criteria_map.get(criterion.criterion_id)
        if not source:
            return None

        verifier_type = str(getattr(source, "verifier_type", VerifierType.MANUAL.value))
        template = _REPAIR_TEMPLATES.get(
            verifier_type, _REPAIR_TEMPLATES[VerifierType.MANUAL.value]
        )
        action_name, action_desc = template

        # Look for a registered capability that can handle this
        cap = self._find_best_capability(verifier_type)

        return RepairStep(
            description=f"{action_name}: {criterion.description}",
            targets_criterion=criterion.criterion_id,
            capability_id=cap.capability_id if cap else None,
            action=action_desc,
            priority=priority,
            metadata={"verifier_type": verifier_type, "evidence_quality": criterion.evidence_quality},
        )

    def _repair_for_missed(
        self,
        missed: MissedCapability,
    ) -> RepairStep | None:
        cap = self._registry.get(missed.capability_id)
        if not cap:
            return None
        return RepairStep(
            description=f"Use {cap.name} for better outcome",
            targets_criterion=missed.metadata.get("criterion_id", ""),
            capability_id=cap.capability_id,
            action=(
                f"Re-execute using '{cap.name}' ({cap.description}) "
                f"which is the preferred capability for this use case."
            ),
            priority=RepairPriority.OPTIONAL,
            metadata={"missed_capability": missed.name, "impact": missed.impact},
        )

    def _find_best_capability(
        self, verifier_type: str
    ) -> object | None:
        from .evidence_model import VerifierType as VT
        tag_map: dict[str, list[str]] = {
            VT.FILE_DIFF.value: ["write", "file"],
            VT.TEST_PASS.value: ["test", "pytest"],
            VT.DOC_SECTION.value: ["docs"],
            VT.PR_EXISTS.value: ["pr", "github"],
            VT.COMMAND_OUTPUT.value: ["shell", "command"],
        }
        tags = tag_map.get(verifier_type, [])
        if not tags:
            return None
        candidates = self._registry.by_tags(tags)
        # Prefer lower risk
        candidates.sort(key=lambda c: ["low", "medium", "high", "critical"].index(
            c.risk_level if isinstance(c.risk_level, str) else c.risk_level.value
        ))
        return candidates[0] if candidates else None
