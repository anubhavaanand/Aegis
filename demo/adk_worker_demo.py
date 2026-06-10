#!/usr/bin/env python3
"""
Aegis MVP Demo — Login Bug Fix Scenario
========================================

This demo proves the Aegis closed loop end-to-end:

  1. User gives task
  2. Aegis builds a structured task contract
  3. ADK worker executes (simulated — no API keys needed)
  4. Aegis ingests trace and output evidence
  5. Aegis reconciles contract vs execution reality
  6. Aegis finds drift (docs not updated, PR not created)
  7. Aegis flags a missed capability (doc_updater was available)
  8. Aegis shows a drift report
  9. Aegis proposes a corrective sub-plan
  10. User approves
  11. Corrective pass runs
  12. Final verification returns CORRECTED

Run:
    python demo/adk_worker_demo.py

No API keys or live cloud connections required.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Make src importable when running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.rule import Rule

from aegis.contract_builder import ContractBuilder
from aegis.capability_registry import CapabilityRegistry
from aegis.capability_auditor import CapabilityAuditor
from aegis.reconciliation_engine import ReconciliationEngine
from aegis.repair_planner import RepairPlanner
from aegis.approval_manager import ApprovalManager
from aegis.final_verifier import FinalVerifier
from aegis.state_verifier import StateVerifier
from adapters.adk_adapter import ADKAdapter, SimulatedADKWorker
from ui.terminal_ui import TerminalUI

console = Console()
ui = TerminalUI(console=console)


def pause(seconds: float = 0.8) -> None:
    time.sleep(seconds)


def run_demo(auto_approve: bool = False) -> None:
    """
    Run the full Aegis MVP demo scenario.

    Args:
        auto_approve: If True, automatically approve the repair plan
                      (useful for CI / non-interactive environments).
    """
    ui.render_banner()

    # ----------------------------------------------------------------
    # STEP 1: User gives task
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEP 1 — User Request[/cyan]"))
    user_request = (
        "Fix the login validation bug, update docs, run tests, and create a PR."
    )
    console.print(f"\n[bold]User:[/bold] {user_request}\n")
    pause()

    # ----------------------------------------------------------------
    # STEP 2: Aegis builds Task Contract
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEP 2 — Building Task Contract[/cyan]"))
    builder = ContractBuilder()
    contract = builder.build(user_request)
    ui.render_contract(contract)

    # Save contract to demo output
    contract_path = Path(__file__).parent / "output_contract.json"
    contract_path.write_text(
        json.dumps(contract.model_dump(mode="json"), indent=2, default=str)
    )
    console.print(f"[dim]Contract saved → {contract_path}[/dim]")
    pause()

    # ----------------------------------------------------------------
    # STEP 3: ADK Worker executes
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEP 3 — ADK Worker Executing[/cyan]"))
    console.print("[dim]Running simulated ADK worker...[/dim]")

    # The worker intentionally skips docs and PR to trigger drift detection
    worker = SimulatedADKWorker(agent_id="adk-demo-worker")
    adapter = ADKAdapter(worker=worker, agent_id="adk-demo-worker")
    worker_result, events = adapter.run_and_collect(
        user_request,
        skip_steps=["skip_docs"],  # docs skipped, PR not created either
    )

    console.print(f"\n[bold]Worker claimed success:[/bold] {worker_result.claimed_success}")
    console.print(f"[bold]Summary:[/bold] {worker_result.summary}")
    console.print(f"[dim]Collected {len(events)} evidence events[/dim]\n")
    pause()

    # ----------------------------------------------------------------
    # STEP 4: Aegis ingests trace and evidence
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEP 4 — Aegis Ingesting Evidence[/cyan]"))
    console.print(f"[dim]{len(events)} events ingested from trace {worker_result.trace_id[:16]}...[/dim]")
    for ev in events:
        console.print(
            f"  [dim]→ {ev.event_type:12s} | {ev.status:8s} | {ev.input_summary[:50]}[/dim]"
        )
    pause()

    # ----------------------------------------------------------------
    # STEP 5: Reconcile contract vs execution reality
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEP 5 — Reconciliation[/cyan]"))

    # Build registry and auditor
    registry = CapabilityRegistry()
    auditor = CapabilityAuditor(registry=registry)
    state_verifier = StateVerifier(workspace=None)  # No workspace in demo

    engine = ReconciliationEngine(
        state_verifier=state_verifier,
        capability_auditor=auditor,
    )

    report = engine.reconcile(contract, events)

    # ----------------------------------------------------------------
    # STEP 6 + 7: Drift detection
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEPS 6 & 7 — Drift Detection + Missed Capabilities[/cyan]"))
    ui.render_drift_report(report)

    # Save report
    report_path = Path(__file__).parent / "output_reconciliation_report.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, default=str)
    )
    console.print(f"[dim]Report saved → {report_path}[/dim]")
    pause()

    # ----------------------------------------------------------------
    # STEP 8: Propose corrective sub-plan
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEP 8 — Repair Planning[/cyan]"))

    criteria_map = {c.criterion_id: c for c in contract.success_criteria}
    planner = RepairPlanner(registry=registry)
    repair_steps = planner.plan(report, criteria_map)

    ui.render_repair_plan(repair_steps)
    pause()

    # ----------------------------------------------------------------
    # STEP 9: User approves
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEP 9 — Approval Gate[/cyan]"))

    if auto_approve:
        # Non-interactive mode: auto-approve
        console.print("[aegis.warn]Auto-approve mode: approving all repair steps[/]")
        from aegis.approval_manager import ApprovalDecision
        decision = ApprovalDecision(
            approved=True,
            selected_steps=repair_steps,
            notes="Auto-approved (demo mode)",
        )
    else:
        approval_mgr = ApprovalManager(ui=ui)
        decision = approval_mgr.request_approval(contract, report, repair_steps)

    if not decision.approved:
        console.print("\n[aegis.warn]Repair plan rejected by user. Aegis loop complete.[/]")
        return

    console.print(f"\n[aegis.success]Approved {len(decision.selected_steps)} repair step(s)[/]")
    pause()

    # ----------------------------------------------------------------
    # STEP 10: Corrective pass runs
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEP 10 — Corrective Repair Pass[/cyan]"))
    console.print("[dim]Running corrective ADK worker pass (docs + PR)...[/dim]")

    # Second pass: now include docs and PR
    repair_worker = SimulatedADKWorker(agent_id="adk-repair-worker")
    repair_adapter = ADKAdapter(worker=repair_worker, agent_id="adk-repair-worker")
    _, repair_events = repair_adapter.run_and_collect(
        "Update documentation and create PR for login fix",
        skip_steps=["include_pr"],  # this triggers PR creation
    )

    # Simulate doc update event — look up real registry capability_id
    from aegis.evidence_model import EvidenceEvent, EventType, EventStatus, Artifact
    import uuid
    _doc_cap = registry.get_by_name("doc_updater")
    _pr_cap = registry.get_by_name("git_create_pr")
    doc_event = EvidenceEvent(
        event_type=EventType.FILE_CHANGE,
        trace_id=worker_result.trace_id + "-repair",
        agent_id="adk-repair-worker",
        capability_id=_doc_cap.capability_id if _doc_cap else "doc_updater",
        input_summary="docs/auth.md",
        output_summary="Documentation updated: login validation section added",
        status=EventStatus.SUCCESS,
        artifacts=[Artifact(type="file", path="docs/auth.md", description="Auth docs updated")],
    )
    pr_event = EvidenceEvent(
        event_type=EventType.EXTERNAL_ACTION,
        trace_id=worker_result.trace_id + "-repair",
        agent_id="adk-repair-worker",
        capability_id=_pr_cap.capability_id if _pr_cap else "git_create_pr",
        input_summary="gh pr create --title 'Fix login validation'",
        output_summary="PR created: https://github.com/org/repo/pull/42",
        status=EventStatus.SUCCESS,
        artifacts=[Artifact(
            type="pr",
            url="https://github.com/org/repo/pull/42",
            description="PR #42: Fix login validation bug"
        )],
    )
    repair_events.extend([doc_event, pr_event])

    console.print(f"[dim]Repair pass produced {len(repair_events)} additional events[/dim]")
    pause()

    # ----------------------------------------------------------------
    # STEP 11 + 12: Final verification
    # ----------------------------------------------------------------
    console.print(Rule("[cyan]STEPS 11 & 12 — Final Verification[/cyan]"))

    all_events = events + repair_events
    final_verifier = FinalVerifier(engine=engine)
    final_report = final_verifier.verify(
        contract,
        report,
        repair_events,
        all_events,
    )

    summary = final_verifier.summary(report, final_report)

    def _status_str(s: object) -> str:
        return s.value if hasattr(s, "value") else str(s)

    ui.render_final_summary(
        original_status=_status_str(report.status),
        final_status=_status_str(final_report.status),
        resolved=summary["criteria_resolved"],  # type: ignore
        still_unmet=summary["criteria_still_unmet"],  # type: ignore
    )

    # Save final report
    final_report_path = Path(__file__).parent / "output_final_report.json"
    final_report_path.write_text(
        json.dumps(final_report.model_dump(mode="json"), indent=2, default=str)
    )
    console.print(f"\n[dim]Final report saved → {final_report_path}[/dim]")

    console.print()
    console.print(Rule("[bold cyan]Aegis Demo Complete[/bold cyan]"))
    console.print()


if __name__ == "__main__":
    auto = "--auto" in sys.argv or "--yes" in sys.argv
    run_demo(auto_approve=auto)
