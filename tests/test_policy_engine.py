"""Tests for PolicyEngine including risk-tiering, path restrictions, and OPA REST calls."""

from __future__ import annotations

import os
import json
from unittest.mock import MagicMock, patch
import pytest

from aegis.evidence_model import (
    EvidenceEvent,
    EventType,
    ReconciliationReport,
    ReconciliationStatus,
    RepairStep,
    RiskLevel,
    TaskContract,
    UnmetCriterion,
    EvidenceQuality,
)
from aegis.policy_engine import PolicyEngine, PolicyDecision


class TestPolicyEngineInProcess:
    @pytest.fixture
    def mock_contract(self) -> TaskContract:
        return TaskContract(
            user_request="Perform security audit and updates.",
            goal="Security audit",
            risk_level=RiskLevel.LOW,
            success_criteria=[{"description": "Task completed", "verifier_type": "manual"}],
        )

    @pytest.fixture
    def mock_report(self) -> ReconciliationReport:
        return ReconciliationReport(
            task_id="task_123",
            status=ReconciliationStatus.COMPLETE,
        )

    def test_low_risk_auto_approved(self, mock_contract, mock_report):
        mock_contract.risk_level = RiskLevel.LOW
        engine = PolicyEngine()
        decision = engine.evaluate(mock_contract, mock_report, [], [])
        assert decision.allow is True
        assert decision.requires_human is False
        assert "auto" in decision.reason.lower()

    def test_critical_risk_requires_human(self, mock_contract, mock_report):
        mock_contract.risk_level = RiskLevel.CRITICAL
        engine = PolicyEngine()
        decision = engine.evaluate(mock_contract, mock_report, [], [])
        assert decision.allow is False
        assert decision.requires_human is True
        assert "critical" in decision.reason.lower()

    def test_high_risk_requires_human(self, mock_contract, mock_report):
        mock_contract.risk_level = RiskLevel.HIGH
        engine = PolicyEngine()
        decision = engine.evaluate(mock_contract, mock_report, [], [])
        assert decision.allow is False
        assert decision.requires_human is True
        assert "high" in decision.reason.lower()

    def test_medium_risk_no_drift_auto_approved(self, mock_contract, mock_report):
        mock_contract.risk_level = RiskLevel.MEDIUM
        engine = PolicyEngine()
        decision = engine.evaluate(mock_contract, mock_report, [], [])
        assert decision.allow is True
        assert decision.requires_human is False

    def test_medium_risk_with_drift_requires_human(self, mock_contract, mock_report):
        mock_contract.risk_level = RiskLevel.MEDIUM
        mock_report.unmet_criteria = [
            UnmetCriterion(
                criterion_id="crit_1",
                description="Failed tests",
                evidence_quality=EvidenceQuality.ABSENT,
            )
        ]
        engine = PolicyEngine()
        decision = engine.evaluate(mock_contract, mock_report, [], [])
        assert decision.allow is False
        assert decision.requires_human is True
        assert "unmet" in decision.reason.lower()

    def test_protected_path_violation(self, mock_contract, mock_report):
        mock_contract.risk_level = RiskLevel.LOW
        
        # Setup file change event targeting protected config
        event = MagicMock()
        event.event_type = EventType.FILE_CHANGE
        event.input_summary = "/home/user/project/config/secrets.yaml"
        event.artifacts = []

        with patch.dict(os.environ, {"AEGIS_PROTECTED_PATHS": "/home/user/project/config"}):
            engine = PolicyEngine()
            decision = engine.evaluate(mock_contract, mock_report, [], [event])
            
            assert decision.allow is False
            assert decision.requires_human is True
            assert "protected path" in decision.reason.lower()


class TestPolicyEngineOPADelegation:
    @pytest.fixture
    def mock_contract(self) -> TaskContract:
        return TaskContract(
            user_request="OPA testing",
            goal="OPA test",
            risk_level=RiskLevel.MEDIUM,
            success_criteria=[{"description": "OPA gate", "verifier_type": "manual"}],
        )

    @pytest.fixture
    def mock_report(self) -> ReconciliationReport:
        return ReconciliationReport(
            task_id="task_opa",
            status=ReconciliationStatus.COMPLETE,
        )

    @patch("urllib.request.urlopen")
    def test_opa_delegate_success(self, mock_urlopen, mock_contract, mock_report):
        # Setup mock http response
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "result": {
                "allow": True,
                "requires_human": False,
                "reason": "Approved by central OPA agent"
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with patch.dict(os.environ, {"AEGIS_POLICY_ENGINE": "opa", "AEGIS_OPA_URL": "http://mock-opa:8181"}):
            engine = PolicyEngine()
            decision = engine.evaluate(mock_contract, mock_report, [], [])

            assert decision.allow is True
            assert decision.requires_human is False
            assert decision.reason == "Approved by central OPA agent"

    @patch("urllib.request.urlopen")
    def test_opa_delegate_fallback_on_error(self, mock_urlopen, mock_contract, mock_report):
        # Setup mock http response to fail
        mock_urlopen.side_effect = Exception("Connection refused")

        with patch.dict(os.environ, {"AEGIS_POLICY_ENGINE": "opa", "AEGIS_OPA_URL": "http://mock-opa:8181"}):
            engine = PolicyEngine()
            # Low risk should fallback to in-process and be auto-approved
            mock_contract.risk_level = RiskLevel.LOW
            decision = engine.evaluate(mock_contract, mock_report, [], [])

            assert decision.allow is True
            assert decision.requires_human is False
            assert "low-risk" in decision.reason.lower()
