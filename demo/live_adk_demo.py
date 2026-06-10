#!/usr/bin/env python3
"""
Aegis Live ADK Demo
===================

This demo runs a real Google ADK agent with tool calls, captures spans in real-time,
and feeds them to Aegis for contract verification and capability auditing.

Prerequisites:
  1. Set GOOGLE_API_KEY environment variable.
  2. (Optional) Run Phoenix locally and set PHOENIX_COLLECTOR_ENDPOINT="http://localhost:6006/v1/traces".

Run:
    GOOGLE_API_KEY="your-key" python demo/live_adk_demo.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Make src importable when running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.rule import Rule
from rich.panel import Panel

from aegis.contract_builder import ContractBuilder
from aegis.capability_registry import CapabilityRegistry
from aegis.capability_auditor import CapabilityAuditor
from aegis.reconciliation_engine import ReconciliationEngine
from aegis.repair_planner import RepairPlanner
from aegis.approval_manager import ApprovalManager
from aegis.final_verifier import FinalVerifier
from aegis.state_verifier import StateVerifier
from adapters.adk_adapter import ADKAdapter
from ui.terminal_ui import TerminalUI

console = Console()
ui = TerminalUI(console=console)


def run_live_demo() -> None:
    ui.render_banner()

    # 1. Verification of environment keys
    if not os.environ.get("GOOGLE_API_KEY"):
        console.print(Panel(
            "[bold red]Error: GOOGLE_API_KEY is not set.[/bold red]\n\n"
            "To run the live ADK demo, you must set your Gemini API key in your environment:\n"
            "  [yellow]export GOOGLE_API_KEY=\"your_api_key_here\"[/yellow]\n\n"
            "Alternatively, run the simulated demo which requires no keys:\n"
            "  [yellow]python demo/adk_worker_demo.py --auto[/yellow]",
            title="Live Demo Prerequisites",
            border_style="red"
        ))
        sys.exit(1)

    # STEP 1: User gives task
    console.print(Rule("[cyan]STEP 1 — User Request[/cyan]"))
    user_request = (
        "Add 15 and 27, then multiply the result by 3. Use tools to calculate."
    )
    console.print(f"\n[bold]User:[/bold] {user_request}\n")

    # STEP 2: Aegis builds Task Contract
    console.print(Rule("[cyan]STEP 2 — Building Task Contract[/cyan]"))
    builder = ContractBuilder()
    contract = builder.build(user_request)
    ui.render_contract(contract)

    # STEP 3: Real ADK Worker executes
    console.print(Rule("[cyan]STEP 3 — Real ADK Worker Executing[/cyan]"))
    console.print("[dim]Starting real ADK agent... (instrumented with OpenTelemetry & OpenInference)[/dim]")

    adapter = ADKAdapter(agent_id="real-math-worker", use_real_adk=True)
    
    with console.status("[bold green]Running real ADK runner..."):
        try:
            worker_result, events = adapter.run_and_collect(user_request)
        except Exception as e:
            console.print(f"\n[bold red]Execution failed:[/bold red] {e}")
            sys.exit(1)

    console.print(f"\n[bold]Worker claimed success:[/bold] {worker_result.claimed_success}")
    console.print(f"[bold]Summary:[/bold] {worker_result.summary}")
    console.print(f"[dim]Collected {len(events)} evidence events from OpenInference spans[/dim]\n")

    # STEP 4: Aegis ingests trace and evidence
    console.print(Rule("[cyan]STEP 4 — Aegis Ingesting Evidence[/cyan]"))
    console.print(f"[dim]{len(events)} events normalized from trace {worker_result.trace_id[:16]}...[/dim]")
    for ev in events:
        console.print(
            f"  [dim]→ {ev.event_type:12s} | {ev.status:8s} | {ev.input_summary[:50]}[/dim]"
        )

    # STEP 5: Reconcile contract vs execution reality
    console.print(Rule("[cyan]STEP 5 — Reconciliation[/cyan]"))
    registry = CapabilityRegistry()
    auditor = CapabilityAuditor(registry=registry)
    state_verifier = StateVerifier(workspace=None)

    engine = ReconciliationEngine(
        state_verifier=state_verifier,
        capability_auditor=auditor,
    )

    report = engine.reconcile(contract, events)

    # STEPS 6 & 7: Drift detection + Missed capabilities
    console.print(Rule("[cyan]STEPS 6 & 7 — Drift Detection + Missed Capabilities[/cyan]"))
    ui.render_drift_report(report)

    # Save report
    report_path = Path(__file__).parent / "output_live_reconciliation_report.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, default=str)
    )
    console.print(f"[dim]Report saved → {report_path}[/dim]")

    console.print()
    console.print(Rule("[bold cyan]Aegis Live Demo Complete[/bold cyan]"))
    console.print()


if __name__ == "__main__":
    run_live_demo()
