---
description: Use when the user asks how to reduce Claude Code token usage or cost, or whether an optimization worked. Grounds advice in Boring Meter findings and experiments instead of generic tips.
allowed-tools: Bash(boring-meter analyze *) Bash(boring-meter experiment list*) Bash(boring-meter experiment show *)
---

Base advice on evidence from this user's own data:

1. Run `boring-meter analyze --json` (add `--project PATH` or `--session ID` when relevant) and use its findings. Each finding has evidence, confidence, a recommended action, and limitations. Lead with high-confidence findings.
2. If there are no findings, say so plainly. Do not invent problems.
3. Recommend actions; do not perform them. Never edit instruction files, switch models, or clear sessions on your own. For instruction file changes, point to `/boring-meter:optimize`, which shows a diff and needs explicit approval.
4. Suggest validating any change with `/boring-meter:experiment`: record two or more comparable baseline runs and two or more follow-up runs, then record task quality.
5. Do not promise percentages or savings. Only quote differences from `boring-meter experiment show ID`, using its classification (verified, directional, inconclusive, invalid).

If `boring-meter` is not on PATH, use `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"`. On Windows without Git Bash (PowerShell), use `& "${CLAUDE_PLUGIN_ROOT}/bin/boring-meter.cmd"`.
