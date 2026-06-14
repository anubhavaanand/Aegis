"""
Aegis Semantic Verifier

Uses gemini-2.5-flash as an LLM-as-Judge to check if a task was completed
in spirit, not just literally or technically.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .evidence_model import (
    EvidenceEvent,
    ReconciliationReport,
    SemanticVerificationResult,
    TaskContract,
)


class SemanticVerifier:
    """
    Evaluates execution semantics using LLM-as-Judge structured outputs.
    """

    def verify(
        self,
        contract: TaskContract,
        evidence: list[EvidenceEvent],
        reconciliation_report: ReconciliationReport,
    ) -> SemanticVerificationResult:
        """
        Run semantic verification on the task execution telemetry.
        """
        enabled = os.environ.get("AEGIS_SEMANTIC_VERIFY", "").lower() == "true"
        api_key = os.environ.get("GOOGLE_API_KEY")

        if not enabled or not api_key:
            return SemanticVerificationResult(
                semantic_score=0.5,
                verdict="WARN",
                reasoning="Semantic verification skipped.",
                missed_intent=[],
            )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client()

            # Prepare telemetry summary for LLM context
            evidence_summary = (
                f"Total Events: {reconciliation_report.evidence_summary.total_events}, "
                f"Tool Calls: {reconciliation_report.evidence_summary.tool_calls}, "
                f"File Changes: {reconciliation_report.evidence_summary.file_changes}, "
                f"Test Results: {reconciliation_report.evidence_summary.test_results}"
            )

            drift_summary = ""
            if reconciliation_report.unmet_criteria:
                drift_summary += "Unmet Criteria:\n"
                for c in reconciliation_report.unmet_criteria:
                    drift_summary += f"- {c.description} (Quality: {c.evidence_quality}) | {c.notes}\n"
            if reconciliation_report.weak_evidence:
                drift_summary += "Weak Evidence:\n"
                for c in reconciliation_report.weak_evidence:
                    drift_summary += f"- {c.description} (Quality: {c.evidence_quality}) | {c.notes}\n"
            if not drift_summary:
                drift_summary = "All success criteria were technically satisfied."

            prompt = f"""
You are an expert task auditor. Given the following:
- Task request: {contract.user_request}
- Success criteria: {[c.description for c in contract.success_criteria]}
- Evidence summary: {evidence_summary}
- Drift findings: {drift_summary}

Evaluate whether the task was completed in spirit, not just technically.
Return a semantic score (0=complete failure, 1=perfect), your reasoning, any missed intent, and a verdict.
"""

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SemanticVerificationResult,
                    temperature=0.1,
                ),
            )

            return SemanticVerificationResult.model_validate(json.loads(response.text))

        except Exception as e:
            # Fallback to a neutral result on any failure
            return SemanticVerificationResult(
                semantic_score=0.5,
                verdict="WARN",
                reasoning=f"Semantic verification failed: {e}",
                missed_intent=[],
            )
