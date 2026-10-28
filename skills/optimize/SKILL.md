---
description: Propose reviewable improvements to CLAUDE.md and other instruction files (remove word-for-word repeats, move task-specific material). Never changes a file without explicit confirmation.
argument-hint: "[--project PATH] | show ID | apply ID | save ID --output PATH"
disable-model-invocation: true
allowed-tools: Bash(boring-meter optimize) Bash(boring-meter optimize --project *) Bash(boring-meter optimize propose *) Bash(boring-meter optimize show *) Bash(boring-meter optimize save *)
---

Run the Boring Meter optimizer with the Bash tool:

```
boring-meter optimize $ARGUMENTS
```

Supported forms:
- `boring-meter optimize [--project PATH]` creates proposals and prints each diff. Nothing is changed.
- `boring-meter optimize show ID` prints a stored proposal and its diff.
- `boring-meter optimize save ID --output PATH` writes the proposed content to a new file. Add `--force` only if the user explicitly confirms replacing an existing file at PATH.
- `boring-meter optimize apply ID --confirm` changes the original file.

## Safety rules for apply (mandatory)

Never run `apply` on your own initiative. Before running `boring-meter optimize apply ID --confirm`:
1. Show the user the current content and the proposed diff (`boring-meter optimize show ID`).
2. Explain the expected benefit and the risk printed with the proposal.
3. Ask the user for explicit approval to apply that specific proposal id, and wait for a clear yes in their reply.
4. Only then run apply. It checks that the file has not changed, saves a backup, writes atomically, and verifies the result. Report its output exactly.

If the user does not approve, offer `save` or the copyable diff instead. Do not edit instruction files with Edit or Write tools as a substitute.

## How to run it

- Pass only the options listed above. If the arguments contain anything else (for example `;`, `|`, `&`, `$(`, backticks, or redirection), do not run anything. Explain the supported options instead.
- If `boring-meter` is not on PATH, run `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"` with the same arguments.
- Show the output to the user verbatim in a fenced `text` block. Do not recompute, round, re-rank, or add numbers. Afterward, add at most two sentences, and only when something needs explaining (for example partial coverage or an error hint).
- Never describe recorded token counts as remaining subscription allowance, and never present a cost estimate as a bill or a saving.
