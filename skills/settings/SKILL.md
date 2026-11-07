---
description: Inspect and change Boring Meter's local settings, data sources, thresholds, pricing, retention, and stored data (export or delete Boring Meter's own records only).
argument-hint: "show | set KEY VALUE | sources | path | export --output PATH | prune | reset --yes | delete-data --yes"
disable-model-invocation: true
allowed-tools: Bash(boring-meter settings) Bash(boring-meter settings show*) Bash(boring-meter settings sources*) Bash(boring-meter settings path*) Bash(boring-meter settings set *) Bash(boring-meter settings export *) Bash(boring-meter settings prune*) Bash(boring-meter doctor*)
---

Run the Boring Meter settings command with the Bash tool:

```
boring-meter settings $ARGUMENTS
```

With no arguments this shows every setting, its value, what it does, and when a change applies.

Supported forms: `show`, `set KEY VALUE`, `sources`, `path`, `export --output PATH`, `prune`, `reset --yes`, `delete-data --yes`. `boring-meter doctor` checks the installation.

Confirmation rules:
- `reset --yes` and `delete-data --yes` are permanent. Run them only after the user explicitly confirms in this conversation. `delete-data` removes only Boring Meter's own data directory; it never touches Claude Code transcripts.
- `export --output PATH` refuses to overwrite an existing file. Add `--force` only after the user confirms.

## How to run it

- Pass only the options listed above. If the arguments contain anything else (for example `;`, `|`, `&`, `$(`, backticks, or redirection), do not run anything. Explain the supported options instead.
- If `boring-meter` is not on PATH, run `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"` with the same arguments. On Windows without Git Bash (PowerShell or CMD), run `& "${CLAUDE_PLUGIN_ROOT}/bin/boring-meter.cmd"` with the same arguments.
- Show the output to the user verbatim in a fenced `text` block. Do not recompute, round, re-rank, or add numbers. Afterward, add at most two sentences, and only when something needs explaining (for example partial coverage or an error hint).
- Never describe recorded token counts as remaining subscription allowance, and never present a cost estimate as a bill or a saving.
