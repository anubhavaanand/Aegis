"""Tests for SemanticVerifier including mock API calls and fallback modes."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest

from aegis.evidence_model import (
    EvidenceEvent,
    EvidenceSummary,
    EventStatus,
    EventType,
    ReconciliationReport,
    ReconciliationStatus,
    SemanticVerificationResult,
    SuccessCriterion,
    TaskContract,
    VerifierType,
)
from aegis.semantic_verifier import SemanticVerifier


class TestSemanticVerifier:
    @pytest.fixture
    def sample_contract(self) -> TaskContract:
        return TaskContract(
            user_request="Refactor the user database module and add unit tests.",
            goal="Refactor user database module and add unit tests.",
            success_criteria=[
                SuccessCriterion(
                    criterion_id="crit_1",
                    description="Source code diff exists with changes",
                    verifier_type=VerifierType.FILE_DIFF,
                ),
                SuccessCriterion(
                    criterion_id="crit_2",
                    description="Tests pass",
                    verifier_type=VerifierType.TEST_PASS,
                ),
            ],
        )

    @pytest.fixture
    def sample_report(self) -> ReconciliationReport:
        return ReconciliationReport(
            task_id="test_task_id",
            status=ReconciliationStatus.COMPLETE,
            evidence_summary=EvidenceSummary(
                total_events=5,
                successful_events=5,
                tool_calls=2,
                file_changes=1,
                test_results=2,
            ),
        )

    def test_verify_disabled_by_default(self, sample_contract, sample_report):
        # By default, AEGIS_SEMANTIC_VERIFY is not set
        with patch.dict(os.environ, {}, clear=True):
            verifier = SemanticVerifier()
            result = verifier.verify(sample_contract, [], sample_report)
            
            assert isinstance(result, SemanticVerificationResult)
            assert result.verdict == "WARN"
            assert result.semantic_score == 0.5
            assert "skipped" in result.reasoning.lower()

    def test_verify_missing_api_key(self, sample_contract, sample_report):
        with patch.dict(os.environ, {"AEGIS_SEMANTIC_VERIFY": "true"}, clear=True):
            verifier = SemanticVerifier()
            result = verifier.verify(sample_contract, [], sample_report)
            
            assert result.verdict == "WARN"
            assert result.semantic_score == 0.5
            assert "skipped" in result.reasoning.lower()

    def test_verify_successful_api_call(self, sample_contract, sample_report):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"semantic_score": 0.9, "reasoning": "Tasks were mostly completed, but docs are missing.", "missed_intent": ["Add API documentation"], "verdict": "PASS"}'
        mock_client.models.generate_content.return_value = mock_response

        # Mock the entire google.genai module
        with patch.dict(os.environ, {"AEGIS_SEMANTIC_VERIFY": "true", "GOOGLE_API_KEY": "fake-key"}):
            with patch("google.genai.Client", return_value=mock_client):
                verifier = SemanticVerifier()
                result = verifier.verify(sample_contract, [], sample_report)

                assert isinstance(result, SemanticVerificationResult)
                assert result.semantic_score == 0.9
                assert result.verdict == "PASS"
                assert "missing" in result.reasoning
                assert result.missed_intent == ["Add API documentation"]
                
                # Check that client generate_content was called
                mock_client.models.generate_content.assert_called_once()

    def test_verify_api_error_fallback(self, sample_contract, sample_report):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API connection timed out")

        with patch.dict(os.environ, {"AEGIS_SEMANTIC_VERIFY": "true", "GOOGLE_API_KEY": "fake-key"}):
            with patch("google.genai.Client", return_value=mock_client):
                verifier = SemanticVerifier()
                result = verifier.verify(sample_contract, [], sample_report)

                # Should fallback to WARN/0.5
                assert isinstance(result, SemanticVerificationResult)
                assert result.verdict == "WARN"
                assert result.semantic_score == 0.5
                assert "failed: API connection timed out" in result.reasoning
