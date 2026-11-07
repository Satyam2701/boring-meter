# Decision log

Decisions made while building and releasing Boring Meter (2026-10-27 to 2026-10-28). VERIFIED from the build session and Git history.

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-10-27 | Python standard library only, no packages | PRD: no paid or network dependencies; Python 3 ships on macOS; zero install step |
| 2026-10-27 | Usage source = Claude Code transcripts (`~/.claude/projects/**/*.jsonl`) | Only real local token data; hook payloads carry no token usage (verified in hooks docs) |
| 2026-10-27 | Treat the four API token categories as disjoint and sum them | Anthropic `usage` semantics: `input_tokens` excludes cache reads and writes |
| 2026-10-27 | Dedup by `message.id` + `requestId`, keep highest `output_tokens` | Claude Code writes one line per content block; 941 real repeats had partial mid-stream output counts |
| 2026-10-27 | Pricing table from the live Anthropic pricing page, versioned `anthropic-api-list-2026-10-27` | Bundled skill reference was stale (Sonnet 5.5 cache read is $0.10, not $0.20); unknown models never priced |
| 2026-10-27 | Records with `inference_geo` `not_available` or missing, and missing `speed`, priced at standard rates | Otherwise most older records would be unpriceable; stated as an explicit assumption |
| 2026-10-27 | Skills instead of `commands/`; six command skills `disable-model-invocation: true` | Docs recommend skills; keeps always-on context small (about 533 tokens) |
| 2026-10-27 | Skills run `boring-meter` from `bin/` via Bash with `allowed-tools`, not `!` injection | Avoids shell injection of `$ARGUMENTS`; works when skill shell execution is disabled |
| 2026-10-27 | Own data directory, not `CLAUDE_PLUGIN_DATA` | That variable is exported to hooks but not to Bash tool commands, which would split data |
| 2026-10-27 | InstructionsLoaded hook is opt-in and metadata only | Privacy by default |
| 2026-10-27 | Optimizer auto-applies only removal of exact repeated lines within one file, with confirmation | Smallest deterministic change; everything else advisory |
| 2026-10-27 | Experiments need 2+ runs per side, same models, recorded quality and completion for "verified" | PRD: no savings claims from non-comparable data |
| 2026-10-27 | Priority = 3 x confidence + 2 x benefit - effort - risk | Confidence must dominate so speculative findings never outrank high-confidence ones |
| 2026-10-27 | Request project = directory the session started in | Sessions that `cd` into subfolders were split into fake projects |
| 2026-10-28 | Cross-platform CI; pin Ubuntu 24.04 | `ubuntu-latest` (26.04) has no Python 3.9 |
| 2026-10-28 | Windows fixes: lock PermissionError means busy; normalized path comparison; UTC without tzdata | Found by CI |
| 2026-10-28 | MIT license | Owner choice |
| 2026-10-28 | Removed Claude co-author trailers from history; attribution disabled in owner's user settings | Owner request |
| 2026-10-28 | Marketplace renamed `boring-meter-local` to `boring-meter` | Public install command `boring-meter@boring-meter` |
| 2026-10-28 | Work email replaced in history; public repo recreated fresh; old repo renamed `boring-meter-old` | Merged PR refs keep old commits permanently and cannot be rewritten |
| 2026-10-28 | Release marked Latest instead of pre-release; "Beta" in title, tag, notes, README, description | Pre-releases are hidden from the GitHub sidebar |
