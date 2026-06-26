"""
Focused integration tests for the hardened StateVerifier features:
- Programmatic JUnit XML parsed verification.
- AST Python docstring semantic checks.
- Structural Markdown section headers checks.
- Strict path traversal mitigation checks.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import pytest

from aegis.evidence_model import (
    EvidenceEvent,
    EventStatus,
    EventType,
    EvidenceQuality,
    SuccessCriterion,
    VerifierType,
)
from aegis.state_verifier import StateVerifier


class TestStateVerifierHardened:
    def test_junit_xml_programmatic_success(self):
        verifier = StateVerifier()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            junit_file = workspace / "test_report.xml"
            
            # Formulate mock successful JUnit XML output
            junit_file.write_text(
                '<testsuites><testsuite name="pytest" failures="0" errors="0" tests="12"></testsuite></testsuites>',
                encoding="utf-8"
            )
            
            criterion = SuccessCriterion(
                description="Tests must pass",
                verifier_type=VerifierType.TEST_PASS,
                verifier_config={"junit_xml_path": "test_report.xml"}
            )
            
            result = verifier._verifiers[VerifierType.TEST_PASS].verify(criterion, [], workspace)
            
            assert result.passed is True
            assert result.quality == EvidenceQuality.STRONG
            assert "12 tests passed" in result.notes

    def test_junit_xml_programmatic_failure(self):
        verifier = StateVerifier()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            junit_file = workspace / "test_report.xml"
            
            # Formulate mock failing JUnit XML output
            junit_file.write_text(
                '<testsuite name="pytest" failures="2" errors="0" tests="12"></testsuite>',
                encoding="utf-8"
            )
            
            criterion = SuccessCriterion(
                description="Tests must pass",
                verifier_type=VerifierType.TEST_PASS,
                verifier_config={"junit_xml_path": "test_report.xml"}
            )
            
            result = verifier._verifiers[VerifierType.TEST_PASS].verify(criterion, [], workspace)
            
            assert result.passed is False
            assert result.quality == EvidenceQuality.STRONG
            assert "2 failures" in result.notes

    def test_ast_python_docstring_verification(self):
        verifier = StateVerifier()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            python_file = workspace / "auth.py"
            
            # Write a Python file containing complete docstrings
            python_file.write_text(
                'def validate_login():\n    """Validates login credentials."""\n    return True\n',
                encoding="utf-8"
            )
            
            criterion = SuccessCriterion(
                description="Verify docstring exists",
                verifier_type=VerifierType.DOC_SECTION,
                verifier_config={
                    "doc_file": "auth.py",
                    "required_functions": ["validate_login"]
                }
            )
            
            result = verifier._verifiers[VerifierType.DOC_SECTION].verify(criterion, [], workspace)
            
            assert result.passed is True
            assert result.quality == EvidenceQuality.STRONG
            assert "AST verification passed" in result.notes

    def test_ast_python_docstring_missing_failure(self):
        verifier = StateVerifier()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            python_file = workspace / "auth.py"
            
            # Write a Python function completely missing its docstring
            python_file.write_text(
                'def validate_login():\n    return True\n',
                encoding="utf-8"
            )
            
            criterion = SuccessCriterion(
                description="Verify docstring exists",
                verifier_type=VerifierType.DOC_SECTION,
                verifier_config={
                    "doc_file": "auth.py",
                    "required_functions": ["validate_login"]
                }
            )
            
            result = verifier._verifiers[VerifierType.DOC_SECTION].verify(criterion, [], workspace)
            
            assert result.passed is False
            assert result.quality == EvidenceQuality.STRONG
            assert "AST verification failed" in result.notes

    def test_markdown_header_verification(self):
        verifier = StateVerifier()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            md_file = workspace / "README.md"
            
            md_file.write_text(
                "# Project Title\n## Configuration\nInformation here.",
                encoding="utf-8"
            )
            
            criterion = SuccessCriterion(
                description="Verify headers exist",
                verifier_type=VerifierType.DOC_SECTION,
                verifier_config={
                    "doc_file": "README.md",
                    "required_headers": ["Configuration"]
                }
            )
            
            result = verifier._verifiers[VerifierType.DOC_SECTION].verify(criterion, [], workspace)
            
            assert result.passed is True
            assert result.quality == EvidenceQuality.STRONG
            assert "Markdown verification passed" in result.notes

    def test_state_verifier_workspace_escape_traversal_block(self):
        verifier = StateVerifier()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            
            # Test-attempt to read an XML file completely outside of the workspace tree
            criterion = SuccessCriterion(
                description="Ensure sandboxed traversal fails",
                verifier_type=VerifierType.TEST_PASS,
                verifier_config={"junit_xml_path": "../../../outside.xml"}
            )
            
            result = verifier._verifiers[VerifierType.TEST_PASS].verify(criterion, [], workspace)
            
            assert result.passed is False
            assert result.quality == EvidenceQuality.ABSENT
            assert "workspace escape" in result.notes