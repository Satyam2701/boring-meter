---
description: Show recorded Claude Code token usage (input, output, cache read, cache write) and an API list-price estimate from local session transcripts.
argument-hint: "[--today | --week | --days N | --since DATE --until DATE | --all] [--session ID] [--sessions] [--project PATH] [--source] [--json]"
disable-model-invocation: true
allowed-tools: Bash(boring-meter *)
---

Run the Boring Meter usage summary with the Bash tool:

```
boring-meter usage $ARGUMENTS
```

Supported options: `--today`, `--week`, `--days N`, `--since YYYY-MM-DD`, `--until YYYY-MM-DD`, `--all`, `--session ID`, `--sessions` (list sessions), `--project PATH`, `--source` (show data sources), `--no-findings`, `--json`.

If the user asks about "this session", or passes `--session` without an id, use `--session ${CLAUDE_SESSION_ID}`. The current session's latest requests may not be written to its transcript yet.

## How to run it

- Pass only the options listed above. If the arguments contain anything else (for example `;`, `|`, `&`, `$(`, backticks, or redirection), do not run anything. Explain the supported options instead.
- If `boring-meter` is not on PATH, run `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"` with the same arguments. On Windows without Git Bash (PowerShell or CMD), run `& "${CLAUDE_PLUGIN_ROOT}/bin/boring-meter.cmd"` with the same arguments.
- Show the output to the user verbatim in a fenced `text` block. Do not recompute, round, re-rank, or add numbers. Afterward, add at most two sentences, and only when something needs explaining (for example partial coverage or an error hint).
- Never describe recorded token counts as remaining subscription allowance, and never present a cost estimate as a bill or a saving.
