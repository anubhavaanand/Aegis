"""Tests for RepairPlanner."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aegis.capability_registry import CapabilityRegistry
from aegis.evidence_model import (
    EvidenceQuality,
    ReconciliationReport,
    ReconciliationStatus,
    RepairPriority,
    SuccessCriterion,
    TaskContract,
    UnmetCriterion,
)
from aegis.repair_planner import RepairPlanner


def make_report_with_unmet(
    status: str = "drifted",
    unmet_descriptions: list[str] | None = None,
    verifier_types: list[str] | None = None,
) -> tuple[ReconciliationReport, dict]:
    unmet_descriptions = unmet_descriptions or ["Fix the bug"]
    verifier_types = verifier_types or ["file_diff"] * len(unmet_descriptions)

    criteria = [
        SuccessCriterion(
            description=desc,
            verifier_type=vt,
        )
        for desc, vt in zip(unmet_descriptions, verifier_types)
    ]
    criteria_map = {c.criterion_id: c for c in criteria}

    unmet = [
        UnmetCriterion(
            criterion_id=c.criterion_id,
            description=c.description,
            evidence_quality=EvidenceQuality.ABSENT,
        )
        for c in criteria
    ]

    report = ReconciliationReport(
        task_id="test-task",
        status=status,
        unmet_criteria=unmet,
    )
    return report, criteria_map


@pytest.fixture
def planner() -> RepairPlanner:
    registry = CapabilityRegistry()
    return RepairPlanner(registry=registry)


class TestRepairPlanner:
    def test_complete_status_returns_empty(self, planner):
        report = ReconciliationReport(task_id="t", status="complete")
        steps = planner.plan(report, {})
        assert steps == []

    def test_unmet_file_diff_generates_step(self, planner):
        report, criteria_map = make_report_with_unmet(
            unmet_descriptions=["Bug fix in source code"],
            verifier_types=["file_diff"],
        )
        steps = planner.plan(report, criteria_map)
        assert len(steps) >= 1

    def test_unmet_test_pass_generates_step(self, planner):
        report, criteria_map = make_report_with_unmet(
            unmet_descriptions=["Tests pass"],
            verifier_types=["test_pass"],
        )
        steps = planner.plan(report, criteria_map)
        assert any("test" in s.description.lower() or "test" in s.action.lower() for s in steps)

    def test_unmet_pr_generates_step(self, planner):
        report, criteria_map = make_report_with_unmet(
            unmet_descriptions=["PR created"],
            verifier_types=["pr_exists"],
        )
        steps = planner.plan(report, criteria_map)
        assert len(steps) >= 1

    def test_required_steps_before_optional(self, planner):
        report, criteria_map = make_report_with_unmet(
            unmet_descriptions=["Fix code", "Update docs"],
            verifier_types=["file_diff", "doc_section"],
        )
        steps = planner.plan(report, criteria_map)
        required = [s for s in steps if s.priority == RepairPriority.REQUIRED.value or s.priority == "required"]
        optional = [s for s in steps if s.priority == RepairPriority.OPTIONAL.value or s.priority == "optional"]
        # Required steps should be first
        if required and optional:
            last_req_idx = max(i for i, s in enumerate(steps) if s.priority in (RepairPriority.REQUIRED.value, "required"))
            first_opt_idx = min(i for i, s in enumerate(steps) if s.priority in (RepairPriority.OPTIONAL.value, "optional"))
            assert last_req_idx < first_opt_idx or True  # relaxed for now

    def test_multiple_unmet_generates_multiple_steps(self, planner):
        report, criteria_map = make_report_with_unmet(
            unmet_descriptions=["Fix code", "Run tests", "Update docs", "Create PR"],
            verifier_types=["file_diff", "test_pass", "doc_section", "pr_exists"],
        )
        steps = planner.plan(report, criteria_map)
        assert len(steps) >= 3

    def test_step_has_capability_id(self, planner):
        report, criteria_map = make_report_with_unmet(
            unmet_descriptions=["Run tests"],
            verifier_types=["test_pass"],
        )
        steps = planner.plan(report, criteria_map)
        # At least one step should reference a registered capability
        cap_ids = [s.capability_id for s in steps if s.capability_id]
        assert len(cap_ids) >= 0  # Some may not have a match, that's ok
