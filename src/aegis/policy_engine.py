"""
Aegis Policy Engine

Evaluates whether proposed repair plans are allowed to run, require human
approval, or must be blocked immediately. Supports in-process risk and
protected path rules, as well as REST-based delegation to Open Policy Agent (OPA).
"""

from __future__ import annotations

import os
import json
import logging
import urllib.request
from pathlib import Path
from typing import Any
from pydantic import BaseModel

from .evidence_model import (
    EventType,
    ReconciliationReport,
    RepairStep,
    TaskContract,
)

logger = logging.getLogger("aegis.policy_engine")


class PolicyDecision(BaseModel):
    """The outcome of policy evaluation."""

    allow: bool
    requires_human: bool
    reason: str


class PolicyEngine:
    """
    Evaluates repair actions against safety and compliance policies.
    """

    def __init__(self, opa_url: str | None = None) -> None:
        self.opa_url = opa_url or os.environ.get("AEGIS_OPA_URL", "http://localhost:8181")

    def evaluate(
        self,
        contract: TaskContract,
        report: ReconciliationReport,
        repair_steps: list[RepairStep],
        events: list[Any],
    ) -> PolicyDecision:
        """
        Evaluate if the repair plan violates any policy.
        """
        # Determine modified paths from events & repair steps
        modified_paths = self._extract_modified_paths(events, repair_steps)

        # Build policy input payload
        risk_val = contract.risk_level.value if hasattr(contract.risk_level, "value") else str(contract.risk_level)
        policy_input = {
            "risk_level": risk_val.lower(),
            "unmet_criteria_count": len(report.unmet_criteria),
            "weak_evidence_count": len(report.weak_evidence),
            "missed_capabilities_count": len(report.missed_capabilities),
            "modified_paths": modified_paths,
            "repair_steps_count": len(repair_steps),
        }

        # Check if OPA delegation is enabled
        engine_mode = os.environ.get("AEGIS_POLICY_ENGINE", "").lower()
        if engine_mode == "opa":
            decision = self._delegate_to_opa(policy_input)
            if decision is not None:
                return decision
            logger.warning("OPA policy check failed or returned invalid result. Falling back to in-process rules.")

        # Fallback to in-process rules
        return self._evaluate_in_process(contract, report, modified_paths)

    def _extract_modified_paths(self, events: list[Any], repair_steps: list[RepairStep]) -> list[str]:
        paths = set()
        for e in events:
            # Check event type and input summary / artifacts
            e_type = getattr(e, "event_type", None)
            if e_type in ("file_change", EventType.FILE_CHANGE):
                input_sum = getattr(e, "input_summary", "")
                if input_sum:
                    paths.add(input_sum)
            # Check artifacts
            artifacts = getattr(e, "artifacts", [])
            for art in artifacts:
                art_type = getattr(art, "type", None)
                art_path = getattr(art, "path", None)
                if art_type == "file" and art_path:
                    paths.add(art_path)

        # Check repair steps metadata for paths if any
        for step in repair_steps:
            target_file = step.metadata.get("target_file")
            if target_file:
                paths.add(str(target_file))

        return sorted(list(paths))

    def _delegate_to_opa(self, policy_input: dict[str, Any]) -> PolicyDecision | None:
        """
        Call OPA REST API with standard JSON body format.
        """
        url = f"{self.opa_url.rstrip('/')}/v1/data/aegis/policy/decision"
        payload = {"input": policy_input}
        
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Short timeout to keep fallback fast
            with urllib.request.urlopen(req, timeout=3.0) as response:
                if response.status == 200:
                    res_body = json.loads(response.read().decode("utf-8"))
                    result = res_body.get("result")
                    if isinstance(result, dict) and "allow" in result and "requires_human" in result:
                        return PolicyDecision(
                            allow=bool(result["allow"]),
                            requires_human=bool(result["requires_human"]),
                            reason=str(result.get("reason", "Decided by OPA Policy Agent")),
                        )
        except Exception as e:
            logger.warning(f"OPA REST request failed: {e}")
            
        return None

    def _evaluate_in_process(
        self,
        contract: TaskContract,
        report: ReconciliationReport,
        modified_paths: list[str],
    ) -> PolicyDecision:
        """
        Default in-process policy rules.
        """
        # 1. Protected paths check
        protected_env = os.environ.get("AEGIS_PROTECTED_PATHS", "")
        if protected_env:
            protected_paths = [p.strip() for p in protected_env.split(",") if p.strip()]
            for path in modified_paths:
                for p in protected_paths:
                    # Match if the path is relative to the protected prefix or contains it
                    try:
                        resolved_path = Path(path).resolve()
                        resolved_p = Path(p).resolve()
                        if resolved_path.is_relative_to(resolved_p) or p in path:
                            return PolicyDecision(
                                allow=False,
                                requires_human=True,
                                reason=f"Modification of protected path detected: '{path}' matching pattern '{p}'",
                            )
                    except Exception:
                        if p in path:
                            return PolicyDecision(
                                allow=False,
                                requires_human=True,
                                reason=f"Modification of protected path detected: '{path}' matching pattern '{p}'",
                            )

        # 2. Risk level checks
        risk_val = contract.risk_level.value if hasattr(contract.risk_level, "value") else str(contract.risk_level)
        risk = risk_val.lower()
        if risk == "critical":
            return PolicyDecision(
                allow=False,
                requires_human=True,
                reason="Critical-risk tasks require mandatory human oversight",
            )
        elif risk == "high":
            return PolicyDecision(
                allow=False,
                requires_human=True,
                reason="High-risk tasks require human oversight before corrective actions are applied",
            )
        elif risk == "medium":
            # Require human oversight if there is actual drift / unmet criteria
            if report.unmet_criteria:
                return PolicyDecision(
                    allow=False,
                    requires_human=True,
                    reason="Medium-risk tasks with unmet success criteria require human approval",
                )
            # Else, allow automated repair if only weak evidence / missed capabilities exist
            return PolicyDecision(
                allow=True,
                requires_human=False,
                reason="Medium-risk tasks with no unmet criteria are automatically approved",
            )
        else:
            # Low risk tasks are auto-approved
            return PolicyDecision(
                allow=True,
                requires_human=False,
                reason="Low-risk tasks are automatically approved",
            )
