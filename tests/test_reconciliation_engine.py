"""Tests for ReconciliationEngine and DriftClassifier."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aegis.contract_builder import ContractBuilder
from aegis.evidence_model import (
    Artifact,
    EvidenceEvent,
    EventStatus,
    EventType,
    ReconciliationStatus,
    SuccessCriterion,
    TaskContract,
    VerifierType,
)
from aegis.reconciliation_engine import ReconciliationEngine
from aegis.state_verifier import StateVerifier


def make_file_change_event(trace_id: str = "trace-001") -> EvidenceEvent:
    return EvidenceEvent(
        event_type=EventType.FILE_CHANGE,
        trace_id=trace_id,
        agent_id="test-agent",
        input_summary="src/auth.py",
        output_summary="File written",
        status=EventStatus.SUCCESS,
        artifacts=[Artifact(type="file", path="src/auth.py")],
    )


def make_test_event(trace_id: str = "trace-001", status: EventStatus = EventStatus.SUCCESS) -> EvidenceEvent:
    return EvidenceEvent(
        event_type=EventType.TEST_RESULT,
        trace_id=trace_id,
        agent_id="test-agent",
        input_summary="pytest tests/",
        output_summary="5 passed",
        status=status,
    )


def make_contract_with_criteria(*verifier_types: str) -> TaskContract:
    criteria = [
        SuccessCriterion(description=f"Criterion: {vt}", verifier_type=vt)
        for vt in verifier_types
    ]
    return TaskContract(
        user_request="Test request",
        goal="Test goal",
        success_criteria=criteria,
    )


@pytest.fixture
def engine() -> ReconciliationEngine:
    return ReconciliationEngine(state_verifier=StateVerifier(workspace=None))


class TestReconciliationEngine:
    def test_all_unmet_returns_failed(self, engine):
        contract = make_contract_with_criteria("file_diff", "test_pass")
        report = engine.reconcile(contract, events=[])
        assert report.status in (ReconciliationStatus.FAILED.value, "failed")

    def test_file_change_satisfies_file_diff(self, engine):
        contract = make_contract_with_criteria("file_diff")
        events = [make_file_change_event()]
        report = engine.reconcile(contract, events)
        # file_diff criterion should now be met
        assert report.status not in ("failed",)

    def test_test_pass_event_satisfies_test_pass(self, engine):
        contract = make_contract_with_criteria("test_pass")
        events = [make_test_event()]
        report = engine.reconcile(contract, events)
        assert len(report.unmet_criteria) == 0

    def test_failed_test_is_unmet(self, engine):
        contract = make_contract_with_criteria("test_pass")
        events = [make_test_event(status=EventStatus.FAILURE)]
        report = engine.reconcile(contract, events)
        assert len(report.unmet_criteria) > 0

    def test_mixed_criteria_returns_drifted(self, engine):
        contract = make_contract_with_criteria("file_diff", "pr_exists")
        events = [make_file_change_event()]  # file_diff met, pr_exists not met
        report = engine.reconcile(contract, events)
        assert report.status in ("drifted", "partial", "failed")

    def test_evidence_summary_counts(self, engine):
        contract = make_contract_with_criteria("file_diff")
        events = [
            make_file_change_event(),
            make_test_event(),
        ]
        report = engine.reconcile(contract, events)
        assert report.evidence_summary.total_events == 2
        assert report.evidence_summary.file_changes == 1
        assert report.evidence_summary.test_results == 1

    def test_report_has_task_id(self, engine):
        contract = make_contract_with_criteria("file_diff")
        report = engine.reconcile(contract, [])
        assert report.task_id == contract.task_id

    def test_empty_events_all_unmet(self, engine):
        builder = ContractBuilder()
        contract = builder.build(
            "Fix the login validation bug, update docs, run tests, and create a PR."
        )
        report = engine.reconcile(contract, events=[])
        assert len(report.unmet_criteria) > 0
        assert report.status in ("failed", "drifted")
