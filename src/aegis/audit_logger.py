"""
Aegis Audit Logger

Handles persistent compliance audit trails for Aegis runs.
Saves execution and reconciliation history to ~/.aegis/audit/{date}/{task_id}.json.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence_model import (
    ReconciliationReport,
    RepairStep,
    TaskContract,
)

SCHEMA_VERSION = "1.0"


class AuditLogger:
    """
    Handles logging and querying Aegis compliance audit trails.
    """

    def __init__(self, audit_dir: str | Path | None = None) -> None:
        if audit_dir:
            self.audit_dir = Path(audit_dir)
        else:
            env_dir = os.environ.get("AEGIS_AUDIT_DIR")
            if env_dir:
                self.audit_dir = Path(env_dir)
            else:
                self.audit_dir = Path.home() / ".aegis" / "audit"

    def save_report(
        self,
        contract: TaskContract,
        drift_report: ReconciliationReport,
        approval_decision: Any | None = None,
        repair_steps: list[RepairStep] | None = None,
        final_report: ReconciliationReport | None = None,
        runtime: str | None = None,
    ) -> Path:
        """
        Serialize and persist the complete audit trail of an Aegis run.
        """
        # Create directory for current date
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        target_dir = self.audit_dir / date_str
        target_dir.mkdir(parents=True, exist_ok=True)

        # Build log record
        log_record = {
            "schema_version": SCHEMA_VERSION,
            "task_id": contract.task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "runtime": runtime or "unknown",
            "contract": contract.model_dump(mode="json"),
            "drift_report": drift_report.model_dump(mode="json"),
            "evidence_summary": drift_report.evidence_summary.model_dump(mode="json"),
            "approval_decision": (
                {
                    "approved": approval_decision.approved,
                    "selected_steps": [s.model_dump(mode="json") for s in approval_decision.selected_steps],
                    "notes": approval_decision.notes,
                }
                if approval_decision
                else None
            ),
            "repair_steps": (
                [s.model_dump(mode="json") for s in repair_steps]
                if repair_steps
                else []
            ),
            "final_report": final_report.model_dump(mode="json") if final_report else None,
            "final_status": (
                str(final_report.status)
                if final_report
                else str(drift_report.status)
            ),
        }

        file_path = target_dir / f"{contract.task_id}.json"
        file_path.write_text(json.dumps(log_record, indent=2), encoding="utf-8")
        return file_path

    def get_report(self, task_id: str) -> dict[str, Any] | None:
        """
        Find and load an audit report by task ID.
        """
        # Since files are nested inside dates, we scan the audit directory
        if not self.audit_dir.exists():
            return None

        for path in self.audit_dir.glob("**/*.json"):
            if path.name == f"{task_id}.json":
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return None
        return None

    def list_reports(self) -> list[dict[str, Any]]:
        """
        List all available audit reports, ordered by timestamp descending.
        """
        reports = []
        if not self.audit_dir.exists():
            return reports

        for path in self.audit_dir.glob("**/*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                reports.append({
                    "task_id": data.get("task_id"),
                    "timestamp": data.get("timestamp"),
                    "goal": data.get("contract", {}).get("goal"),
                    "final_status": data.get("final_status"),
                    "runtime": data.get("runtime", "unknown"),
                    "file_path": str(path),
                })
            except (json.JSONDecodeError, OSError):
                continue

        # Sort by timestamp desc
        reports.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return reports
