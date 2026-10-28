---
description: Run before-and-after optimization experiments - record baseline and follow-up sessions, record task quality, and compare usage with comparability checks.
argument-hint: "start --name NAME --change TEXT | baseline ID --session SID | followup ID --session SID | outcome ID --quality Q --completed yes|no | list | show ID | delete ID"
disable-model-invocation: true
allowed-tools: Bash(boring-meter experiment *)
---

Run the Boring Meter experiment command with the Bash tool:

```
boring-meter experiment $ARGUMENTS
```

Supported forms:
- `start --name NAME --change "what is being changed" [--task-type TYPE] [--project PATH]`
- `baseline ID --session SESSION_ID` or `baseline ID --from ISO_TIME --to ISO_TIME [--project PATH]`
- `followup ID --session SESSION_ID` (same options as baseline)
- `outcome ID --quality preserved|improved|degraded|unknown [--completed yes|no|unknown] [--side baseline|followup]`
- `list`, `show ID`
- `delete ID --yes` (only after the user explicitly confirms deletion)

If the user wants to record the current session as a run, use `--session ${CLAUDE_SESSION_ID}`, and remind them that requests from the current turn may not be written yet. Recording a finished session is more accurate.

Quality and task completion come only from the user. Never fill them in yourself. If they are unknown, leave them unknown.

Explain results using the printed classification: verified, directional, inconclusive, or invalid. Do not describe a directional or inconclusive result as proven savings.

## How to run it

- Pass only the options listed above. If the arguments contain anything else (for example `;`, `|`, `&`, `$(`, backticks, or redirection), do not run anything. Explain the supported options instead.
- If `boring-meter` is not on PATH, run `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"` with the same arguments.
- Show the output to the user verbatim in a fenced `text` block. Do not recompute, round, re-rank, or add numbers. Afterward, add at most two sentences, and only when something needs explaining (for example partial coverage or an error hint).
- Never describe recorded token counts as remaining subscription allowance, and never present a cost estimate as a bill or a saving.
