"""
Aegis Capability Auditor

Detects capabilities that were AVAILABLE in the registry but NOT USED
during task execution, and assesses whether their absence represents
a suboptimal or deficient execution path.

This is one of Aegis's key differentiating features:
  - A task completion checker asks "was it done?"
  - Aegis also asks "was it done with the best available tools?"
"""

from __future__ import annotations

from .capability_registry import CapabilityRegistry
from .evidence_model import (
    EvidenceEvent,
    MissedCapability,
    MissedCapabilityImpact,
    TaskContract,
    VerifierType,
)
from .state_verifier import VerificationResult

# ---------------------------------------------------------------------------
# Mapping: success criterion verifier type → tags of capabilities that should
# have been used to satisfy it.
# ---------------------------------------------------------------------------

_CRITERION_TO_TAGS: dict[str, list[str]] = {
    VerifierType.FILE_DIFF.value: ["file", "write", "edit", "patch"],
    VerifierType.TEST_PASS.value: ["test", "pytest", "verify"],
    VerifierType.DOC_SECTION.value: ["docs", "documentation", "update"],
    VerifierType.PR_EXISTS.value: ["pr", "github", "git"],
    VerifierType.COMMAND_OUTPUT.value: ["shell", "command", "build"],
    VerifierType.MANUAL.value: [],
}

# Impact heuristics: how important was this missed capability?
_IMPACT_MAP: dict[str, MissedCapabilityImpact] = {
    VerifierType.PR_EXISTS.value: MissedCapabilityImpact.CRITICAL,
    VerifierType.TEST_PASS.value: MissedCapabilityImpact.SIGNIFICANT,
    VerifierType.DOC_SECTION.value: MissedCapabilityImpact.MINOR,
    VerifierType.FILE_DIFF.value: MissedCapabilityImpact.CRITICAL,
    VerifierType.COMMAND_OUTPUT.value: MissedCapabilityImpact.SIGNIFICANT,
    VerifierType.MANUAL.value: MissedCapabilityImpact.MINOR,
}


class CapabilityAuditor:
    """
    Audits task execution for missed or underutilized capabilities.

    For each UNMET or WEAKLY-MET criterion, the auditor:
      1. Identifies which capability tags should have been used
      2. Queries the registry for matching capabilities
      3. Checks if those capabilities appear in the evidence
      4. If not, reports them as missed (with impact rating)

    Also performs a general audit: capabilities used by the agent that
    do NOT appear in the registry (potentially unknown/unsafe tools).
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def audit(
        self,
        contract: TaskContract,
        events: list[EvidenceEvent],
        verification_results: list[VerificationResult],
    ) -> list[MissedCapability]:
        """
        Return a list of capabilities that were available but not used.
        """
        used_capability_ids = {
            e.capability_id for e in events if e.capability_id
        }
        used_capability_names = {
            e.input_summary.split()[0].lower()
            for e in events
            if e.input_summary
        }

        missed: list[MissedCapability] = []
        seen_capability_ids: set[str] = set()

        # 1. For each unmet/weak criterion, find capabilities that should have been used
        failed_results = [
            r for r in verification_results
            if not r.passed or r.quality.value == "weak"  # type: ignore[union-attr]
        ]

        criterion_map = {
            c.criterion_id: c for c in contract.success_criteria
        }

        for result in failed_results:
            criterion = criterion_map.get(result.criterion_id)
            if not criterion:
                continue

            verifier_type = str(criterion.verifier_type)
            relevant_tags = _CRITERION_TO_TAGS.get(verifier_type, [])
            if not relevant_tags:
                continue

            # Find registry capabilities matching these tags
            # Sort by risk level ascending (prefer safest / most specific)
            candidates = self._registry.by_tags(relevant_tags)
            candidates.sort(key=lambda c: ["low", "medium", "high", "critical"].index(
                c.risk_level if isinstance(c.risk_level, str) else c.risk_level.value
            ))

            # Report at most the single best unused capability per criterion
            for cap in candidates:
                if cap.capability_id in seen_capability_ids:
                    continue
                # Was this capability actually used?
                if (
                    cap.capability_id in used_capability_ids
                    or cap.name.lower() in used_capability_names
                ):
                    continue

                impact = _IMPACT_MAP.get(
                    verifier_type, MissedCapabilityImpact.MINOR
                )
                missed.append(
                    MissedCapability(
                        capability_id=cap.capability_id,
                        name=cap.name,
                        reason=(
                            f"Criterion '{criterion.description}' was not satisfied. "
                            f"'{cap.name}' ({cap.description}) was available "
                            f"and tagged for this use case but was not used."
                        ),
                        impact=impact,
                        metadata={"criterion_id": criterion.criterion_id},
                    )
                )
                seen_capability_ids.add(cap.capability_id)
                break  # Only report the best candidate per criterion

        # 2. General suboptimality: capabilities used that have better alternatives
        # (future extension — placeholder for now)

        return missed

    def audit_unknown_tools(
        self,
        events: list[EvidenceEvent],
    ) -> list[str]:
        """
        Return capability IDs / names used during execution that are NOT
        in the registry. These may represent unknown or unsafe tools.
        """
        registered_ids = {
            cap.capability_id for cap in self._registry.all()
        }
        registered_names = {
            cap.name.lower() for cap in self._registry.all()
        }
        unknown = []
        for event in events:
            if event.capability_id and event.capability_id not in registered_ids:
                unknown.append(event.capability_id)
            elif (
                not event.capability_id
                and event.input_summary
                and event.input_summary.split()[0].lower() not in registered_names
            ):
                unknown.append(f"unknown:{event.input_summary.split()[0][:40]}")
        return list(set(unknown))
