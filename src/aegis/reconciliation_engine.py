"""
Aegis Reconciliation Engine

The heart of Aegis. Compares a TaskContract against collected EvidenceEvents
and verified state to produce a ReconciliationReport.

Responsibilities:
  1. Classify reconciliation status (complete / partial / drifted / failed / suboptimal)
  2. Identify unmet and weakly-satisfied criteria
  3. Summarise evidence
  4. Delegate missed-capability detection to CapabilityAuditor

The engine is RUNTIME-AGNOSTIC: it only sees normalized EvidenceEvents
regardless of whether they came from ADK, Gemini CLI, or any other runtime.
"""

from __future__ import annotations

from .evidence_model import (
    EvidenceQuality,
    EvidenceEvent,
    EvidenceSummary,
    EventStatus,
    EventType,
    MissedCapability,
    ReconciliationReport,
    ReconciliationStatus,
    TaskContract,
    UnmetCriterion,
)
from .state_verifier import StateVerifier, VerificationResult
from .semantic_verifier import SemanticVerifier


# ---------------------------------------------------------------------------
# Drift Classifier (isolated — would be capability_auditor's sibling)
# ---------------------------------------------------------------------------


class DriftClassifier:
    """
    Classifies reconciliation status from verification results.

    Kept as an explicit sub-component of the engine so the status decision
    logic is auditable without making the engine a blob.
    """

    def classify(
        self,
        results: list[VerificationResult],
        missed_capabilities: list[MissedCapability],
    ) -> ReconciliationStatus:
        if not results:
            return ReconciliationStatus.FAILED

        required_results = [r for r in results if r.criterion_id]  # all for now
        failed = [r for r in required_results if not r.passed]
        weak = [
            r for r in required_results
            if r.passed and r.quality == EvidenceQuality.WEAK
        ]

        if not failed and not weak:
            if missed_capabilities:
                return ReconciliationStatus.SUBOPTIMAL
            return ReconciliationStatus.COMPLETE

        if failed and len(failed) == len(required_results):
            return ReconciliationStatus.FAILED

        if failed:
            # Some passed, some failed → drift
            return ReconciliationStatus.DRIFTED

        if weak:
            return ReconciliationStatus.PARTIAL

        return ReconciliationStatus.COMPLETE


# ---------------------------------------------------------------------------
# ReconciliationEngine
# ---------------------------------------------------------------------------


class ReconciliationEngine:
    """
    Reconciles a TaskContract against execution evidence.

    Usage::

        engine = ReconciliationEngine(state_verifier=StateVerifier(workspace="."))
        report = engine.reconcile(contract, events)
    """

    def __init__(
        self,
        state_verifier: StateVerifier | None = None,
        capability_auditor: object | None = None,
        semantic_verifier: SemanticVerifier | None = None,
    ) -> None:
        self._verifier = state_verifier or StateVerifier()
        self._auditor = capability_auditor  # injected; optional for now
        self._semantic_verifier = semantic_verifier or SemanticVerifier()
        self._classifier = DriftClassifier()

    def reconcile(
        self,
        contract: TaskContract,
        events: list[EvidenceEvent],
    ) -> ReconciliationReport:
        """
        Core reconciliation: contract vs evidence.

        Returns a ReconciliationReport with status, unmet criteria,
        weak evidence, missed capabilities, and repair recommendations.
        """
        # 1. Verify each criterion against real state
        verification_results = self._verifier.verify_all(
            contract.success_criteria, events
        )

        # 2. Build evidence summary
        summary = self._build_summary(events)

        # 3. Separate unmet from weakly-met criteria
        unmet = self._extract_unmet(contract, verification_results)
        weak = self._extract_weak(contract, verification_results)

        # 4. Missed capability audit (delegate to auditor if available)
        missed: list[MissedCapability] = []
        if self._auditor:
            missed = self._auditor.audit(contract, events, verification_results)  # type: ignore[union-attr]

        # 5. Classify overall status
        status = self._classifier.classify(verification_results, missed)

        report = ReconciliationReport(
            task_id=contract.task_id,
            status=status,
            unmet_criteria=unmet,
            weak_evidence=weak,
            missed_capabilities=missed,
            evidence_summary=summary,
        )

        semantic_result = self._semantic_verifier.verify(contract, events, report)
        report.semantic_verification = semantic_result

        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_unmet(
        self,
        contract: TaskContract,
        results: list[VerificationResult],
    ) -> list[UnmetCriterion]:
        unmet = []
        result_map = {r.criterion_id: r for r in results}
        for criterion in contract.success_criteria:
            r = result_map.get(criterion.criterion_id)
            if r and not r.passed:
                unmet.append(
                    UnmetCriterion(
                        criterion_id=criterion.criterion_id,
                        description=criterion.description,
                        evidence_quality=EvidenceQuality(r.quality),
                        notes=r.notes,
                    )
                )
        return unmet

    def _extract_weak(
        self,
        contract: TaskContract,
        results: list[VerificationResult],
    ) -> list[UnmetCriterion]:
        weak = []
        result_map = {r.criterion_id: r for r in results}
        for criterion in contract.success_criteria:
            r = result_map.get(criterion.criterion_id)
            if r and r.passed and r.quality == EvidenceQuality.WEAK:
                weak.append(
                    UnmetCriterion(
                        criterion_id=criterion.criterion_id,
                        description=criterion.description,
                        evidence_quality=EvidenceQuality.WEAK,
                        notes=r.notes,
                    )
                )
        return weak

    def _build_summary(self, events: list[EvidenceEvent]) -> EvidenceSummary:
        summary = EvidenceSummary(
            total_events=len(events),
            successful_events=sum(
                1 for e in events if e.status == EventStatus.SUCCESS
            ),
            failed_events=sum(
                1 for e in events if e.status == EventStatus.FAILURE
            ),
            tool_calls=sum(
                1 for e in events if e.event_type == EventType.TOOL_CALL
            ),
            model_calls=sum(
                1 for e in events if e.event_type == EventType.MODEL_CALL
            ),
            file_changes=sum(
                1 for e in events if e.event_type == EventType.FILE_CHANGE
            ),
            test_results=sum(
                1 for e in events if e.event_type == EventType.TEST_RESULT
            ),
            capabilities_used=list({
                e.capability_id for e in events if e.capability_id
            }),
            traces=list({e.trace_id for e in events}),
        )
        return summary
