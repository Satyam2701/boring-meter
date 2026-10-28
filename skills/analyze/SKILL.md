---
description: Find possible usage inefficiencies (repeated file reads, oversized instructions, long multi-task sessions, regenerated output, routine subagent work on a top-tier model) with evidence and confidence.
argument-hint: "[--week | --days N | --all] [--project PATH] [--session ID] [--limit N] [--rules] [--json]"
disable-model-invocation: true
allowed-tools: Bash(boring-meter *)
---

Run the Boring Meter analysis with the Bash tool:

```
boring-meter analyze $ARGUMENTS
```

Supported options: `--today`, `--week`, `--days N`, `--since YYYY-MM-DD`, `--until YYYY-MM-DD`, `--all`, `--project PATH` (default: current directory), `--session ID`, `--limit N`, `--no-instructions`, `--rules` (show the rule catalog), `--json`.

If the user says "this session", use `--session ${CLAUDE_SESSION_ID}`.

This command only reads data. Do not edit any file as a follow-up unless the user explicitly asks; point them to `/boring-meter:optimize` for reviewable changes.

## How to run it

- Pass only the options listed above. If the arguments contain anything else (for example `;`, `|`, `&`, `$(`, backticks, or redirection), do not run anything. Explain the supported options instead.
- If `boring-meter` is not on PATH, run `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"` with the same arguments.
- Show the output to the user verbatim in a fenced `text` block. Do not recompute, round, re-rank, or add numbers. Afterward, add at most two sentences, and only when something needs explaining (for example partial coverage or an error hint).
- Never describe recorded token counts as remaining subscription allowance, and never present a cost estimate as a bill or a saving.
