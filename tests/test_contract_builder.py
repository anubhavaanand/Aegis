"""Tests for ContractBuilder."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aegis.contract_builder import ContractBuilder
from aegis.evidence_model import RiskLevel, VerifierType


@pytest.fixture
def builder() -> ContractBuilder:
    return ContractBuilder()


class TestContractBuilder:
    def test_basic_build(self, builder):
        contract = builder.build("Fix the login bug")
        assert contract.task_id
        assert contract.user_request == "Fix the login bug"
        assert contract.goal
        assert len(contract.success_criteria) >= 1

    def test_fix_infers_file_diff(self, builder):
        contract = builder.build("Fix the payment validation bug")
        types = [c.verifier_type for c in contract.success_criteria]
        assert VerifierType.FILE_DIFF.value in types or "file_diff" in types

    def test_test_infers_test_pass(self, builder):
        contract = builder.build("Run tests and fix the auth bug")
        types = [c.verifier_type for c in contract.success_criteria]
        assert VerifierType.TEST_PASS.value in types or "test_pass" in types

    def test_docs_infers_doc_section(self, builder):
        contract = builder.build("Update docs for the new API")
        types = [c.verifier_type for c in contract.success_criteria]
        assert VerifierType.DOC_SECTION.value in types or "doc_section" in types

    def test_pr_infers_pr_exists(self, builder):
        contract = builder.build("Create a PR for the login fix")
        types = [c.verifier_type for c in contract.success_criteria]
        assert VerifierType.PR_EXISTS.value in types or "pr_exists" in types

    def test_full_scenario(self, builder):
        contract = builder.build(
            "Fix the login validation bug, update docs, run tests, and create a PR."
        )
        types = {c.verifier_type for c in contract.success_criteria}
        # Should have inferred multiple criteria
        assert len(contract.success_criteria) >= 3

    def test_risk_level_critical_for_production(self, builder):
        contract = builder.build("Deploy to production database")
        assert contract.risk_level in (RiskLevel.CRITICAL.value, "critical")

    def test_risk_level_low_for_docs(self, builder):
        # "readme" and "comment" are LOW keywords; avoid "update" which scores MEDIUM
        contract = builder.build("Read and review the readme comments")
        assert contract.risk_level in (RiskLevel.LOW.value, "low")

    def test_approval_required_for_pr(self, builder):
        contract = builder.build("Create a PR for this fix")
        assert "pr" in contract.approval_required_for

    def test_extra_criteria_injection(self, builder):
        contract = builder.build(
            "Fix the bug",
            extra_criteria=[
                {"description": "Changelog updated", "verifier_type": "doc_section"}
            ],
        )
        descs = [c.description for c in contract.success_criteria]
        assert any("Changelog" in d for d in descs)

    def test_empty_request_gets_fallback_criterion(self, builder):
        # Even a minimal request should produce at least one criterion
        contract = builder.build("Do something")
        assert len(contract.success_criteria) >= 1

    def test_contract_has_created_at(self, builder):
        contract = builder.build("Fix something")
        assert contract.created_at is not None
