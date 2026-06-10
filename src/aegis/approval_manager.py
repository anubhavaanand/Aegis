"""
Aegis Approval Manager

Presents the drift report and proposed repair plan to the user and
waits for explicit approval or rejection before any repair runs.

This is the blocking gate in the Aegis loop:
  reconcile → approval_manager → (if approved) repair → final_verify

The approval screen shows:
  - Original task
  - Current reconciliation status
  - Unmet criteria
  - Evidence summary
  - Proposed repair steps
  - Missed capabilities (if any)
"""

from __future__ import annotations

import sys
from typing import Callable

from .evidence_model import ReconciliationReport, RepairStep, TaskContract


class ApprovalDecision:
    """The result of an approval gate interaction."""

    def __init__(
        self,
        approved: bool,
        selected_steps: list[RepairStep],
        notes: str = "",
    ) -> None:
        self.approved = approved
        self.selected_steps = selected_steps
        self.notes = notes

    def __bool__(self) -> bool:
        return self.approved


class ApprovalManager:
    """
    Manages the user approval gate before any corrective repair runs.

    In terminal mode, renders a Rich-formatted drift report and prompts
    for user confirmation. Can be given a custom prompt_fn for testing.
    """

    def __init__(
        self,
        prompt_fn: Callable[[str], str] | None = None,
        ui: object | None = None,
    ) -> None:
        self._prompt = prompt_fn or self._default_prompt
        self._ui = ui  # optional TerminalUI injection

    def request_approval(
        self,
        contract: TaskContract,
        report: ReconciliationReport,
        repair_steps: list[RepairStep],
    ) -> ApprovalDecision:
        """
        Show the drift report and proposed repair plan, then wait for approval.

        Returns an ApprovalDecision with approved=True if the user approves.
        """
        if self._ui:
            self._ui.render_approval_screen(contract, report, repair_steps)  # type: ignore[union-attr]
        else:
            self._render_plain(contract, report, repair_steps)

        if not repair_steps:
            print("\n[No repair steps proposed — nothing to approve.]")
            return ApprovalDecision(approved=False, selected_steps=[], notes="Nothing to repair")

        answer = self._prompt(
            "\nApprove repair plan? [y=yes / n=no / s=select steps]: "
        ).strip().lower()

        if answer in ("y", "yes"):
            return ApprovalDecision(
                approved=True, selected_steps=repair_steps, notes="User approved all steps"
            )

        if answer in ("s", "select"):
            selected = self._select_steps(repair_steps)
            if selected:
                return ApprovalDecision(
                    approved=True, selected_steps=selected, notes="User selected specific steps"
                )
            return ApprovalDecision(approved=False, selected_steps=[], notes="No steps selected")

        return ApprovalDecision(
            approved=False, selected_steps=[], notes="User rejected repair plan"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _render_plain(
        self,
        contract: TaskContract,
        report: ReconciliationReport,
        steps: list[RepairStep],
    ) -> None:
        print("\n" + "=" * 70)
        print("  AEGIS DRIFT REPORT")
        print("=" * 70)
        print(f"  Task   : {contract.goal}")
        print(f"  Status : {report.status}")
        print()

        if report.unmet_criteria:
            print("UNMET CRITERIA:")
            for c in report.unmet_criteria:
                print(f"  ✗ {c.description}")
                print(f"    Evidence quality: {c.evidence_quality} | {c.notes}")
        if report.weak_evidence:
            print("\nWEAK EVIDENCE:")
            for c in report.weak_evidence:
                print(f"  ⚠ {c.description}")
                print(f"    {c.notes}")
        if report.missed_capabilities:
            print("\nMISSED CAPABILITIES:")
            for m in report.missed_capabilities:
                print(f"  ● {m.name} [{m.impact}]: {m.reason}")

        print(f"\nEVIDENCE: {report.evidence_summary.total_events} events | "
              f"{report.evidence_summary.tool_calls} tool calls | "
              f"{report.evidence_summary.file_changes} file changes | "
              f"{report.evidence_summary.test_results} test results")

        if steps:
            print("\nPROPOSED REPAIR STEPS:")
            for i, step in enumerate(steps, 1):
                tag = "[REQUIRED]" if step.priority == "required" else "[OPTIONAL]"
                print(f"  {i}. {tag} {step.description}")
                print(f"     → {step.action}")
        print("=" * 70)

    def _select_steps(
        self, steps: list[RepairStep]
    ) -> list[RepairStep]:
        print("\nEnter step numbers to include (comma-separated), e.g. '1,3':")
        for i, step in enumerate(steps, 1):
            print(f"  {i}. {step.description}")
        raw = self._prompt("Steps: ").strip()
        try:
            indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip()]
            return [steps[i] for i in indices if 0 <= i < len(steps)]
        except (ValueError, IndexError):
            return []

    @staticmethod
    def _default_prompt(message: str) -> str:
        try:
            return input(message)
        except (EOFError, KeyboardInterrupt):
            return "n"
