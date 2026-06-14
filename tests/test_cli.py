"""Tests for Aegis CLI commands and options."""

from __future__ import annotations

# Apply Python 3.14+ Click compatibility patches before importing typer
import click
if not hasattr(click.Choice, "__class_getitem__"):
    click.Choice.__class_getitem__ = classmethod(lambda cls, item: cls)
if not hasattr(click.Parameter, "_aegis_patched"):
    _orig_make_metavar = click.Parameter.make_metavar
    click.Parameter.make_metavar = lambda self, ctx=None: _orig_make_metavar(self)
    click.Parameter._aegis_patched = True

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from typer.testing import CliRunner

from aegis.cli import app


class TestAegisCLI:
    @pytest.fixture
    def cli_runner(self) -> CliRunner:
        return CliRunner()

    def test_discover_capabilities_command(self, cli_runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "manifest.json"
            
            # Setup a minimal mock mcp config file
            mcp_config = Path(tmpdir) / "mcp.json"
            mcp_config.write_text(json.dumps({
                "mcpServers": {
                    "test-server": {
                        "command": "echo",
                        "args": []
                    }
                }
            }))

            # Mock query to avoid running subprocess
            with patch("aegis.capability_registry.CapabilityRegistry._query_mcp_server_tools", return_value=[
                {"name": "test_tool", "description": "A test tool"}
            ]):
                result = cli_runner.invoke(
                    app,
                    [
                        "discover-capabilities",
                        "-c", str(mcp_config),
                        "-o", str(output_file)
                    ]
                )

                assert result.exit_code == 0
                assert output_file.exists()
                
                # Check manifest contents
                data = json.loads(output_file.read_text(encoding="utf-8"))
                assert "capabilities" in data
                caps = data["capabilities"]
                # Must have registered the discovered MCP tool plus built-ins
                discovered = [c for c in caps if c["capability_id"] == "mcp_test-server_test_tool"]
                assert len(discovered) == 1
                assert discovered[0]["name"] == "test_tool"
                assert discovered[0]["source"] == "test-server"

    @patch("aegis.cli.AegisLoopRunner")
    @patch("aegis.cli.ADKAdapter")
    def test_run_command_flags(self, mock_adapter, mock_runner_cls, cli_runner):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner

        with patch.dict(os.environ, {}, clear=True):
            # Invoke CLI run with flags
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "-r", "Run unit tests",
                    "--semantic",
                    "--policy", "opa"
                ]
            )

            assert result.exit_code == 0
            
            # Verify environment variables were set
            assert os.environ.get("AEGIS_SEMANTIC_VERIFY") == "true"
            assert os.environ.get("AEGIS_POLICY_ENGINE") == "opa"

            # Verify runner.run was called with correct arguments
            mock_runner.run.assert_called_once_with("Run unit tests", auto_approve=False)

    @patch("aegis.cli.AegisLoopRunner")
    @patch("aegis.cli.ADKAdapter")
    def test_run_command_flags_defaults(self, mock_adapter, mock_runner_cls, cli_runner):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner

        with patch.dict(os.environ, {}, clear=True):
            result = cli_runner.invoke(
                app,
                [
                    "run",
                    "-r", "Run unit tests"
                ]
            )

            assert result.exit_code == 0
            
            # Verify defaults
            assert os.environ.get("AEGIS_SEMANTIC_VERIFY") == "false"
            assert os.environ.get("AEGIS_POLICY_ENGINE") == "in-process"
