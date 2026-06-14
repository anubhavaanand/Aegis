"""Integration tests checking the selector, adapters, runner, and audit log runtime matrix."""

from __future__ import annotations

# Apply Click patches for Python 3.14+ before importing typer/cli
import click
if not hasattr(click.Choice, "__class_getitem__"):
    click.Choice.__class_getitem__ = classmethod(lambda cls, item: cls)
if not hasattr(click.Parameter, "_aegis_patched"):
    _orig_make_metavar = click.Parameter.make_metavar
    click.Parameter.make_metavar = lambda self, ctx=None: _orig_make_metavar(self)
    click.Parameter._aegis_patched = True

import os
import tempfile
import pytest
from pathlib import Path
from typer.testing import CliRunner

from aegis.runner import AegisLoopRunner
from aegis.audit_logger import AuditLogger
from aegis.cli import app
from adapters.runtime_selector import RuntimeSelector


class TestIntegrationMatrix:
    @pytest.fixture
    def temp_audit_dir(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.parametrize("runtime_name, expected_agent_id", [
        ("gemini", "gemini-cli-agent"),
        ("opencode", "opencode-agent"),
        ("antigravity", "antigravity-cli-agent"),
    ])
    def test_runner_matrix_simulated(self, runtime_name, expected_agent_id, temp_audit_dir):
        # 1. Resolve adapter
        adapter = RuntimeSelector.get_adapter(runtime_name, use_simulated=True)
        assert adapter.agent_id == expected_agent_id

        # 2. Run the loop runner
        runner = AegisLoopRunner(
            worker_adapter=adapter,
            workspace=None,
            max_retries=2,
            audit_dir=temp_audit_dir,
        )

        res = runner.run(
            "Fix login vulnerability, run tests, and open PR",
            auto_approve=True,
        )

        # 3. Assert correctness of output schema
        assert res["contract"] is not None
        assert res["initial_report"] is not None
        assert res["final_report"] is not None
        assert res["audit_log_path"] is not None
        
        # 4. Verify audit logger stored the correct runtime name
        logger = AuditLogger(audit_dir=temp_audit_dir)
        report_data = logger.get_report(res["contract"].task_id)
        assert report_data is not None
        assert report_data["runtime"] == expected_agent_id
        
        # 5. List audits showing runtime
        reports = logger.list_reports()
        assert len(reports) == 1
        assert reports[0]["runtime"] == expected_agent_id

    def test_cli_list_audits_filtering(self, temp_audit_dir):
        # Generate two logs for different runtimes
        for rt in ["gemini", "opencode"]:
            adapter = RuntimeSelector.get_adapter(rt, use_simulated=True)
            runner = AegisLoopRunner(
                worker_adapter=adapter,
                workspace=None,
                max_retries=1,
                audit_dir=temp_audit_dir,
            )
            runner.run("Simple task", auto_approve=True)

        runner = CliRunner()
        
        # Filter list-audits by gemini
        result_gemini = runner.invoke(
            app,
            ["list-audits", "--audit-dir", str(temp_audit_dir), "--runtime", "gemini"]
        )
        assert result_gemini.exit_code == 0
        assert "gemini-cli" in result_gemini.stdout
        assert "opencode" not in result_gemini.stdout

        # Filter list-audits by opencode
        result_opencode = runner.invoke(
            app,
            ["list-audits", "--audit-dir", str(temp_audit_dir), "--runtime", "opencode"]
        )
        assert result_opencode.exit_code == 0
        assert "opencode" in result_opencode.stdout
        assert "gemini-cli" not in result_opencode.stdout

