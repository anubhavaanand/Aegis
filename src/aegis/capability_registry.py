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

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"<CapabilityRegistry capabilities={len(self._store)}>"
