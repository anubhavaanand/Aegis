# Aegis

> **Aegis is the truth layer that runs after agents claim done.**

Aegis is a post-execution state reconciliation and trace audit layer for agent runtimes. It runs *after* a worker agent executes and answers:
- Was the task actually completed?
- Did the final state match the approved success criteria?
- Did anything silently fail?
- Was a better available capability missed?
- Should a corrective sub-plan be proposed and approved?

---

## Product Definition

Aegis is **not** a replacement for Gemini CLI Plan Mode, ADK orchestration, or Google’s governance boundary. It is the layer that runs **after** a worker agent executes to enforce compliance, detect drift, audit tool usage, and perform minimal corrective repairs.

```
                  ┌─────────────────────────────────────┐
                  │          Gemini Plan Mode           │ (High-level planning)
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │            Google ADK /             │ (Orchestration &
                  │       Worker Agent Execution        │  Task Execution)
                  └──────────────────┬──────────────────┘
                                     │ [OTel Tracing Spans]
                                     ▼
            =================================================
                                AEGIS ZONE
            =================================================
                  ┌─────────────────────────────────────┐
                  │        Trace Normalization          │ (Translates spans to
                  │         & State Verifier            │  Aegis EvidenceEvents)
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │        Reconciliation Engine        │ (Verifies state &
                  │         & Capability Audit          │  detects tool drift)
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │          Drift Classifier           │ (Computes drift severity
                  │         & Repair Planner            │  & minimal sub-plan)
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │            Approval Gate            │ (User approves/rejects
                  │           & Final Verify            │  corrective repair)
                  └─────────────────────────────────────┘
```

---

## Hackathon Positioning: The Aegis Edge

Most agent frameworks focus on the execution loop—getting agents to run tools and output answers. However, there is a **trust and validation gap** when an agent claims a complex task is completed. Humans or orchestration frameworks must blindly accept the result.

Aegis fills this gap with three key differentiators:

1. **State Reconciliation vs. Simple Outputs:** Instead of just checking the model's text output, Aegis uses pluggable verifiers to confirm actual system state changes (e.g., verifying that a git diff exists, tests pass, or documentation sections were edited).
2. **Capability Auditing (Key Differentiator):** Aegis doesn't just check if a task passed; it checks *how* it was done. By auditing the execution traces against a registry of preferred capabilities, Aegis flags sub-optimal execution. If an agent performs a manual regex replacement instead of using a registered AST refactoring skill, Aegis detects this missed capability.
3. **Closed-Loop Repair:** When drift or suboptimal execution is detected, Aegis generates a minimal corrective sub-plan. Once approved by the user, Aegis executes the repair pass and performs final re-verification to bring the system back into full compliance.

---

## ASCII Architecture Diagram

### The Closed-Loop Flow
```
User Request
     │
     ▼
┌──────────────────────────┐
│  Contract Builder        │ ──► Generates TaskContract (JSON Schema)
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Worker Agent Run        │ ──► Real ADK worker using gemini-2.5-flash & tools
└────────────┬─────────────┘      (Or simulated worker fallback)
             │
             ▼ [OpenTelemetry / OpenInference Spans]
┌──────────────────────────┐
│  Trace Adapter           │ ──► Normalizes spans to EvidenceEvents
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Reconciliation Engine   │ ──► Runs StateVerifier & CapabilityAuditor
└────────────┬─────────────┘
             │
             ▼ [ReconciliationReport]
┌──────────────────────────┐
│  Repair Planner          │ ──► Generates minimal corrective sub-plan
└────────────┬─────────────┘
             │
             ▼ [Terminal UI Gate]
┌──────────────────────────┐
│  Approval Manager        │ ──► User approves or rejects sub-plan
└────────────┬─────────────┘
             │
             ├──────────────────────────┐
             ▼ (Approved)               ▼ (Rejected)
┌──────────────────────────┐      ┌──────────────────────────┐
│  Corrective Repair Pass  │      │   Stop / Exit            │
└────────────┬─────────────┘      └──────────────────────────┘
             │
             ▼ [New Evidence]
┌──────────────────────────┐
│  Final Verifier          │ ──► Re-verifies all criteria
└──────────────────────────┘      Result: CORRECTED ✅ or UNRESOLVED ✗
```

### Module Layout
```
src/
├── aegis/                         # Runtime-agnostic core modules
│   ├── evidence_model.py          # Pydantic v2 schemas (spans, contracts, reports)
│   ├── contract_builder.py        # Maps user requests to TaskContracts
│   ├── capability_registry.py     # Database of preferred skills, tools, and MCPs
│   ├── state_verifier.py          # Pluggable verifiers (FileDiff, pytest, docs, PR)
│   ├── reconciliation_engine.py   # Main engine invoking verifiers and DriftClassifier
│   ├── capability_auditor.py      # Checks traces for underutilized or missed capabilities
│   ├── repair_planner.py          # Formulates the corrective plan steps
│   ├── approval_manager.py        # Handles the blocking user approval loop
│   └── final_verifier.py          # Performs post-repair verification
├── adapters/                      # Runtime-specific integrations
│   ├── adk_adapter.py             # Google ADK Adapter (runs simulated / real worker)
│   ├── real_adk_worker.py         # Real ADK agent runner instrumented with OTel
│   ├── trace_adapter.py           # Normalizes OpenInference spans into Aegis Events
│   ├── antigravity_adapter.py     # Antigravity CLI stub
│   └── wrapper_adapter.py         # Subprocess wrapper stub
├── ui/
│   └── terminal_ui.py             # Premium Rich-based CLI layout
└── schemas/                       # Draft-07 JSON schemas for runtime interoperability
    ├── task_contract.json
    ├── capability.json
    ├── evidence_event.json
    └── reconciliation_report.json
```

---

## Installation & Setup

```bash
# Clone the repository
git clone <repo-url>
cd Aegis

# Install the package with dependencies
pip install -e . --break-system-packages

# Install development/test dependencies
pip install -e ".[dev]" --break-system-packages
```

---

## Two Demo Paths

Aegis includes both a simulated zero-config offline demo and a live demo executing a real Google ADK agent.

### Path A: Simulated Demo (Offline / Zero-Config)
Runs a full 12-step reconciliation and repair loop using simulated ADK trace data. Ideal for checking the UI, verifier logic, and planner without requiring API keys or network calls.

```bash
# Run interactively (prompts for approval)
python demo/adk_worker_demo.py

# Run in auto-approve mode (non-interactive, suitable for CI)
python demo/adk_worker_demo.py --auto
```

### Path B: Live ADK Demo (Real Gemini Run & OTel Tracing)
Runs a real Google ADK agent utilizing `gemini-2.5-flash` to execute tools. Captures execution spans in memory using `openinference-instrumentation-google-adk`, exports them to OTel, and feeds them into the Aegis reconciliation engine.

```bash
# Set your Gemini API Key
export GOOGLE_API_KEY="your_api_key_here"

# (Optional) Export traces to a local Phoenix instance
# export PHOENIX_COLLECTOR_ENDPOINT="http://localhost:6006/v1/traces"

# Run the live demo
python demo/live_adk_demo.py
```

---

## Module Reference

| Module | Purpose | Key Differentiator |
|---|---|---|
| `contract_builder.py` | Distills raw user requests into goals, success criteria, and risk level. | Can be backed by deterministic heuristics or LLM inference. |
| `state_verifier.py` | Pluggable system verifying if outcomes are actually true in the workspace. | Includes verifiers for File Diff, pytest status, PR existence, doc changes. |
| `capability_auditor.py` | Audits trace evidence against registered skills/tools. | Flags missed capabilities to avoid suboptimal manual execution. |
| `repair_planner.py` | Creates a sequential repair plan mapping unmet criteria to tools. | Prioritizes required fixes over optional enhancements. |
| `approval_manager.py` | Gatekeeper block preventing any repair pass from executing without review. | Interactive CLI UI built with Rich. |

---

## Extending Aegis

### Registering Custom Capabilities
You can register new skills, local CLI tools, or MCP servers in the `CapabilityRegistry`:

```python
from aegis.capability_registry import CapabilityRegistry
from aegis.evidence_model import Capability, CapabilityType, RiskLevel

registry = CapabilityRegistry()
registry.register(Capability(
    name="ast_refactor_tool",
    type=CapabilityType.LOCAL_TOOL,
    source="refactor-suite",
    description="Refactor code structure using AST parsing",
    preferred_use_cases=["refactor", "migrate", "clean code"],
    risk_level=RiskLevel.MEDIUM,
    tags=["refactor", "ast", "python"],
))
```

### Creating a New Verifier
To add a new state verifier (e.g., verifying a deployment URL is live):
1. Implement the `Verifier` protocol in `src/aegis/state_verifier.py`:
   ```python
   class UrlLiveVerifier:
       def verify(self, criterion, events, workspace):
           # check URL response status code...
           return VerificationResult(criterion.criterion_id, passed=True, quality=EvidenceQuality.STRONG)
   ```
2. Add your verifier to the `StateVerifier` lookup registry.
3. Update `VerifierType` enum in `src/aegis/evidence_model.py` and JSON schema.

---

## Non-Goals (MVP)
- Replacing developer agent runners (like Gemini CLI or ADK agent executors).
- Providing a generic, non-agent policy firewall.
- Universal support for all arbitrary terminal commands.
- Polished enterprise web UI (Aegis is terminal-first).

---

## License
MIT
