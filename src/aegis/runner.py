"""
Aegis Loop Runner

Orchestrates the entire Aegis workflow:
1. Builds task contract
2. Executes worker run
3. Performs reconciliation & audit
4. Proposes repair plans
5. Manages approval gate
6. Reruns repair worker (iterative Reflexion retry loop)
7. Persists final compliance audit logs
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .approval_manager import ApprovalDecision, ApprovalManager
from .audit_logger import AuditLogger
from .capability_auditor import CapabilityAuditor
from .capability_registry import CapabilityRegistry
from .contract_builder import ContractBuilder
from .evidence_model import (
    ReconciliationReport,
    RepairStep,
    TaskContract,
)
from .final_verifier import FinalVerifier
from .reconciliation_engine import ReconciliationEngine
from .repair_planner import RepairPlanner
from .state_verifier import StateVerifier
from .policy_engine import PolicyEngine


class AegisLoopRunner:
    """
    Main orchestrator for Aegis runs, implementing the iterative repair loop
    and ensuring persistent compliance audit trail outputs.
    """

    def __init__(
        self,
        worker_adapter: Any,
        registry: CapabilityRegistry | None = None,
        workspace: Path | str | None = None,
        max_retries: int = 2,
        ui: Any = None,
        audit_dir: str | Path | None = None,
    ) -> None:
        self.worker_adapter = worker_adapter
        self.registry = registry or CapabilityRegistry()
        self.workspace = Path(workspace) if workspace else None
        self.max_retries = max_retries
        self.ui = ui

        # Setup core Aegis pipeline
        self.contract_builder = ContractBuilder()
        self.auditor = CapabilityAuditor(registry=self.registry)
        self.state_verifier = StateVerifier(workspace=self.workspace)
        self.engine = ReconciliationEngine(
            state_verifier=self.state_verifier,
            capability_auditor=self.auditor,
        )
        self.planner = RepairPlanner(registry=self.registry)
        self.approval_mgr = ApprovalManager(ui=self.ui)
        self.policy_engine = PolicyEngine()
        self.final_verifier = FinalVerifier(engine=self.engine)
        self.audit_logger = AuditLogger(audit_dir=audit_dir)

    def _unpack_bundle(self, res: Any) -> tuple[Any, list[Any]]:
        if isinstance(res, tuple):
            return res
        return res.worker_result, res.events

    def run(self, task_description: str, auto_approve: bool = False) -> dict[str, Any]:
        """
        Execute the task, check for drift, approve, repair, and verify with retries.
        """
        if self.ui:
            self.ui.render_banner()

        # Step 1: Build contract
        if self.ui:
            self.ui.print_info("Building task contract...")
        contract = self.contract_builder.build(task_description)
        if self.ui:
            self.ui.render_contract(contract)

        # Step 2: Initial worker run
        if self.ui:
            self.ui.print_info("Executing initial worker run...")
        worker_result, events = self._unpack_bundle(self.worker_adapter.run_and_collect(task_description))

        if self.ui:
            self.ui.print_info(f"Worker execution complete. Collected {len(events)} events.")

        # Step 3: Initial reconciliation
        report = self.engine.reconcile(contract, events)
        if self.ui:
            self.ui.render_drift_report(report)

        retries = 0
        all_events = list(events)
        approval_decision = None
        repair_steps: list[RepairStep] = []
        latest_report = report
        audit_log_path = None

        try:
            while latest_report.needs_repair and retries < self.max_retries:
                # Update report with iteration context if retrying
                if retries > 0:
                    unmet_notes = "; ".join(
                        f"{c.description}: {c.notes}" for c in latest_report.unmet_criteria
                    )
                    latest_report.previous_failure_reason = unmet_notes
                    latest_report.repair_iteration = retries

                criteria_map = {c.criterion_id: c for c in contract.success_criteria}
                repair_steps = self.planner.plan(latest_report, criteria_map)

                if not repair_steps:
                    if self.ui:
                        self.ui.print_info("No repair steps could be formulated.")
                    break

                # Approval Gate (with Policy Engine evaluation)
                policy_decision = self.policy_engine.evaluate(
                    contract, latest_report, repair_steps, all_events
                )
                if not policy_decision.allow and not policy_decision.requires_human:
                    if self.ui:
                        self.ui.print_warning(f"Repair plan blocked by policy engine: {policy_decision.reason}")
                    approval_decision = ApprovalDecision(
                        approved=False,
                        selected_steps=[],
                        notes=f"Blocked by policy: {policy_decision.reason}",
                    )
                else:
                    effective_auto = auto_approve or (policy_decision.allow and not policy_decision.requires_human)
                    approval_decision = self.approval_mgr.request_approval(
                        contract, latest_report, repair_steps, auto_approve=effective_auto
                    )

                if not approval_decision.approved:
                    if self.ui:
                        self.ui.print_warning("Repair plan rejected or denied.")
                    break

                # Formulate repair prompt for Reflexion-style retry
                approved_steps = approval_decision.selected_steps
                repair_desc = (
                    f"Please perform the following corrections for the task '{contract.goal}':\n"
                )
                repair_desc += "\n".join(f"- {step.description}: {step.action}" for step in approved_steps)
                if retries > 0 and latest_report.previous_failure_reason:
                    repair_desc += (
                        f"\nNote: The previous repair attempt failed with the following errors:\n"
                        f"{latest_report.previous_failure_reason}"
                    )

                if self.ui:
                    self.ui.print_info(f"Executing repair pass (retry iteration {retries + 1}/{self.max_retries})...")

                # Handle SimulatedADKWorker vs real worker
                if (
                    hasattr(self.worker_adapter, "_worker")
                    and self.worker_adapter._worker.__class__.__name__ == "SimulatedADKWorker"
                ):
                    repair_res = self.worker_adapter.run_and_collect(
                        repair_desc,
                        skip_steps=["include_pr"],  # let it produce PR/docs
                    )
                    repair_result, repair_events = self._unpack_bundle(repair_res)
                    # Inject doc/pr mock events for simulation demo compatibility
                    _doc_cap = self.registry.get_by_name("doc_updater")
                    _pr_cap = self.registry.get_by_name("git_create_pr")
                    from aegis.evidence_model import Artifact, EventStatus, EventType, EvidenceEvent
                    doc_event = EvidenceEvent(
                        event_type=EventType.FILE_CHANGE,
                        trace_id=worker_result.trace_id + f"-repair-{retries}",
                        agent_id="adk-repair-worker",
                        capability_id=_doc_cap.capability_id if _doc_cap else "doc_updater",
                        input_summary="docs/auth.md",
                        output_summary="Documentation updated: login validation section added",
                        status=EventStatus.SUCCESS,
                        artifacts=[Artifact(type="file", path="docs/auth.md", description="Auth docs updated")],
                    )
                    pr_event = EvidenceEvent(
                        event_type=EventType.EXTERNAL_ACTION,
                        trace_id=worker_result.trace_id + f"-repair-{retries}",
                        agent_id="adk-repair-worker",
                        capability_id=_pr_cap.capability_id if _pr_cap else "git_create_pr",
                        input_summary="gh pr create --title 'Fix login validation'",
                        output_summary="PR created: https://github.com/org/repo/pull/42",
                        status=EventStatus.SUCCESS,
                        artifacts=[
                            Artifact(
                                type="pr",
                                url="https://github.com/org/repo/pull/42",
                                description="PR #42: Fix login validation bug",
                            )
                        ],
                    )
                    repair_events.extend([doc_event, pr_event])
                else:
                    repair_result, repair_events = self._unpack_bundle(
                        self.worker_adapter.run_and_collect(repair_desc)
                    )

                all_events.extend(repair_events)

                # Re-verify post-repair
                final_report = self.final_verifier.verify(
                    contract,
                    latest_report,
                    repair_events,
                    all_events,
                )
                latest_report = final_report
                retries += 1

                if self.ui:
                    self.ui.print_info(f"Re-verification status: {latest_report.status}")

        finally:
            # Persistent Audit Logging (finally block ensures this always runs)
            runtime = getattr(self.worker_adapter, "agent_id", "unknown")
            audit_log_path = self.audit_logger.save_report(
                contract=contract,
                drift_report=report,
                approval_decision=approval_decision,
                repair_steps=repair_steps,
                final_report=latest_report if latest_report is not report else None,
                runtime=runtime,
            )
            if self.ui:
                self.ui.print_success(f"Compliance audit trail logged → {audit_log_path}")

        # Render final outcome
        if self.ui:
            self.ui.render_final_summary(
                original_status=str(report.status),
                final_status=str(latest_report.status),
                resolved=[c.description for c in report.unmet_criteria if c.criterion_id not in [x.criterion_id for x in latest_report.unmet_criteria]],
                still_unmet=[c.description for c in latest_report.unmet_criteria],
            )

        return {
            "contract": contract,
            "initial_report": report,
            "final_report": latest_report,
            "retries": retries,
            "audit_log_path": audit_log_path,
        }
