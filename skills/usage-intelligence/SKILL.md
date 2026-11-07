---
description: Use when the user asks how many tokens they used, where their Claude Code usage went, what a session cost at API prices, or how to read Boring Meter output. Explains observed versus estimated values.
allowed-tools: Bash(boring-meter usage *) Bash(boring-meter sources*)
---

To answer usage questions, get data from Boring Meter instead of guessing:

- `boring-meter usage --json` (add `--today`, `--week`, `--days N`, or `--session ${CLAUDE_SESSION_ID}` for this session)
- `boring-meter sources` to see which data exists

If `boring-meter` is not on PATH, use `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"`. On Windows without Git Bash (PowerShell), use `& "${CLAUDE_PLUGIN_ROOT}/bin/boring-meter.cmd"`.

How to interpret the output:
- Token counts are observed values copied from Claude Code's local transcripts. Input, output, cache read, and cache write are separate categories; "total tokens" is their sum.
- Cache reads are re-sent context served from the prompt cache at a reduced price. A high cache-read share is normal for long sessions.
- The cost is an estimate at Anthropic API list prices, with the pricing version shown. It is not what a subscription plan charges, and it is not a bill.
- Values shown as unknown are unknown. Never treat them as zero.
- Coverage "partial" means some of the period or some fields are missing. Say so when you quote numbers.
- Boring Meter cannot see remaining subscription allowance or plan limits. Do not estimate them.

Quote numbers exactly as printed. Do not invent, round, or extrapolate figures.
