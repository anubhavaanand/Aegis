"""
Tests for Aegis Loop Runner, Audit Logger, Risk-Tiered Approvals, and CLI commands.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from aegis.audit_logger import AuditLogger
from aegis.evidence_model import (
    Artifact,
    EventStatus,
    EventType,
    EvidenceEvent,
    ReconciliationReport,
    ReconciliationStatus,
    RepairStep,
    RiskLevel,
    TaskContract,
)
from aegis.runner import AegisLoopRunner
from aegis.approval_manager import ApprovalManager, ApprovalDecision
from aegis.contract_builder import ContractBuilder


class MockWorkerAdapter:
    def __init__(self, trace_id="mock-trace-123"):
        self.trace_id = trace_id
        self.run_calls = []

    def run_and_collect(self, task_description, skip_steps=None):
        self.run_calls.append(task_description)
        # Mock initial run result
        from adapters.adk_adapter import WorkerResult
        worker_res = WorkerResult(
            trace_id=self.trace_id,
            agent_id="mock-agent",
            claimed_success=True,
            summary="Done",
            tool_calls=[],
        )
        
        # Initial run has file changes but no tests run to trigger drift/repair
        events = [
            EvidenceEvent(
                event_type=EventType.FILE_CHANGE,
                trace_id=self.trace_id,
                agent_id="mock-agent",
                status=EventStatus.SUCCESS,
                artifacts=[Artifact(type="file", path="auth.py")],
            )
        ]
        return worker_res, events


@pytest.fixture
def temp_audit_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestAuditLogger:
    def test_save_and_load_report(self, temp_audit_dir):
        logger = AuditLogger(audit_dir=temp_audit_dir)

        contract = TaskContract(
            user_request="Refactor tests",
            goal="Refactor tests",
            risk_level=RiskLevel.LOW,
            success_criteria=[{"description": "Code changes", "verifier_type": "file_diff"}],
        )

        report = ReconciliationReport(
            task_id=contract.task_id,
            status=ReconciliationStatus.COMPLETE,
        )

        decision = ApprovalDecision(approved=True, selected_steps=[], notes="Test notes")

        file_path = logger.save_report(
            contract=contract,
            drift_report=report,
            approval_decision=decision,
        )

        assert file_path.exists()
        
        # Load report
        loaded = logger.get_report(contract.task_id)
        assert loaded is not None
        assert loaded["task_id"] == contract.task_id
        assert loaded["schema_version"] == "1.0"
        assert loaded["approval_decision"]["notes"] == "Test notes"

        # List reports
        reports = logger.list_reports()
        assert len(reports) == 1
        assert reports[0]["task_id"] == contract.task_id


class TestRiskTieredApproval:
    def test_low_risk_auto_approve_env_var(self):
        contract = TaskContract(
            user_request="Fix doc string",
            goal="Fix doc string",
            risk_level=RiskLevel.LOW,
            success_criteria=[{"description": "Doc changes", "verifier_type": "doc_section"}],
        )
        report = ReconciliationReport(
            task_id=contract.task_id,
            status=ReconciliationStatus.DRIFTED,
        )
        steps = [
            RepairStep(
                description="Update doc",
                targets_criterion="c1",
                action="Write docs",
            )
        ]

        # Enable auto approve
        with patch.dict(os.environ, {"AEGIS_AUTO_APPROVE_LOW_RISK": "true"}):
            mgr = ApprovalManager()
            decision = mgr.request_approval(contract, report, steps)
            assert decision.approved is True
            assert "Auto-approved LOW risk" in decision.notes

    def test_medium_risk_timeout_or_deny(self):
        contract = TaskContract(
            user_request="Refactor logic",
            goal="Refactor logic",
            risk_level=RiskLevel.MEDIUM,
            success_criteria=[{"description": "Code changes", "verifier_type": "file_diff"}],
        )
        report = ReconciliationReport(
            task_id=contract.task_id,
            status=ReconciliationStatus.DRIFTED,
        )
        steps = [
            RepairStep(
                description="Fix bug",
                targets_criterion="c1",
                action="Write file",
            )
        ]

        # In non-TTY environment it should default to deny
        with patch("sys.stdin.isatty", return_value=False):
            mgr = ApprovalManager()
            decision = mgr.request_approval(contract, report, steps)
            assert decision.approved is False
            assert "non-interactive" in decision.notes.lower()


class TestAegisLoopRunner:
    def test_loop_runner_runs_and_retries(self, temp_audit_dir):
        worker = MockWorkerAdapter()
        runner = AegisLoopRunner(
            worker_adapter=worker,
            workspace=None,
            max_retries=2,
            audit_dir=temp_audit_dir,
        )

        call_count = 0
        def run_and_collect_mock(prompt, skip_steps=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    MockWorkerAdapter().run_and_collect("Fix bug and run tests")[0],
                    [
                        EvidenceEvent(
                            event_type=EventType.FILE_CHANGE,
                            trace_id="initial-trace",
                            agent_id="mock-agent",
                            status=EventStatus.SUCCESS,
                            artifacts=[Artifact(type="file", path="auth.py")],
                        )
                    ]
                )
            else:
                # Verify failure reason was passed to prompt
                assert "test" in prompt.lower()
                
                from adapters.adk_adapter import WorkerResult
                res = WorkerResult(
                    trace_id="repair-trace-123",
                    agent_id="mock-agent",
                    claimed_success=True,
                    summary="Tests pass",
                    tool_calls=[],
                )
                events = [
                    EvidenceEvent(
                        event_type=EventType.TEST_RESULT,
                        trace_id="repair-trace-123",
                        agent_id="mock-agent",
                        status=EventStatus.SUCCESS,
                    )
                ]
                return res, events

        # Run with auto approve
        with patch.object(runner.worker_adapter, "run_and_collect", side_effect=run_and_collect_mock):
            res = runner.run("Fix bug and run tests", auto_approve=True)
            assert res["final_report"] is not None
            assert res["final_report"].status in (ReconciliationStatus.CORRECTED, ReconciliationStatus.COMPLETE)
            assert res["retries"] == 1


class TestLLMContractBuilderGracefulFallback:
    def test_llm_mode_fallback_without_key(self):
        builder = ContractBuilder()
        
        # Enable LLM mode but clean GOOGLE_API_KEY
        with patch.dict(os.environ, {"AEGIS_CONTRACT_MODE": "llm", "GOOGLE_API_KEY": ""}):
            contract = builder.build("Fix bug and run tests")
            # Should fallback to heuristic contract successfully
            assert contract.goal == "Fix bug and run tests"
            assert len(contract.success_criteria) > 0
