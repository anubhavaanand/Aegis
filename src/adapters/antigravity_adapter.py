"""
Aegis Antigravity CLI Adapter (Stub)

Future adapter for the Antigravity / Gemini CLI runtime.
Will normalize Antigravity agent traces into Aegis EvidenceEvents.

Currently a stub — ADK is the first-class integration.
"""

from __future__ import annotations

from aegis.evidence_model import EvidenceEvent


class AntigravityAdapter:
    """
    Stub adapter for Antigravity CLI / Gemini CLI agent runs.

    To implement: hook into Antigravity session logs or trace output,
    normalize tool calls and model calls into EvidenceEvents using
    the TraceAdapter.
    """

    def __init__(self, agent_id: str = "antigravity-worker") -> None:
        self.agent_id = agent_id

    def collect_events(self, session_id: str) -> list[EvidenceEvent]:
        """
        Collect and normalize evidence events from an Antigravity session.

        TODO: Implement when Antigravity trace export API is available.
        """
        raise NotImplementedError(
            "AntigravityAdapter is a stub. Implement when Antigravity "
            "trace export is available."
        )
