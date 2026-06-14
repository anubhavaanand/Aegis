"""
Aegis Command Line Interface

Provides Typer commands:
- run: Executing tasks through the Aegis verification loop
- report: Viewing persistent audit logs
- list-audits: Listing historical audit runs
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Python 3.14+ Click compatibility patches for Typer compatibility
import click
if not hasattr(click.Choice, "__class_getitem__"):
    click.Choice.__class_getitem__ = classmethod(lambda cls, item: cls)
if not hasattr(click.Parameter, "_aegis_patched"):
    _orig_make_metavar = click.Parameter.make_metavar
    click.Parameter.make_metavar = lambda self, ctx=None: _orig_make_metavar(self)
    click.Parameter._aegis_patched = True

import typer
from rich.console import Console
from rich.table import Table

import os
from adapters.adk_adapter import ADKAdapter
from aegis.audit_logger import AuditLogger
from aegis.runner import AegisLoopRunner
from aegis.capability_registry import CapabilityRegistry
from aegis.evidence_model import CapabilityType
from ui.terminal_ui import TerminalUI

app = typer.Typer(
    name="aegis",
    help="Aegis: Post-execution state reconciliation and trace audit layer.",
    no_args_is_help=True,
)

console = Console()
ui = TerminalUI(console=console)


@app.command("run")
def run_task(
    request: str = typer.Option(
        ..., "--request", "-r", help="The user request to execute and audit."
    ),
    auto_approve: bool = typer.Option(
        False, "--auto", "-y", help="Automatically approve proposed repairs."
    ),
    retries: int = typer.Option(
        2, "--retries", "-n", help="Maximum number of self-healing repair attempts."
    ),
    real_adk: bool = typer.Option(
        False, "--real", help="Use real Google ADK agent instead of simulated."
    ),
    audit_dir: Optional[str] = typer.Option(
        None, "--audit-dir", help="Custom path to write audit logs to."
    ),
    semantic: bool = typer.Option(
        False, "--semantic", help="Enable semantic verification via Gemini LLM-as-Judge."
    ),
    policy: str = typer.Option(
        "in-process", "--policy", help="Policy engine mode ('in-process' or 'opa')."
    ),
    runtime: str = typer.Option(
        "adk", "--runtime", help="Developer CLI runtime to verify: 'adk' (default), 'gemini', 'opencode', 'antigravity'."
    ),
) -> None:
    """
    Run a task, reconcile its telemetry, and auto-repair if drift is detected.
    """
    if semantic:
        os.environ["AEGIS_SEMANTIC_VERIFY"] = "true"
    else:
        os.environ["AEGIS_SEMANTIC_VERIFY"] = "false"

    os.environ["AEGIS_POLICY_ENGINE"] = policy
    # Initialize adapter using selector
    from adapters.runtime_selector import RuntimeSelector
    if runtime.lower() == "adk":
        adapter = RuntimeSelector.get_adapter(
            "adk",
            agent_id="real-cli-worker" if real_adk else "simulated-cli-worker",
            use_real_adk=real_adk,
        )
    else:
        adapter = RuntimeSelector.get_adapter(
            runtime,
            agent_id=f"{runtime}-cli-agent",
            use_simulated=not real_adk,
        )

    runner = AegisLoopRunner(
        worker_adapter=adapter,
        workspace=Path.cwd(),
        max_retries=retries,
        ui=ui,
        audit_dir=audit_dir,
    )

    try:
        runner.run(request, auto_approve=auto_approve)
    except Exception as e:
        ui.print_error(f"Execution failed: {e}")
        raise typer.Exit(code=1)


@app.command("report")
def view_report(
    task_id: str = typer.Option(
        ..., "--task-id", "-t", help="The unique Task ID to inspect."
    ),
    audit_dir: Optional[str] = typer.Option(
        None, "--audit-dir", help="Custom audit directory path."
    ),
) -> None:
    """
    Load and display a historical Aegis compliance audit report.
    """
    logger = AuditLogger(audit_dir=audit_dir)
    data = logger.get_report(task_id)

    if not data:
        ui.print_error(f"Audit report for Task ID '{task_id}' not found.")
        raise typer.Exit(code=1)

    # Decode JSON into ReconciliationReport, TaskContract, etc.
    from aegis.evidence_model import ReconciliationReport, RepairStep, TaskContract

    contract = TaskContract.model_validate(data["contract"])
    drift_report = ReconciliationReport.model_validate(data["drift_report"])
    final_report = (
        ReconciliationReport.model_validate(data["final_report"])
        if data.get("final_report")
        else None
    )

    ui.render_banner()
    console.print(f"[bold cyan]AUDIT REPORT FOR TASK ID:[/bold cyan] {task_id}")
    console.print(f"[bold cyan]TIMESTAMP:[/bold cyan] {data.get('timestamp')}")
    console.print(f"[bold cyan]SCHEMA VERSION:[/bold cyan] {data.get('schema_version')}")
    console.print()

    ui.render_contract(contract)
    console.print("\n[bold cyan]Initial Drift Findings:[/bold cyan]")
    ui.render_drift_report(drift_report)

    if data.get("approval_decision"):
        decision = data["approval_decision"]
        console.print(
            f"\n[bold cyan]Approval decision:[/bold cyan] "
            f"{'Approved' if decision.get('approved') else 'Denied'} | "
            f"Notes: {decision.get('notes')}"
        )

    if data.get("repair_steps"):
        console.print("\n[bold cyan]Proposed Repair Steps:[/bold cyan]")
        steps = [RepairStep.model_validate(s) for s in data["repair_steps"]]
        ui.render_repair_plan(steps)

    if final_report:
        console.print("\n[bold cyan]Final Reconciliation Findings:[/bold cyan]")
        ui.render_drift_report(final_report)
        ui.render_final_summary(
            original_status=str(drift_report.status),
            final_status=str(final_report.status),
            resolved=[
                c.description
                for c in drift_report.unmet_criteria
                if c.criterion_id not in [x.criterion_id for x in final_report.unmet_criteria]
            ],
            still_unmet=[c.description for c in final_report.unmet_criteria],
        )
    else:
        console.print("\n[bold yellow]No repair loop was executed.[/bold yellow]")


@app.command("list-audits")
def list_audits(
    audit_dir: Optional[str] = typer.Option(
        None, "--audit-dir", help="Custom audit directory path."
    ),
    runtime: Optional[str] = typer.Option(
        None, "--runtime", help="Filter logs by runtime agent name (e.g., 'gemini', 'opencode')."
    ),
) -> None:
    """
    List all archived compliance audit reports.
    """
    logger = AuditLogger(audit_dir=audit_dir)
    reports = logger.list_reports()

    # Filter by runtime if specified
    if runtime:
        rt_lower = runtime.lower()
        reports = [r for r in reports if rt_lower in r.get("runtime", "unknown").lower()]

    if not reports:
        ui.print_warning("No audit reports found matching criteria.")
        return

    table = Table(title="Aegis Compliance Audit Log")
    table.add_column("Task ID", style="cyan")
    table.add_column("Timestamp", style="magenta")
    table.add_column("Goal", style="white")
    table.add_column("Runtime", style="blue")
    table.add_column("Final Status", style="green")

    for r in reports:
        status = r.get("final_status")
        status_color = "green" if status in ("complete", "corrected") else "red" if status == "failed" else "yellow"

        table.add_row(
            r.get("task_id")[:16] + "...",
            r.get("timestamp"),
            r.get("goal")[:50] + "..." if len(r.get("goal", "")) > 50 else r.get("goal"),
            r.get("runtime", "unknown"),
            f"[{status_color}]{status}[/{status_color}]",
        )

    console.print(table)


@app.command("discover-capabilities")
def discover_capabilities(
    config_path: Optional[str] = typer.Option(
        None, "--config", "-c", help="Custom path to MCP servers.json configuration."
    ),
    output: str = typer.Option(
        "capabilities_manifest.json", "--output", "-o", help="Output JSON manifest file path."
    ),
) -> None:
    """
    Auto-discover capabilities from installed MCP configs and save manifest.
    """
    registry = CapabilityRegistry()
    ui.print_info("Scanning MCP configurations for servers and tools...")
    registry.discover_from_mcp_config(config_path)

    mcp_caps = registry.by_type(CapabilityType.MCP)
    ui.print_success(f"Discovered {len(mcp_caps)} MCP capabilities.")

    try:
        registry.save_capability_manifest(output)
        ui.print_success(f"Saved capability manifest to: {output}")
    except Exception as e:
        ui.print_error(f"Failed to save capability manifest: {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
