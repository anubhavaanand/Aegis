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

## Command Line Interface (CLI)

Aegis now comes with a unified command-line tool built on Typer.

### CLI Installation

To register the `aegis` entrypoint globally, run:
```bash
pip install -e . --break-system-packages
```
Once installed, you can invoke the CLI using the `aegis` command. (Alternatively, run it via `python -m aegis.cli`).

### Commands

*   **`aegis run --request "<request>" [--auto] [--retries N] [--real] [--semantic] [--policy <in-process|opa>]`**
    Executes a task through the complete Aegis self-healing verification loop.
    *   `--request` (`-r`): Verbatim user request statement.
    *   `--auto` (`-y`): Run non-interactively, auto-approving proposed repairs (ideal for CI/CD environments).
    *   `--retries` (`-n`): Max repair retries (defaults to 2).
    *   `--real`: Executes with a real OTel-instrumented Google ADK agent instead of simulated run.
    *   `--semantic`: Enables LLM-as-Judge semantic verification using `gemini-2.5-flash` structured outputs.
    *   `--policy`: Policy engine mode (either `in-process` or `opa`, defaults to `in-process`).
*   **`aegis discover-capabilities [--config <path>] [--output <path>]`**
    Auto-discovers capabilities from Model Context Protocol (MCP) server configurations and saves them to a capability manifest.
    *   `--config` (`-c`): Optional custom path to MCP `servers.json`. (Checks `~/.config/mcp/servers.json`, `.mcp.json`, and `mcp.json` by default).
    *   `--output` (`-o`): Output JSON manifest path (defaults to `capabilities_manifest.json`).
*   **`aegis list-audits`**
    Lists all stored compliance audit logs in a clean Rich table.
*   **`aegis report --task-id <id>`**
    Inspects and renders a historical compliance report from the audit archive.

---

## Environment Variables

Aegis supports the following environment variables for advanced configuration:

*   `AEGIS_SEMANTIC_VERIFY`: Set to `true` to enable semantic task validation. (Requires `GOOGLE_API_KEY`).
*   `AEGIS_POLICY_ENGINE`: Set to `opa` to delegate policy evaluations to an Open Policy Agent instance.
*   `AEGIS_OPA_URL`: The REST API URL of the OPA server (defaults to `http://localhost:8181`).
*   `AEGIS_PROTECTED_PATHS`: Comma-separated list of directories/files that should be protected (any changes to these paths trigger mandatory human review in default policy).
*   `AEGIS_AUTO_APPROVE_LOW_RISK`: Set to `true` to automatically approve low-risk repair tasks.
*   `AEGIS_AUDIT_DIR`: Custom directory to save compliance audit reports.

---

## Persistent Compliance Audit Trails

Aegis writes a structured compliance audit log for every task execution to `~/.aegis/audit/{date}/{task_id}.json` (override via the `AEGIS_AUDIT_DIR` environment variable). This fulfills high-risk logging requirements under modern AI frameworks (e.g. EU AI Act process logging).

### Audit Trail Schema Structure
```json
{
  "schema_version": "1.0",
  "task_id": "84ab00e3-990e-4f8b-8fd2-65cd391caf6d",
  "timestamp": "2026-06-11T08:38:00.000000+00:00",
  "contract": { ...TaskContract snapshot... },
  "drift_report": { ...ReconciliationReport... },
  "evidence_summary": { ...EvidenceSummary... },
  "approval_decision": {
    "approved": true,
    "selected_steps": [...],
    "notes": "User approved all steps"
  },
  "repair_steps": [...],
  "final_report": { ...post-repair ReconciliationReport... },
  "final_status": "corrected"
}
```

---

## Three-Phase Roadmap (Maximum Potential)

Aegis’s long-term vision is organized into a three-phase architecture:

*   **Phase 1: Production-Ready Verification (Shipped)**
    *   **Persistent Compliance Audit Trails:** Timestamped, schema-versioned JSON logs for every audit run.
    *   **Risk-Tiered Approval Automation:** Auto-approvals for `LOW` risk tasks (via `AEGIS_AUTO_APPROVE_LOW_RISK=true`), 30-second timed gates for `MEDIUM` risk tasks, and blocking prompts for `HIGH`/`CRITICAL` tasks.
    *   **Iterative Self-Healing Loops:** Bounded retry loops (default 2) passing failure context (verbal critiques) to subsequent iterations.
    *   **Unified CLI Interface:** `run`, `report`, `list-audits`, and `discover-capabilities` subcommands.
*   **Phase 2: LLM-Backed Contract Intelligence & Observability (Shipped)**
    *   **LLM Contract Builder (Opt-In):** Gemini structured JSON contract generation (`AEGIS_CONTRACT_MODE=llm`) with heuristic fallback.
    *   **MCP Server Auto-Discovery:** Dynamic registry tool discovery scanning standard and local configs.
    *   **Semantic Verification (LLM-as-Judge):** Gemini 2.5 structured output validation comparing intent and drift reports.
    *   **OPA & Rego Policy Integration:** Policy engine supporting in-process rules and OPA REST HTTP delegation.
*   **Phase 3: Reusable Standards & Services (Planned)**
    *   **Aegis Python SDK:** Publishing programmatic imports (`import aegis`) to decouple from subprocess CLIs.
    *   **A2A Verifier Agent:** Wrapping Aegis as a standard Agent-to-Agent protocol service enabling remote or team orchestrators to request audits.
    *   **OTel Thinking Span Extraction:** Normalizing internal reasoning attributes to audit cognitive step drift.

---

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
│   ├── final_verifier.py          # Performs post-repair verification
│   ├── audit_logger.py            # Persists structured compliance logs
│   ├── runner.py                  # Coordinates the closed-loop execution & self-healing
│   └── cli.py                     # Typer command line interface
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
