"""
Aegis Runtime Selector

Factory to resolve runtime string names to their respective agent CLI adapters.
"""

from __future__ import annotations

from typing import Any
from .adk_adapter import ADKAdapter
from .gemini_cli_adapter import GeminiCLIAdapter
from .opencode_adapter import OpenCodeAdapter
from .antigravity_adapter import AntigravityAdapter


class RuntimeSelector:
    """Resolves developer CLI runtime string names to concrete adapters."""

    @staticmethod
    def get_adapter(runtime_name: str, **kwargs: Any) -> Any:
        """
        Get the adapter for a given runtime name.

        Supported runtimes: 'gemini', 'opencode', 'antigravity', 'adk'
        """
        name = runtime_name.lower().strip()
        if name == "gemini":
            return GeminiCLIAdapter(**kwargs)
        elif name == "opencode":
            return OpenCodeAdapter(**kwargs)
        elif name in ("antigravity", "antigravity-cli"):
            return AntigravityAdapter(**kwargs)
        elif name == "adk":
            return ADKAdapter(**kwargs)
        else:
            raise ValueError(
                f"Unknown runtime: '{runtime_name}'. "
                f"Supported runtimes: 'gemini', 'opencode', 'antigravity', 'adk'"
            )
