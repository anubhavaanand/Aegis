"""
Aegis Terminal UI

Rich-powered terminal interface for Aegis drift reports, approval gates,
and step-by-step progress tracking.

Design principles:
  - Use Rich panels, tables, and color to make drift immediately obvious
  - Make the approval gate unmissable
  - Keep it fast — no blocking rendering calls
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from aegis.evidence_model import (
    ReconciliationReport,
    ReconciliationStatus,
    RepairPriority,
    RepairStep,
    TaskContract,
)

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

AEGIS_THEME = Theme({
    "aegis.title": "bold cyan",
    "aegis.success": "bold green",
    "aegis.warn": "bold yellow",
    "aegis.error": "bold red",
    "aegis.info": "dim",
    "aegis.critical": "bold magenta",
    "aegis.repair": "bold blue",
    "aegis.border": "cyan",
})

console = Console(theme=AEGIS_THEME, highlight=True)

# Status → (icon, style)
_STATUS_STYLE: dict[str, tuple[str, str]] = {
    ReconciliationStatus.COMPLETE: ("✅", "aegis.success"),
    ReconciliationStatus.CORRECTED: ("✅", "aegis.success"),
    ReconciliationStatus.PARTIAL: ("⚠️ ", "aegis.warn"),
    ReconciliationStatus.DRIFTED: ("🔴", "aegis.error"),
    ReconciliationStatus.FAILED: ("💀", "aegis.error"),
    ReconciliationStatus.SUBOPTIMAL: ("🔶", "aegis.warn"),
}


# ---------------------------------------------------------------------------
# TerminalUI
# ---------------------------------------------------------------------------


class TerminalUI:
    """
    Rich-powered terminal UI for the Aegis approval and reporting loop.
    """

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or globals()["console"]

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------

    def render_banner(self) -> None:
        banner = Text()
        banner.append("  AEGIS  ", style="bold white on cyan")
        banner.append("  Post-Execution Reconciliation Layer", style="cyan")
        self._console.print()
        self._console.print(Align.center(banner))
        self._console.print(
            Align.center(Text("Truth-checking for agent runtimes", style="aegis.info"))
        )
        self._console.print()

    # ------------------------------------------------------------------
    # Contract display
    # ------------------------------------------------------------------

    def render_contract(self, contract: TaskContract) -> None:
        table = Table(
            show_header=False,
            box=box.SIMPLE,
            padding=(0, 1),
            border_style="cyan",
        )
        table.add_column("Key", style="bold", width=22)
        table.add_column("Value")

        table.add_row("Task ID", contract.task_id[:16] + "...")
        table.add_row("Goal", contract.goal)
        table.add_row("Risk Level", _risk_badge(str(contract.risk_level)))
        table.add_row(
            "Criteria",
            f"{len(contract.success_criteria)} success criteria",
        )
        if contract.approval_required_for:
            table.add_row(
                "Approval Required",
                ", ".join(contract.approval_required_for),
            )

        self._console.print(
            Panel(table, title="[aegis.title]Task Contract[/]", border_style="cyan")
        )

    # ------------------------------------------------------------------
    # Drift Report
    # ------------------------------------------------------------------

    def render_drift_report(self, report: ReconciliationReport) -> None:
        status_icon, status_style = _STATUS_STYLE.get(
            report.status, ("?", "aegis.info")
        )
        status_text = Text()
        status_text.append(f"{status_icon} ", style=status_style)
        status_text.append(str(report.status).upper(), style=status_style)

        self._console.print(
            Panel(
                Align.center(status_text),
                title="[aegis.title]Reconciliation Status[/]",
                border_style=self._status_border(report.status),
                padding=(1, 4),
            )
        )

        # Evidence summary
        self._render_evidence_summary(report)

        # Unmet criteria
        if report.unmet_criteria:
            self._render_unmet_criteria(report)

        # Weak evidence
        if report.weak_evidence:
            self._render_weak_evidence(report)

        # Missed capabilities
        if report.missed_capabilities:
            self._render_missed_capabilities(report)

    def _render_evidence_summary(self, report: ReconciliationReport) -> None:
        s = report.evidence_summary
        table = Table(box=box.ROUNDED, border_style="bright_black")
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")

        table.add_row("Total Events", str(s.total_events))
        table.add_row("✅ Successful", f"[green]{s.successful_events}[/green]")
        table.add_row("❌ Failed", f"[red]{s.failed_events}[/red]" if s.failed_events else "0")
        table.add_row("🔧 Tool Calls", str(s.tool_calls))
        table.add_row("🤖 Model Calls", str(s.model_calls))
        table.add_row("📄 File Changes", str(s.file_changes))
        table.add_row("🧪 Test Results", str(s.test_results))

        self._console.print(
            Panel(table, title="[aegis.title]Evidence Summary[/]", border_style="dim")
        )

    def _render_unmet_criteria(
        self, report: ReconciliationReport
    ) -> None:
        table = Table(box=box.ROUNDED, border_style="red")
        table.add_column("Criterion", style="bold")
        table.add_column("Evidence Quality")
        table.add_column("Notes", max_width=50)

        for c in report.unmet_criteria:
            table.add_row(
                f"✗ {c.description}",
                _quality_badge(str(c.evidence_quality)),
                c.notes[:80],
            )

        self._console.print(
            Panel(
                table,
                title=f"[aegis.error]Unmet Criteria ({len(report.unmet_criteria)})[/]",
                border_style="red",
            )
        )

    def _render_weak_evidence(
        self, report: ReconciliationReport
    ) -> None:
        table = Table(box=box.ROUNDED, border_style="yellow")
        table.add_column("Criterion", style="bold")
        table.add_column("Notes", max_width=60)

        for c in report.weak_evidence:
            table.add_row(f"⚠️  {c.description}", c.notes[:80])

        self._console.print(
            Panel(
                table,
                title=f"[aegis.warn]Weak Evidence ({len(report.weak_evidence)})[/]",
                border_style="yellow",
            )
        )

    def _render_missed_capabilities(
        self, report: ReconciliationReport
    ) -> None:
        table = Table(box=box.ROUNDED, border_style="magenta")
        table.add_column("Capability", style="bold")
        table.add_column("Impact")
        table.add_column("Reason", max_width=55)

        for m in report.missed_capabilities:
            table.add_row(
                f"● {m.name}",
                _impact_badge(str(m.impact)),
                m.reason[:80],
            )

        self._console.print(
            Panel(
                table,
                title=f"[aegis.critical]Missed Capabilities ({len(report.missed_capabilities)})[/]",
                border_style="magenta",
            )
        )

    # ------------------------------------------------------------------
    # Approval Screen
    # ------------------------------------------------------------------

    def render_approval_screen(
        self,
        contract: TaskContract,
        report: ReconciliationReport,
        repair_steps: list[RepairStep],
    ) -> None:
        self._console.print(Rule("[aegis.title]⚡ AEGIS APPROVAL GATE ⚡[/]", style="cyan"))
        self.render_contract(contract)
        self.render_drift_report(report)
        self.render_repair_plan(repair_steps)

    def render_repair_plan(self, steps: list[RepairStep]) -> None:
        if not steps:
            self._console.print(Panel(
                "[aegis.success]No repairs needed[/]",
                title="[aegis.title]Repair Plan[/]",
                border_style="green",
            ))
            return

        table = Table(box=box.ROUNDED, border_style="blue")
        table.add_column("#", width=3)
        table.add_column("Priority", width=10)
        table.add_column("Description", style="bold")
        table.add_column("Action", max_width=40)

        for i, step in enumerate(steps, 1):
            priority_badge = (
                "[bold red]REQUIRED[/bold red]"
                if step.priority == RepairPriority.REQUIRED
                else "[dim]optional[/dim]"
            )
            table.add_row(
                str(i),
                priority_badge,
                step.description,
                step.action[:80],
            )

        self._console.print(
            Panel(
                table,
                title=f"[aegis.repair]Proposed Repair Plan ({len(steps)} steps)[/]",
                border_style="blue",
            )
        )

    # ------------------------------------------------------------------
    # Progress / Final
    # ------------------------------------------------------------------

    def render_final_summary(
        self,
        original_status: str,
        final_status: str,
        resolved: list[str],
        still_unmet: list[str],
    ) -> None:
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Key", style="bold", width=20)
        table.add_column("Value")

        table.add_row("Original Status", original_status)
        table.add_row("Final Status", final_status)
        table.add_row(
            "Criteria Resolved",
            f"[green]{len(resolved)}[/green]" if resolved else "0",
        )
        table.add_row(
            "Still Unmet",
            f"[red]{len(still_unmet)}[/red]" if still_unmet else "[green]0 ✅[/green]",
        )

        border = "green" if not still_unmet else "red"
        title = (
            "[aegis.success]✅ Aegis: CORRECTED[/]"
            if not still_unmet
            else "[aegis.error]⚠️  Aegis: Unresolved Issues[/]"
        )
        self._console.print(Panel(table, title=title, border_style=border))

    def print_success(self, message: str) -> None:
        self._console.print(f"[aegis.success]✅ {message}[/]")  

    def print_warning(self, message: str) -> None:
        self._console.print(f"[aegis.warn]⚠️  {message}[/]")

    def print_error(self, message: str) -> None:
        self._console.print(f"[aegis.error]✗ {message}[/]")

    def print_info(self, message: str) -> None:
        self._console.print(f"[aegis.info]{message}[/]")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _status_border(status: str) -> str:
        mapping = {
            ReconciliationStatus.COMPLETE: "green",
            ReconciliationStatus.CORRECTED: "green",
            ReconciliationStatus.PARTIAL: "yellow",
            ReconciliationStatus.DRIFTED: "red",
            ReconciliationStatus.FAILED: "red",
            ReconciliationStatus.SUBOPTIMAL: "yellow",
        }
        return mapping.get(status, "dim")  # type: ignore


# ---------------------------------------------------------------------------
# Helper badge functions
# ---------------------------------------------------------------------------


def _risk_badge(risk: str) -> Text:
    colors = {"low": "green", "medium": "yellow", "high": "red", "critical": "magenta"}
    color = colors.get(risk.lower(), "dim")
    t = Text()
    t.append(f" {risk.upper()} ", style=f"bold white on {color}")
    return t


def _quality_badge(quality: str) -> Text:
    colors = {"strong": "green", "weak": "yellow", "absent": "red"}
    color = colors.get(quality.lower(), "dim")
    t = Text()
    t.append(f" {quality.upper()} ", style=f"bold {color}")
    return t


def _impact_badge(impact: str) -> Text:
    colors = {"critical": "magenta", "significant": "yellow", "minor": "dim"}
    color = colors.get(impact.lower(), "dim")
    t = Text()
    t.append(f" {impact.upper()} ", style=f"bold {color}")
    return t
