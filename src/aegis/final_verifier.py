"""
Aegis Final Verifier

Runs after the corrective repair pass to verify that the repaired state
now satisfies the originally unmet criteria.

Updates the ReconciliationReport with the new status:
  - corrected   → all previously unmet criteria now satisfied
  - partial     → some criteria improved but not all
  - unresolved  → repair did not improve the state
"""

from __future__ import annotations

from .evidence_model import (
    EvidenceEvent,
    ReconciliationReport,
    ReconciliationStatus,
    TaskContract,
    UnmetCriterion,
)
from .reconciliation_engine import ReconciliationEngine


class FinalVerifier:
    """
    Re-runs reconciliation after a corrective repair pass.

    Compares the new report against the original to determine whether
    the repair succeeded, partially succeeded, or made no difference.
    """

    def __init__(self, engine: ReconciliationEngine) -> None:
        self._engine = engine

    def verify(
        self,
        contract: TaskContract,
        original_report: ReconciliationReport,
        repair_events: list[EvidenceEvent],
        all_events: list[EvidenceEvent],
    ) -> ReconciliationReport:
        """
        Run final verification.

        Args:
            contract: The original task contract.
            original_report: The report from before repair.
            repair_events: New evidence events from the repair run.
            all_events: Combined original + repair events.

        Returns:
            A new ReconciliationReport reflecting post-repair state.
        """
        # Re-run reconciliation with all combined evidence
        new_report = self._engine.reconcile(contract, all_events)

        # Upgrade status if improvement detected
        new_report = self._upgrade_status(original_report, new_report)

        return new_report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _upgrade_status(
        self,
        original: ReconciliationReport,
        updated: ReconciliationReport,
    ) -> ReconciliationReport:
        """
        If the new report has fewer unmet criteria than original,
        mark as 'corrected'. If the same, mark as 'unresolved'.
        """
        orig_unmet_ids = {c.criterion_id for c in original.unmet_criteria}
        new_unmet_ids = {c.criterion_id for c in updated.unmet_criteria}

        resolved = orig_unmet_ids - new_unmet_ids
        still_unmet = orig_unmet_ids & new_unmet_ids

        if not still_unmet and resolved:
            # All previously unmet are now resolved
            return updated.model_copy(update={"status": ReconciliationStatus.CORRECTED})
        elif resolved and still_unmet:
            # Partial improvement
            return updated.model_copy(update={"status": ReconciliationStatus.PARTIAL})
        elif not resolved:
            # No improvement
            return updated.model_copy(update={"status": ReconciliationStatus.FAILED})

        return updated

    def summary(
        self,
        original: ReconciliationReport,
        final: ReconciliationReport,
    ) -> dict[str, object]:
        """Return a diff summary between original and final reports."""
        orig_unmet = {c.criterion_id for c in original.unmet_criteria}
        final_unmet = {c.criterion_id for c in final.unmet_criteria}
        return {
            "original_status": original.status,
            "final_status": final.status,
            "criteria_resolved": list(orig_unmet - final_unmet),
            "criteria_still_unmet": list(orig_unmet & final_unmet),
            "new_issues": list(final_unmet - orig_unmet),
        }
