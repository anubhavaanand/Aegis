# Aegis

> **Aegis is the truth layer that runs after agents claim done.**

Aegis is a post-execution state reconciliation and trace audit layer for agent runtimes. It runs *after* a worker agent executes and answers:

- Was the task actually completed?
- Did the final state match the approved success criteria?
- Did anything silently fail?
- Was a better available capability missed?
- Should a corrective sub-plan be proposed and approved?

---

## Design Goals & Boundaries

Aegis exists to close the trust gap between "the agent said it's done" and "the work is actually verified." It is **not** a general-purpose orchestrator, task planner, or agent runner.

### What Aegis Does

| Capability | Description |
|---|---|
| **Post-execution verification** | Runs after any worker agent (ADK, Gemini CLI, OpenCode, Antigravity) completes, checking actual system state against declared success criteria. |
| **State reconciliation** | Uses pluggable verifiers (file diffs, test results, doc sections, PR existence) to confirm real outcomes — not just text output. |
| **Capability auditing** | Compares execution traces against a registry of preferred tools/skills to flag suboptimal or missed capabilities. |
| **Closed-loop repair** | Generates minimal corrective sub-plans when drift is detected, then re-verifies after the repair pass. |
| **Audit trail persistence** | Writes structured compliance logs to `~/.aegis/audit/` for regulatory traceability (EU AI Act). |

### What Aegis Is Not

| Boundary | Explanation |
|---|---|
| **Not an orchestrator** | Aegis does not schedule tasks, manage agents, or decide what to run. It receives the output of a completed execution. |
| **Not a task planner** | Aegis does not decompose goals into subtasks. It builds verification contracts from user requests, not execution plans. |
| **Not a sandbox** | Aegis does not isolate or contain agent execution. It observes traces produced by the runtime. |
| **Not a prompt framework** | Aegis does not inject prompts or manage conversation history. |
| **Not a replacement for ADK/Gemini** | Aegis complements agent runtimes; it does not replace them. |

### Core Principle

Aegis operates on a simple contract:

> **Given:** a completed agent execution + trace evidence.
> **Produces:** a verdict (pass/drift/corrected) + audit trail + optional repair plan.

This makes it composable — you can run any agent runtime and pipe its output through Aegis for verification.

---

## Architecture

### Positioning

```
    User Request
         │
         ▼
┌──────────────────────────┐
│     Agent Runtime        │   ADK, Gemini CLI, OpenCode, etc.
│  (execution + tracing)   │   Produces OTel spans / trace data
└────────────┬─────────────┘
             │  execution evidence
             ▼
    ╔══════════════════════╗
    ║     AEGIS ZONE       ║
    ║  (post-execution)    ║
    ╚══════════════════════╝
             │
    ┌────────┴────────┐
    │  Reconciliation │   "Did the work actually happen?"
    │  Capability Audit│  "Was the best tool used?"
    │  Repair Planning │  "What's the minimal fix?"
    │  Approval Gate   │  "Does the human agree?"
    │  Audit Logging   │  "What's the compliance record?"
    └─────────────────┘
             │
             ▼
    Final Verdict + Audit Trail
```

### Closed-Loop Flow

```
User Request
     │
     ▼
┌──────────────────────────┐
│  Contract Builder        │ → Generates TaskContract (JSON Schema)
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Worker Agent Run        │ → Real ADK worker using gemini-2.5-flash & tools
└────────────┬─────────────┘     (Or simulated worker fallback)
             │
             ▼ [OpenTelemetry / OpenInference Spans]
┌──────────────────────────┐
│  Trace Adapter           │ → Normalizes spans to EvidenceEvents
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Reconciliation Engine   │ → Runs StateVerifier & CapabilityAuditor
└────────────┬─────────────┘
             │
             ▼ [ReconciliationReport]
┌──────────────────────────┐
│  Repair Planner          │ → Generates minimal corrective sub-plan
└────────────┬─────────────┘
             │
             ▼ [Terminal UI Gate]
┌──────────────────────────┐
│  Approval Manager        │ → User approves or rejects sub-plan
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
│  Final Verifier          │ → Re-verifies all criteria
└──────────────────────────┘     Result: CORRECTED ✅ or UNRESOLVED ✗
```

---

## Example Workflows

These examples show exactly what Aegis does today — verify, audit, and repair after execution.

### Example 1: Bug Fix Verification (Simulated)

A worker agent claims to have fixed a login bug. Aegis verifies the claim:

```bash
# Run the full simulated demo — no API keys needed
python demo/adk_worker_demo.py
```

**What happens:**
1. User requests: "Fix the login validation bug, update docs, run tests, and create a PR."
2. Aegis builds a `TaskContract` with 4 success criteria (file_diff, test_pass, doc_section, pr_exists)
3. Simulated worker executes — but intentionally skips docs and PR creation
4. Aegis reconciles: 2/4 criteria satisfied, drift detected
5. Aegis flags a missed capability: `doc_updater` was available but unused
6. Repair planner proposes minimal sub-plan (update docs + create PR)
7. User approves via terminal UI gate
8. Corrective pass runs, producing doc update and PR events
9. Final verifier confirms: **CORRECTED** ✅

**Pre-generated outputs** in `demo/`:
- `output_contract.json` — the TaskContract
- `output_reconciliation_report.json` — drift report with unmet criteria
- `output_final_report.json` — post-repair verification result

### Example 2: Custom Task via CLI

Run Aegis on an arbitrary task description:

```bash
# Simulated execution (offline)
aegis run --request "Refactor the auth module to use JWT tokens, add rate limiting, and update the API docs"

# With auto-approve for CI/CD pipelines
aegis run --request "Add input validation to the /submit endpoint" --auto

# With semantic verification (requires GOOGLE_API_KEY)
aegis run --request "Fix the race condition in the payment processor" --semantic
```

**What Aegis does:**
1. Builds a TaskContract with appropriate success criteria
2. Executes the worker (simulated or real ADK)
3. Reconciles contract vs. evidence
4. Reports drift, missed capabilities, and compliance metrics
5. Proposes repairs if needed (auto-approves LOW risk when `--auto`)
6. Logs a structured audit trail to `~/.aegis/audit/`

### Example 3: Inspect Audit Trails

```bash
# List all past audit logs
aegis list-audits

# View a specific audit report
aegis report --task-id <task-id-from-list>
```

---

## Hackathon Positioning: The Aegis Edge

Most agent frameworks focus on the execution loop — getting agents to run tools and output answers. However, there is a **trust and validation gap** when an agent claims a complex task is completed. Humans or orchestration frameworks must blindly accept the result.

Aegis fills this gap with three key differentiators:

1. **State Reconciliation vs. Simple Outputs:** Instead of just checking the model's text output, Aegis uses pluggable verifiers to confirm actual system state changes (e.g., verifying that a git diff exists, tests pass, or documentation sections were edited).
2. **Capability Auditing (Key Differentiator):** Aegis doesn't just check if a task passed; it checks *how* it was done. By auditing the execution traces against a registry of preferred capabilities, Aegis flags sub-optimal execution. If an agent performs a manual regex replacement instead of using a registered AST refactoring skill, Aegis detects this missed capability.
3. **Closed-Loop Repair:** When drift or suboptimal execution is detected, Aegis generates a minimal corrective sub-plan. Once approved by the user, Aegis executes the repair pass and performs final re-verification to bring the system back into full compliance.

---

## Command Line Interface (CLI)

Aegis comes with a unified command-line tool built on Typer.

### CLI Installation

```bash
pip install -e .
```

Once installed, invoke via `aegis` (or `python -m aegis.cli`).

### Commands

| Command | Description |
|---|---|
| `aegis run --request "<request>"` | Execute through the full Aegis verification loop |
| `aegis discover-capabilities` | Auto-discover capabilities from MCP server configs |
| `aegis list-audits` | List all stored compliance audit logs |
| `aegis report --task-id <id>` | Inspect a historical compliance report |

### Flags

| Flag | Purpose |
|---|---|
| `--auto` / `-y` | Non-interactively auto-approve repairs (CI/CD) |
| `--retries N` | Max repair retries (default: 2) |
| `--real` | Use real OTel-instrumented Google ADK agent |
| `--semantic` | Enable LLM-as-Judge semantic verification |
| `--policy <in-process\|opa>` | Policy engine mode |

---

## Environment Variables

| Variable | Description |
|---|---|
| `AEGIS_SEMANTIC_VERIFY` | Set to `true` to enable semantic validation (requires `GOOGLE_API_KEY`) |
| `AEGIS_POLICY_ENGINE` | Set to `opa` to delegate policy to OPA |
| `AEGIS_OPA_URL` | OPA REST API URL (default: `http://localhost:8181`) |
| `AEGIS_PROTECTED_PATHS` | Comma-separated protected paths (triggers mandatory human review) |
| `AEGIS_AUTO_APPROVE_LOW_RISK` | Set to `true` to auto-approve LOW risk repairs |
| `AEGIS_AUDIT_DIR` | Custom audit log directory |

---

## Compliance Audit Trails

Aegis writes structured compliance logs to `~/.aegis/audit/{date}/{task_id}.json` for every execution.

### Schema

```json
{
  "schema_version": "1.0",
  "task_id": "84ab00e3-990e-4f8b-8fd2-65cd391caf6d",
  "timestamp": "2026-06-11T08:38:00.000000+00:00",
  "contract": { "..." },
  "drift_report": { "..." },
  "evidence_summary": { "..." },
  "approval_decision": {
    "approved": true,
    "selected_steps": [...],
    "notes": "User approved all steps"
  },
  "repair_steps": [...],
  "final_report": { "..." },
  "final_status": "corrected"
}
```

---

## Module Layout

```
src/
├── aegis/                         # Runtime-agnostic core modules
│   ├── evidence_model.py          # Pydantic v2 schemas (spans, contracts, reports)
│   ├── contract_builder.py        # Maps user requests to TaskContracts
│   ├── capability_registry.py     # Database of preferred skills, tools, and MCPs
│   ├── state_verifier.py          # Pluggable verifiers (FileDiff, pytest, docs, PR)
│   ├── reconciliation_engine.py   # Main engine invoking verifiers and DriftClassifier
│   ├── capability_auditor.py      # Checks traces for underutilized or missed capabilities
│   ├── repair_planner.py          # Formulates corrective plan steps
│   ├── approval_manager.py        # Blocking user approval loop
│   ├── final_verifier.py          # Post-repair verification
│   ├── audit_logger.py            # Persists structured compliance logs
│   ├── policy_engine.py           # In-process + OPA policy evaluation
│   ├── semantic_verifier.py       # LLM-as-Judge semantic verification
│   ├── runner.py                  # Closed-loop orchestrator
│   └── cli.py                     # Typer CLI
├── adapters/                      # Runtime-specific integrations
│   ├── adk_adapter.py             # Google ADK adapter (+ SimulatedADKWorker)
│   ├── real_adk_worker.py         # Real ADK agent with OTel instrumentation
│   ├── trace_adapter.py           # Normalizes OpenInference spans to EvidenceEvents
│   ├── gemini_cli_adapter.py      # Gemini CLI adapter
│   ├── opencode_adapter.py        # OpenCode CLI adapter
│   ├── antigravity_adapter.py     # Antigravity CLI adapter
│   ├── base_cli_adapter.py        # Abstract base for CLI adapters
│   ├── runtime_selector.py        # Factory for runtime adapters
│   └── wrapper_adapter.py         # Generic subprocess wrapper
├── ui/
│   └── terminal_ui.py             # Rich-powered terminal UI
└── schemas/                       # Draft-07 JSON schemas
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
pip install -e .

# Install development/test dependencies
pip install -e ".[dev]"
```

---

## Demo Paths

### Path A: Simulated Demo (Offline / Zero-Config)

Runs a full 12-step reconciliation and repair loop using simulated ADK trace data. No API keys required.

```bash
python demo/adk_worker_demo.py          # interactive (prompts for approval)
python demo/adk_worker_demo.py --auto   # non-interactive (CI-friendly)
```

### Path B: Live ADK Demo (Real Gemini Run)

Runs a real Google ADK agent with `gemini-2.5-flash`, capturing OTel traces.

```bash
export GOOGLE_API_KEY="your_api_key_here"
python demo/live_adk_demo.py
```

---

## Module Reference

| Module | Purpose | Key Differentiator |
|---|---|---|
| `contract_builder.py` | Distills raw user requests into goals, success criteria, and risk level. | Heuristic or LLM-backed generation. |
| `state_verifier.py` | Pluggable system verifying if outcomes are true in the workspace. | Verifiers for File Diff, pytest, PR, docs. |
| `capability_auditor.py` | Audits trace evidence against registered skills/tools. | Flags missed capabilities. |
| `repair_planner.py` | Creates sequential repair plan mapping unmet criteria to tools. | Prioritizes required fixes over optional. |
| `approval_manager.py` | Gatekeeper preventing repair execution without review. | Risk-tiered: auto LOW, timed MEDIUM, blocking HIGH. |
| `reconciliation_engine.py` | Core engine comparing contracts vs. evidence. | Computes compliance score + drift classification. |
| `final_verifier.py` | Post-repair re-verification with status upgrade logic. | Iterative retry with bounded loops. |
| `audit_logger.py` | Persists structured compliance logs. | EU AI Act process logging compatible. |
| `policy_engine.py` | In-process + OPA policy delegation. | Path traversal protection, risk-tiered authorization. |
| `semantic_verifier.py` | LLM-as-Judge semantic verification. | Gemini structured output validation. |

---

## Extending Aegis

### Registering Custom Capabilities

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

## Roadmap

- **Phase 1 (Shipped):** Production-ready verification, persistent audit trails, risk-tiered approval, iterative self-healing loops, unified CLI.
- **Phase 2 (Shipped):** LLM contract builder, MCP auto-discovery, semantic verification, OPA/Rego policy integration.
- **Phase 3 (Planned):** Aegis Python SDK, A2A Verifier Agent, OTel thinking span extraction.

---

## License

MIT
