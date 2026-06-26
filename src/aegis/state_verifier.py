"""
Aegis State Verifier

Pluggable verifiers that check whether claimed outcomes are actually true
by inspecting real system state: file diffs, test results, documentation
sections, PR existence, and command output.

Each verifier takes a SuccessCriterion and collected EvidenceEvents and
returns a VerificationResult with quality scoring.
"""

from __future__ import annotations

import ast
import re
import subprocess
import xml.etree.ElementTree as ET
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
        if workspace:
            safe_root = workspace.resolve()
            if (safe_root / ".git").exists():
                try:
                    result = subprocess.run(
                        ["git", "diff", "--stat"],
                        cwd=safe_root,
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
                        cwd=safe_root,
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
    """Verifies that tests passed programmatically using JUnit XML reports or trace events."""

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        # Programmatic check: Read and parse JUnit XML report if specified in configuration
        junit_xml_path = criterion.verifier_config.get("junit_xml_path")
        if junit_xml_path and workspace:
            try:
                safe_root = workspace.resolve()
                target_xml = (safe_root / junit_xml_path).resolve()

                # Workspace isolation guard
                if not target_xml.is_relative_to(safe_root):
                    return VerificationResult(
                        criterion.criterion_id,
                        passed=False,
                        quality=EvidenceQuality.ABSENT,
                        notes=f"Security Block: JUnit XML path {junit_xml_path} attempts workspace escape.",
                    )

                if target_xml.exists() and target_xml.is_file():
                    tree = ET.parse(target_xml)
                    root = tree.getroot()

                    failures = 0
                    errors = 0
                    tests = 0

                    if root.tag == "testsuite":
                        failures = int(root.attrib.get("failures", 0))
                        errors = int(root.attrib.get("errors", 0))
                        tests = int(root.attrib.get("tests", 0))
                    else:
                        for suite in root.findall(".//testsuite"):
                            failures += int(suite.attrib.get("failures", 0))
                            errors += int(suite.attrib.get("errors", 0))
                            tests += int(suite.attrib.get("tests", 0))

                    if tests == 0:
                        return VerificationResult(
                            criterion.criterion_id,
                            passed=False,
                            quality=EvidenceQuality.WEAK,
                            notes=f"JUnit XML parse found 0 tests executed in {junit_xml_path}",
                        )

                    if failures > 0 or errors > 0:
                        return VerificationResult(
                            criterion.criterion_id,
                            passed=False,
                            quality=EvidenceQuality.STRONG,
                            notes=f"Programmatic failure verification: {failures} failures, {errors} errors in {junit_xml_path}",
                        )

                    return VerificationResult(
                        criterion.criterion_id,
                        passed=True,
                        quality=EvidenceQuality.STRONG,
                        notes=f"Programmatic success verification: {tests} tests passed in {junit_xml_path}",
                    )
            except Exception as e:
                # Log parser error but fallback gracefully to traces
                pass

        # Fallback 2: Check trace event metrics
        test_events = [e for e in events if e.event_type == EventType.TEST_RESULT]
        if not test_events:
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
    """Verifies that documentation was updated programmatically (AST or Markdown structure)."""

    DOC_PATTERNS = re.compile(r"\.(md|rst|txt|adoc)$", re.I)

    def verify(
        self,
        criterion: SuccessCriterion,
        events: list[EvidenceEvent],
        workspace: Path | None,
    ) -> VerificationResult:
        # Programmatic check: Run structured AST/Markdown parsing if target_file is configured
        doc_file_path = criterion.verifier_config.get("doc_file")
        if doc_file_path and workspace:
            try:
                safe_root = workspace.resolve()
                target_doc = (safe_root / doc_file_path).resolve()

                # Workspace isolation guard
                if not target_doc.is_relative_to(safe_root):
                    return VerificationResult(
                        criterion.criterion_id,
                        passed=False,
                        quality=EvidenceQuality.ABSENT,
                        notes=f"Security Block: Doc path {doc_file_path} attempts workspace escape.",
                    )

                if target_doc.exists() and target_doc.is_file():
                    content = target_doc.read_text(encoding="utf-8")

                    # 1. AST Validation for Python files (validating API docs/docstrings)
                    if doc_file_path.endswith(".py"):
                        parsed = ast.parse(content)
                        required_fns = criterion.verifier_config.get("required_functions", [])
                        if required_fns:
                            missing_docs = []
                            for node in ast.walk(parsed):
                                if isinstance(node, ast.FunctionDef) and node.name in required_fns:
                                    docstring = ast.get_docstring(node)
                                    if not docstring or not docstring.strip():
                                        missing_docs.append(node.name)
                            if missing_docs:
                                return VerificationResult(
                                    criterion.criterion_id,
                                    passed=False,
                                    quality=EvidenceQuality.STRONG,
                                    notes=f"AST verification failed: Missing docstrings in target functions: {', '.join(missing_docs)} inside {doc_file_path}",
                                )
                            return VerificationResult(
                                criterion.criterion_id,
                                passed=True,
                                quality=EvidenceQuality.STRONG,
                                notes=f"AST verification passed: Docstrings exist for {', '.join(required_fns)} inside {doc_file_path}",
                            )

                    # 2. Section Heading check for Markdown
                    elif doc_file_path.endswith(".md"):
                        required_headers = criterion.verifier_config.get("required_headers", [])
                        if required_headers:
                            missing_headers = []
                            for header in required_headers:
                                header_pattern = re.compile(rf"^\s*#+\s+{re.escape(header)}\s*$", re.M | re.I)
                                if not header_pattern.search(content):
                                    missing_headers.append(header)
                            if missing_headers:
                                return VerificationResult(
                                    criterion.criterion_id,
                                    passed=False,
                                    quality=EvidenceQuality.STRONG,
                                    notes=f"Markdown verification failed: Missing structural headers: {', '.join(missing_headers)} in {doc_file_path}",
                                )
                            return VerificationResult(
                                criterion.criterion_id,
                                passed=True,
                                quality=EvidenceQuality.STRONG,
                                notes=f"Markdown verification passed: Found required headers in {doc_file_path}",
                            )
            except Exception as e:
                # Fallback on parse failure
                pass

        # Fallback to simple trace checking
        doc_changes = [
            e for e in events
            if e.event_type == EventType.FILE_CHANGE
            and e.status == EventStatus.SUCCESS
            and any(self.DOC_PATTERNS.search(a.path or "") for a in e.artifacts if a.path)
        ]
        if doc_changes:
            return VerificationResult(
                criterion.criterion_id,
                passed=True,
                quality=EvidenceQuality.STRONG,
                notes=f"{len(doc_changes)} documentation file(s) updated",
            )

        if workspace:
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=AM"],
                    cwd=workspace.resolve(),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                doc_files = [f for f in result.stdout.splitlines() if self.DOC_PATTERNS.search(f)]
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
            url = next((a.url for a in pr.artifacts if a.url), "unknown")
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
        cmd_events = [e for e in events if e.event_type == EventType.COMMAND]
        if not cmd_events:
            return VerificationResult(
                criterion.criterion_id,
                passed=False,
                quality=EvidenceQuality.ABSENT,
                notes="No command execution events found in trace",
            )

        for ev in cmd_events:
            if ev.status == EventStatus.SUCCESS:
                if not expected_pattern or re.search(expected_pattern, ev.output_summary, re.I):
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
