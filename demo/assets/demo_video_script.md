# Aegis Demo Video Narration Script & Shot List

- **Duration:** 75 Seconds
- **Tone:** Technical, clear, premium, confident
- **Audio:** Clear voiceover or synchronized captions over screen recording

---

## Shot List & Narration Flow

### Scene 1: The One-Line Pitch (0:00 - 0:10)
- **Visual:** Show `aegis_cover_image.png` (or zoom in on the terminal header showing "Aegis: Post-Execution Truth Layer for AI Agents").
- **Voiceover:**
  > "Meet Aegis: the post-execution truth layer for AI agents. Because when an agent claims a task is 'done,' how do you know it actually changed what it said it did?"

---

### Scene 2: The Agent Execution (0:10 - 0:25)
- **Visual:** Show a terminal running a developer agent execution loop, or run:
  `python demo/adk_worker_demo.py` up to STEP 3. Point to the worker claiming success:
  `[bold]Worker claimed success:[/bold] True`
  `[bold]Summary:[/bold] ADK worker completed task... Tests passed.`
- **Voiceover:**
  > "Here, our worker agent executes a login validation fix. It finishes and claims complete success. But under the hood, key criteria—like documentation updates and opening a pull request—were silently skipped."

---

### Scene 3: Aegis Reconciliation & Drift (0:25 - 0:45)
- **Visual:** Show `reconciliation_report.png` (or step 5 and step 6-7 on the terminal screen). Point out the highlighted **FAILED** status, missing file sections, and the capability audit flagging the unused `doc_updater` and `git_create_pr` tools.
- **Voiceover:**
  > "Aegis ingests the OpenTelemetry trace spans, matches them against the task contract success criteria, and runs pluggable verifiers. It immediately flags execution drift: the PR was never opened, and a preferred documentation capability went unused."

---

### Scene 4: Corrective Repair Sub-Plan & Approval (0:45 - 1:00)
- **Visual:** Show `approval_gate.png` (or step 8 and step 9 on the terminal). Focus on the proposed required steps and the approval gate waiting for confirmation.
- **Voiceover:**
  > "Instead of failing the entire pipeline, Aegis proposes a minimal corrective sub-plan to run the exact capabilities missed. The user reviews the plan and approves the repair pass with a single confirmation."

---

### Scene 5: Corrective Pass & Final State (1:00 - 1:15)
- **Visual:** Show `corrected_status.png` (or step 10, 11 and 12 in the terminal showing the green timeline and final `CORRECTED` status panel).
- **Voiceover:**
  > "Aegis executes the corrective pass and re-verifies the workspace state. With all criteria validated, the final status returns 'CORRECTED'. That's Aegis: bringing post-execution truth, auditability, and closed-loop correction to agent runtimes."

---

## Actionable Tips for Screen Recording:
1. **Prepare terminal zoom**: Ensure your terminal font size is large and legible.
2. **Interactive Run**: Run `python demo/adk_worker_demo.py` interactively (without `--auto`) so you can pause at the approval gate, explain the drift, and type `y` to demonstrate the repair live.
3. **Capture Telemetry**: If running Phoenix locally, show the trace span timeline on your web browser at `http://localhost:6006` briefly to visually demonstrate the OpenTelemetry instrumented spans.
