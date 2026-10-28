---
description: Produce a Boring Meter report (period, data completeness, observed usage, cost estimate, top findings, verified and unverified experiment outcomes) as Markdown or JSON.
argument-hint: "[--week | --days N | --all] [--project PATH] [--format markdown|json] [--save | --output PATH]"
disable-model-invocation: true
allowed-tools: Bash(boring-meter report *) Bash(boring-meter report)
---

Run the Boring Meter report with the Bash tool:

```
boring-meter report $ARGUMENTS
```

Supported options: `--today`, `--week`, `--days N`, `--since YYYY-MM-DD`, `--until YYYY-MM-DD`, `--all`, `--project PATH`, `--format markdown|json`, `--json`, `--save` (writes to Boring Meter's exports folder), `--output PATH`.

The report refuses to overwrite an existing file. Add `--force` only after the user explicitly confirms replacing that file.

When the report is printed rather than saved, show it verbatim (it is already Markdown). When it is saved, tell the user the path that was printed.

## How to run it

- Pass only the options listed above. If the arguments contain anything else (for example `;`, `|`, `&`, `$(`, backticks, or redirection), do not run anything. Explain the supported options instead.
- If `boring-meter` is not on PATH, run `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"` with the same arguments.
- Show the output to the user verbatim in a fenced `text` block. Do not recompute, round, re-rank, or add numbers. Afterward, add at most two sentences, and only when something needs explaining (for example partial coverage or an error hint).
- Never describe recorded token counts as remaining subscription allowance, and never present a cost estimate as a bill or a saving.
