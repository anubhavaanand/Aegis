"""Tests for CapabilityRegistry MCP auto-discovery and manifests."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from aegis.capability_registry import CapabilityRegistry
from aegis.evidence_model import CapabilityType, RiskLevel


class TestCapabilityRegistryMCP:
    def test_discover_from_mcp_config_valid_file(self):
        # Create temp mcp config file
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "servers.json"
            config_data = {
                "mcpServers": {
                    "test-server": {
                        "command": "dummy_cmd",
                        "args": ["--arg1"],
                        "env": {"TEST_VAR": "123"}
                    }
                }
            }
            config_path.write_text(json.dumps(config_data))

            # Mock subprocess Popen
            mock_proc = MagicMock()
            mock_proc.stdin = MagicMock()
            
            # Simulate reading initialize response then tools/list response
            mock_proc.stdout.readline.side_effect = [
                json.dumps({"jsonrpc": "2.0", "id": 0, "result": {}}) + "\n",
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "tools": [
                            {"name": "fetch_data", "description": "Fetches dummy data"}
                        ]
                    }
                }) + "\n"
            ]

            registry = CapabilityRegistry()
            # Clear built-ins to isolate discovery test
            registry._store.clear()

            with patch("subprocess.Popen", return_value=mock_proc):
                registry.discover_from_mcp_config(str(config_path))

            # Check if fetch_data capability got registered
            cap = registry.get("mcp_test-server_fetch_data")
            assert cap is not None
            assert cap.name == "fetch_data"
            assert cap.type == CapabilityType.MCP
            assert cap.source == "test-server"
            assert cap.description == "Fetches dummy data"
            assert "mcp" in cap.tags
            assert cap.risk_level == RiskLevel.MEDIUM

    def test_discover_from_mcp_config_missing_file(self):
        registry = CapabilityRegistry()
        registry._store.clear()
        
        # Call with nonexistent path, should log and return cleanly without crashing
        registry.discover_from_mcp_config("/nonexistent/path/mcp.json")
        assert len(registry) == 0

    def test_discover_from_mcp_config_unreachable_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "servers.json"
            config_data = {
                "mcpServers": {
                    "broken-server": {
                        "command": "broken_cmd",
                        "args": []
                    }
                }
            }
            config_path.write_text(json.dumps(config_data))

            registry = CapabilityRegistry()
            registry._store.clear()

            # Popen throws FileNotFoundError/ConnectionError, must log warning and not crash
            with patch("subprocess.Popen", side_effect=FileNotFoundError("Executable not found")):
                registry.discover_from_mcp_config(str(config_path))

            assert len(registry) == 0

    def test_save_and_load_manifest(self):
        registry = CapabilityRegistry()
        # Ensure we have some items in the store
        assert len(registry) > 0

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            registry.save_capability_manifest(str(manifest_path))

            # Load it into a new empty registry
            new_registry = CapabilityRegistry()
            new_registry._store.clear()
            assert len(new_registry) == 0

            new_registry.load_capability_manifest(str(manifest_path))
            assert len(new_registry) == len(registry)

            # Check matching IDs
            for cap_id in registry._store:
                assert cap_id in new_registry._store

    def test_rank_capabilities(self):
        from aegis.evidence_model import Capability, CapabilityType, RiskLevel
        registry = CapabilityRegistry()
        
        c1 = Capability(
            name="command_runner",
            type=CapabilityType.SHELL_COMMAND,
            source="system",
            description="Run command line",
            risk_level=RiskLevel.MEDIUM,
            preferred_use_cases=["compile", "execute"]
        )
        c2 = Capability(
            name="ast_optimizer",
            type=CapabilityType.LOCAL_TOOL,
            source="optimizer",
            description="Optimize python AST",
            risk_level=RiskLevel.LOW,
            preferred_use_cases=["optimize", "compile"],
            tags=["ast", "refactor"]
        )
        
        ranked = registry.rank_capabilities([c1, c2], "Optimize python compilation")
        assert ranked[0].name == "ast_optimizer"
        assert ranked[1].name == "command_runner"

