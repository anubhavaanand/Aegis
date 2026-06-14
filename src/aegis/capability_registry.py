"""
Aegis Capability Registry

Maintains a normalized inventory of all available capabilities across
tools, skills, MCPs, plugins, workflows, subagents, and external APIs.
The reconciliation engine and capability auditor query this registry to
detect missed or underutilized capabilities.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence_model import Capability, CapabilityType, RiskLevel

# ---------------------------------------------------------------------------
# Built-in capability seed data (always available in the Aegis runtime)
# ---------------------------------------------------------------------------

BUILTIN_CAPABILITIES: list[dict[str, Any]] = [
    {
        "name": "run_shell_command",
        "type": CapabilityType.SHELL_COMMAND,
        "source": "system",
        "description": "Execute a shell command and capture stdout/stderr",
        "preferred_use_cases": ["run tests", "build", "lint", "git operations"],
        "risk_level": RiskLevel.MEDIUM,
        "requires_approval": False,
        "tags": ["shell", "system", "test", "build"],
    },
    {
        "name": "read_file",
        "type": CapabilityType.LOCAL_TOOL,
        "source": "system",
        "description": "Read a file from the local filesystem",
        "preferred_use_cases": ["inspect code", "read config", "verify file content"],
        "risk_level": RiskLevel.LOW,
        "requires_approval": False,
        "tags": ["file", "read", "inspect"],
    },
    {
        "name": "write_file",
        "type": CapabilityType.LOCAL_TOOL,
        "source": "system",
        "description": "Write or create a file on the local filesystem",
        "preferred_use_cases": ["apply fix", "update docs", "create config"],
        "risk_level": RiskLevel.MEDIUM,
        "requires_approval": False,
        "tags": ["file", "write", "create"],
    },
    {
        "name": "git_diff",
        "type": CapabilityType.SHELL_COMMAND,
        "source": "git",
        "description": "Show file differences using git diff",
        "preferred_use_cases": ["verify changes", "review patch", "confirm fix"],
        "risk_level": RiskLevel.LOW,
        "requires_approval": False,
        "tags": ["git", "diff", "verify"],
    },
    {
        "name": "git_create_pr",
        "type": CapabilityType.SHELL_COMMAND,
        "source": "git",
        "description": "Create a pull request using git/gh CLI",
        "preferred_use_cases": ["open PR", "submit for review"],
        "risk_level": RiskLevel.HIGH,
        "requires_approval": True,
        "tags": ["git", "pr", "github"],
    },
    {
        "name": "pytest_runner",
        "type": CapabilityType.SHELL_COMMAND,
        "source": "pytest",
        "description": "Run pytest test suite and report results",
        "preferred_use_cases": ["run tests", "verify fix", "regression check"],
        "risk_level": RiskLevel.LOW,
        "requires_approval": False,
        "tags": ["test", "pytest", "verify"],
    },
    {
        "name": "adk_agent",
        "type": CapabilityType.SUBAGENT,
        "source": "google-adk",
        "description": "Google ADK agent for code generation and task execution",
        "preferred_use_cases": ["code generation", "multi-step tasks", "tool use"],
        "risk_level": RiskLevel.MEDIUM,
        "requires_approval": False,
        "tags": ["adk", "agent", "google"],
    },
    {
        "name": "doc_updater",
        "type": CapabilityType.SKILL,
        "source": "aegis",
        "description": "Skill to update documentation sections to reflect code changes",
        "preferred_use_cases": ["update readme", "update api docs", "sync changelog"],
        "risk_level": RiskLevel.LOW,
        "requires_approval": False,
        "tags": ["docs", "documentation", "update"],
    },
]


class CapabilityRegistry:
    """
    Normalized inventory of all available capabilities.

    Supports querying by type, tags, use-case keywords, and risk level.
    The capability auditor uses this registry to identify which capabilities
    were available but not used during task execution.
    """

    def __init__(self) -> None:
        self._store: dict[str, Capability] = {}
        self._load_builtins()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_builtins(self) -> None:
        for entry in BUILTIN_CAPABILITIES:
            cap = Capability(**entry)
            self._store[cap.capability_id] = cap

    def load_from_file(self, path: str | Path) -> None:
        """Load additional capabilities from a JSON file."""
        data = json.loads(Path(path).read_text())
        if isinstance(data, list):
            for entry in data:
                cap = Capability(**entry)
                self._store[cap.capability_id] = cap
        else:
            raise ValueError(f"Expected a JSON array in {path}")

    def register(self, capability: Capability) -> None:
        """Register a single capability."""
        self._store[capability.capability_id] = capability

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get(self, capability_id: str) -> Capability | None:
        return self._store.get(capability_id)

    def get_by_name(self, name: str) -> Capability | None:
        for cap in self._store.values():
            if cap.name == name:
                return cap
        return None

    def all(self, *, enabled_only: bool = True) -> list[Capability]:
        caps = list(self._store.values())
        if enabled_only:
            caps = [c for c in caps if c.enabled]
        return caps

    def by_type(self, cap_type: CapabilityType) -> list[Capability]:
        return [c for c in self.all() if c.type == cap_type]

    def by_tags(self, tags: list[str]) -> list[Capability]:
        tag_set = set(t.lower() for t in tags)
        return [
            c for c in self.all()
            if tag_set & {t.lower() for t in c.tags}
        ]

    def search(self, keyword: str) -> list[Capability]:
        """Full-text search across name, description, tags, use cases."""
        kw = keyword.lower()
        results = []
        for cap in self.all():
            searchable = " ".join([
                cap.name,
                cap.description,
                " ".join(cap.tags),
                " ".join(cap.preferred_use_cases),
            ]).lower()
            if kw in searchable:
                results.append(cap)
        return results

    def relevant_for(self, use_case_keywords: list[str]) -> list[Capability]:
        """Return capabilities relevant to a set of use-case keywords."""
        found: dict[str, Capability] = {}
        for kw in use_case_keywords:
            for cap in self.search(kw):
                found[cap.capability_id] = cap
        return list(found.values())

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def discover_from_mcp_config(self, config_path: str | None = None) -> None:
        """
        Auto-discover capabilities from installed MCP servers config files.
        """
        import os
        import subprocess
        import logging
        
        logger = logging.getLogger("aegis.capability_registry")

        paths_to_try = []
        if config_path:
            paths_to_try.append(Path(config_path))
        else:
            paths_to_try.append(Path.home() / ".config" / "mcp" / "servers.json")
            paths_to_try.append(Path.cwd() / ".mcp.json")
            paths_to_try.append(Path.cwd() / "mcp.json")

        data = {}
        found_path = None
        for p in paths_to_try:
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    found_path = p
                    break
                except Exception as e:
                    logger.warning(f"Failed to parse MCP config at {p}: {e}")

        if not found_path:
            logger.info("No MCP servers configuration files found.")
            return

        servers = {}
        if "mcpServers" in data:
            servers = data["mcpServers"]
        elif "servers" in data:
            if isinstance(data["servers"], list):
                for item in data["servers"]:
                    if isinstance(item, dict) and "name" in item:
                        servers[item["name"]] = item
            elif isinstance(data["servers"], dict):
                servers = data["servers"]

        for server_name, server_cfg in servers.items():
            if not isinstance(server_cfg, dict):
                continue
            command = server_cfg.get("command")
            if not command:
                continue
            args = server_cfg.get("args", [])
            env = server_cfg.get("env", None)

            # Query tools from server
            try:
                tools = self._query_mcp_server_tools(command, args, env, logger)
                for tool in tools:
                    tool_name = tool.get("name")
                    if not tool_name:
                        continue
                    cap = Capability(
                        capability_id=f"mcp_{server_name}_{tool_name}",
                        name=tool_name,
                        type=CapabilityType.MCP,
                        source=server_name,
                        description=tool.get("description", ""),
                        tags=["mcp", "auto-discovered"],
                        risk_level=RiskLevel.MEDIUM,
                    )
                    self.register(cap)
            except Exception as e:
                logger.warning(f"Could not discover tools from MCP server {server_name}: {e}")

    def _query_mcp_server_tools(
        self, command: str, args: list[str], env: dict[str, str] | None, logger: Any
    ) -> list[dict[str, Any]]:
        import os
        import subprocess
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        proc = subprocess.Popen(
            [command] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=full_env,
            bufsize=1,
        )

        try:
            # 1. Send initialize first (required by MCP)
            init_req = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "aegis", "version": "0.1.0"}
                }
            }
            proc.stdin.write(json.dumps(init_req) + "\n")
            proc.stdin.flush()
            
            # Discard initialize response
            proc.stdout.readline()

            # 2. Send tools/list request
            req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()

            # Read tools/list response
            line = proc.stdout.readline()
            if line:
                res = json.loads(line)
                if "result" in res and "tools" in res["result"]:
                    return res["result"]["tools"]
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

        return []

    def save_capability_manifest(self, path: str) -> None:
        """
        Save registered capabilities to a JSON manifest file.
        """
        from datetime import datetime, timezone
        
        manifest_data = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "capabilities": [cap.model_dump(mode="json") for cap in self.all(enabled_only=False)],
        }
        Path(path).write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    def load_capability_manifest(self, path: str) -> None:
        """
        Load capabilities from a JSON manifest file, skipping duplicates by capability_id.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        caps_list = data.get("capabilities", [])
        for entry in caps_list:
            cap = Capability(**entry)
            if cap.capability_id not in self._store:
                self.register(cap)

    def rank_capabilities(self, capabilities: list[Capability], use_case: str) -> list[Capability]:
        """
        Rank a list of capabilities based on their suitability for a use-case.
        Scoring system:
        - Type score: local/mcp tools > skills > subagents > shell commands
        - Risk penalty: higher risk gets penalized
        - Use-case relevance: boosts score for tag/use-case/name/description matches
        """
        import re
        
        # Split use_case into keywords
        keywords = [kw.lower() for kw in re.findall(r"\w+", use_case) if len(kw) > 1]
        
        def score_cap(cap: Capability) -> tuple[float, str]:
            score = 0.0
            
            # 1. Type Score
            t = str(cap.type).lower()
            if t in ("local_tool", "mcp_tool", "mcp"):
                score += 3.0
            elif t == "skill":
                score += 2.5
            elif t == "subagent":
                score += 2.0
            elif t == "shell_command":
                score += 1.0
            else:
                score += 1.0
                
            # 2. Risk Penalty
            r = str(cap.risk_level).lower()
            if r == "critical":
                score -= 3.0
            elif r == "high":
                score -= 1.5
            elif r == "medium":
                score -= 0.5
            elif r == "low":
                score -= 0.0
                
            # 3. Use-case boost
            pref_use_cases = [uc.lower() for uc in cap.preferred_use_cases]
            cap_tags = [tag.lower() for tag in cap.tags]
            cap_name = cap.name.lower()
            cap_desc = cap.description.lower()
            
            for kw in keywords:
                # Preferred use cases match
                if any(kw in uc for uc in pref_use_cases):
                    score += 2.0
                # Tags match
                if any(kw in tag for tag in cap_tags):
                    score += 1.0
                # Name match
                if kw in cap_name:
                    score += 0.5
                # Description match
                if kw in cap_desc:
                    score += 0.5
                    
            return score, cap.name

        # Sort by score descending, then by name ascending
        return sorted(capabilities, key=lambda c: (-score_cap(c)[0], score_cap(c)[1]))

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"<CapabilityRegistry capabilities={len(self._store)}>"
