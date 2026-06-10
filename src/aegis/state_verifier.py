"""
Aegis State Verifier

Pluggable verifiers that check whether claimed outcomes are actually true
by inspecting real system state: file diffs, test results, documentation
sections, PR existence, and command output.

Each verifier takes a SuccessCriterion and collected EvidenceEvents and
returns a VerificationResult with quality scoring.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Protocol

from .evidence_model import (
    EvidenceEvent,
    EvidenceQuality,
    EventStatus,
    EventType,
    SuccessCriterion,
    VerifierType,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class VerificationResult:
    """The outcome of running a verifier against a success criterion."""

    def __init__(
        self,
        criterion_id: str,
        passed: bool,
        quality: EvidenceQuality,
        notes: str = "",
    ) -> None:
        self.criterion_id = criterion_id
        self.passed = passed
        self.quality = quality
        self.notes = notes

    def __repr__(self) -> str:
        return (
            f"<VerificationResult criterion={self.criterion_id!r} "
            f"passed={self.passed} quality={self.quality!r}>"
        )


# ---------------------------------------------------------------------------
# Verifier protocol
# ---------------------------------------------------------------------------


class Verifier(Protocol):
    """Protocol that all verifiers must implement."""

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        ...


# ---------------------------------------------------------------------------
# Individual verifiers
# ---------------------------------------------------------------------------


class FileDiffVerifier:
    """Verifies that at least one file was changed (git diff or file_change events)."""

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        # Check evidence events first
        file_change_events = [
            e for e in events
            if e.event_type == EventType.FILE_CHANGE and e.status == EventStatus.SUCCESS
        ]
        if file_change_events:
            return VerificationResult(
                criterion.criterion_id,
                passed=True,
                quality=EvidenceQuality.STRONG,
                notes=f"{len(file_change_events)} file change event(s) found in trace",
            )

        # Fall back to git diff on workspace
        if workspace and (workspace / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "diff", "--stat"],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.stdout.strip():
                    return VerificationResult(
                        criterion.criterion_id,
                        passed=True,
                        quality=EvidenceQuality.STRONG,
                        notes=f"git diff shows changes: {result.stdout.strip()[:200]}",
                    )
                # Check staged
                result2 = subprocess.run(
                    ["git", "diff", "--cached", "--stat"],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result2.stdout.strip():
                    return VerificationResult(
                        criterion.criterion_id,
                        passed=True,
                        quality=EvidenceQuality.WEAK,
                        notes="Staged changes found (not yet committed)",
                    )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return VerificationResult(
            criterion.criterion_id,
            passed=False,
            quality=EvidenceQuality.ABSENT,
            notes="No file change events in trace and no git diff found",
        )


class TestPassVerifier:
    """Verifies that tests passed by inspecting test_result evidence events."""

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        test_events = [
            e for e in events
            if e.event_type == EventType.TEST_RESULT
        ]
        if not test_events:
            # Try to find command events that look like test runs
            test_cmds = [
                e for e in events
                if e.event_type == EventType.COMMAND
                and any(kw in e.input_summary.lower() for kw in ["pytest", "test", "jest", "mocha"])
            ]
            if test_cmds:
                passing = [e for e in test_cmds if e.status == EventStatus.SUCCESS]
                if passing:
                    return VerificationResult(
                        criterion.criterion_id,
                        passed=True,
                        quality=EvidenceQuality.WEAK,
                        notes="Test command completed successfully (weak: no structured test report)",
                    )
                return VerificationResult(
                    criterion.criterion_id,
                    passed=False,
                    quality=EvidenceQuality.WEAK,
                    notes="Test command found but reported failure",
                )
            return VerificationResult(
                criterion.criterion_id,
                passed=False,
                quality=EvidenceQuality.ABSENT,
                notes="No test execution events found in trace",
            )

        failed = [e for e in test_events if e.status == EventStatus.FAILURE]
        if failed:
            return VerificationResult(
                criterion.criterion_id,
                passed=False,
                quality=EvidenceQuality.STRONG,
                notes=f"{len(failed)} test event(s) failed",
            )
        return VerificationResult(
            criterion.criterion_id,
            passed=True,
            quality=EvidenceQuality.STRONG,
            notes=f"All {len(test_events)} test event(s) passed",
        )


class DocSectionVerifier:
    """Verifies that documentation was updated."""

    DOC_PATTERNS = re.compile(
        r"\.(md|rst|txt|adoc)$", re.I
    )

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        # Check for doc file changes in evidence
        doc_changes = [
            e for e in events
            if e.event_type == EventType.FILE_CHANGE
            and e.status == EventStatus.SUCCESS
            and any(
                self.DOC_PATTERNS.search(a.path or "")
                for a in e.artifacts
                if a.path
            )
        ]
        if doc_changes:
            return VerificationResult(
                criterion.criterion_id,
                passed=True,
                quality=EvidenceQuality.STRONG,
                notes=f"{len(doc_changes)} documentation file(s) updated",
            )

        # Check workspace for recently modified doc files
        if workspace:
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=AM"],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                doc_files = [
                    f for f in result.stdout.splitlines()
                    if self.DOC_PATTERNS.search(f)
                ]
                if doc_files:
                    return VerificationResult(
                        criterion.criterion_id,
                        passed=True,
                        quality=EvidenceQuality.WEAK,
                        notes=f"Doc files found in git diff: {', '.join(doc_files)}",
                    )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return VerificationResult(
            criterion.criterion_id,
            passed=False,
            quality=EvidenceQuality.ABSENT,
            notes="No documentation changes found in trace or git diff",
        )


class PRExistsVerifier:
    """Verifies that a pull request was created (via evidence artifacts)."""

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        pr_events = [
            e for e in events
            if e.event_type in (EventType.EXTERNAL_ACTION, EventType.COMMAND)
            and any(
                "pr" in (a.type or "").lower() or
                "pull" in (a.url or "").lower() or
                "github.com" in (a.url or "").lower()
                for a in e.artifacts
            )
        ]
        if pr_events:
            pr = pr_events[0]
            url = next(
                (a.url for a in pr.artifacts if a.url), "unknown"
            )
            return VerificationResult(
                criterion.criterion_id,
                passed=True,
                quality=EvidenceQuality.STRONG,
                notes=f"PR artifact found: {url}",
            )

        # Check for gh CLI output in command events
        gh_cmds = [
            e for e in events
            if e.event_type == EventType.COMMAND
            and "gh" in e.input_summary.lower()
            and e.status == EventStatus.SUCCESS
        ]
        if gh_cmds:
            return VerificationResult(
                criterion.criterion_id,
                passed=True,
                quality=EvidenceQuality.WEAK,
                notes="gh CLI command succeeded (weak: no PR URL in artifacts)",
            )

        return VerificationResult(
            criterion.criterion_id,
            passed=False,
            quality=EvidenceQuality.ABSENT,
            notes="No PR creation evidence found in trace",
        )


class CommandOutputVerifier:
    """Verifies a criterion by checking command output events."""

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        expected_pattern = criterion.verifier_config.get("expected_pattern", "")
        cmd_events = [
            e for e in events
            if e.event_type == EventType.COMMAND
        ]
        if not cmd_events:
            return VerificationResult(
                criterion.criterion_id,
                passed=False,
                quality=EvidenceQuality.ABSENT,
                notes="No command execution events found in trace",
            )

        for ev in cmd_events:
            if ev.status == EventStatus.SUCCESS:
                if not expected_pattern or re.search(
                    expected_pattern, ev.output_summary, re.I
                ):
                    return VerificationResult(
                        criterion.criterion_id,
                        passed=True,
                        quality=EvidenceQuality.STRONG,
                        notes=f"Command succeeded: {ev.input_summary[:100]}",
                    )

        return VerificationResult(
            criterion.criterion_id,
            passed=False,
            quality=EvidenceQuality.WEAK,
            notes="Command events exist but none matched expected output",
        )


class ManualVerifier:
    """Fallback verifier — marks criterion as weak unless explicitly confirmed."""

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        return VerificationResult(
            criterion.criterion_id,
            passed=False,
            quality=EvidenceQuality.ABSENT,
            notes="Manual verification required — no automated verifier for this criterion",
        )


# ---------------------------------------------------------------------------
# StateVerifier — orchestrates all verifiers
# ---------------------------------------------------------------------------


class StateVerifier:
    """
    Orchestrates pluggable verifiers against a set of success criteria.

    For each criterion in a TaskContract, dispatches to the appropriate
    verifier based on verifier_type.
    """

    _VERIFIER_MAP: dict[str, object] = {}

    def __init__(self, workspace: str | Path | None = None) -> None:
        self.workspace = Path(workspace) if workspace else None
        self._verifiers: dict[VerifierType, object] = {
            VerifierType.FILE_DIFF: FileDiffVerifier(),
            VerifierType.TEST_PASS: TestPassVerifier(),
            VerifierType.DOC_SECTION: DocSectionVerifier(),
            VerifierType.PR_EXISTS: PRExistsVerifier(),
            VerifierType.COMMAND_OUTPUT: CommandOutputVerifier(),
            VerifierType.MANUAL: ManualVerifier(),
        }

    def verify_all(
        self,
        criteria: list[SuccessCriterion],
        events: list[EvidenceEvent],
    ) -> list[VerificationResult]:
        """
        Run all verifiers and return one result per criterion.
        """
        results = []
        for criterion in criteria:
            vtype = VerifierType(criterion.verifier_type)
            verifier = self._verifiers.get(vtype, ManualVerifier())
            result = verifier.verify(criterion, events, self.workspace)  # type: ignore[union-attr]
            results.append(result)
        return results
