# Data sources

Boring Meter discovers sources only in documented locations and explicitly configured folders. It never scans the whole file system. Run `boring-meter sources` to see what was found.

## 1. Claude Code transcripts (`claude-code-transcripts`, adapter version 1)

| Property | Value |
| --- | --- |
| Type | Local JSONL files written by Claude Code, read-only |
| Discovery | `CLAUDE_CONFIG_DIR/projects/**/*.jsonl` (default `~/.claude/projects`), including subagent transcripts, plus `sources.extra_transcript_dirs` |
| Schema | Undocumented internal format, observed with Claude Code 2.1.229 to 2.1.311 |
| Timestamp meaning | UTC time Claude Code wrote the line, close to when the response finished |
| Values | Observed: copied from the Anthropic API `usage` object on each assistant line |
| Completeness | As complete as the files on disk. Claude Code deletes transcripts after `cleanupPeriodDays` (default 30) |

### Fields used

| Normalized field | Transcript source |
| --- | --- |
| `input_tokens` | `message.usage.input_tokens` |
| `output_tokens` | `message.usage.output_tokens` |
| `cache_read_tokens` | `message.usage.cache_read_input_tokens` |
| `cache_creation_tokens` | `message.usage.cache_creation_input_tokens` |
| `other_token_metrics.cache_creation_5m` / `_1h` | `message.usage.cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens` |
| `other_token_metrics.thinking_tokens_subset_of_output` | `message.usage.output_tokens_details.thinking_tokens` (already part of output, never added again) |
| `model` | `message.model` (`<synthetic>` marks Claude Code placeholders, excluded from totals) |
| `session_id`, `timestamp` | `sessionId`, `timestamp` |
| `project_id` | First `cwd` seen in the session (the directory it started in) |
| `speed`, `service_tier`, `inference_geo` | `message.usage` fields of the same names |

Never read: message text, prompts, tool inputs other than `file_path` or `notebook_path` on tool calls, and tool results.

### Token semantics and aggregation

In the Anthropic Messages API the four token categories are disjoint: `input_tokens` excludes cache reads and cache writes. Boring Meter therefore:

- sums each category separately, counting only records where that category is known;
- reports records missing a category as "missing", never as zero (a recorded zero stays zero);
- computes "total tokens" as the sum of all four categories, only over records where all four are known, and states how many records were excluded.

### Deduplication

- Claude Code writes one line per content block, so a single API response appears on several lines with the same `message.id` and `requestId`. Earlier lines can carry a partial, mid-stream `output_tokens` value. The record kept is the line with the highest `output_tokens`, the later line on ties.
- Stable key: `message.id` + `requestId`. Fallbacks, in order: `message.id`; the line's `uuid`; a SHA-256 fingerprint of file path and line number.
- The same key in another file (a forked session or a rotated copy) is merged and counted under "duplicates merged".
- Records are never deduplicated by timestamp and token counts.

### File handling

| Situation | Behavior |
| --- | --- |
| Missing or unreadable folder | Reported in `sources`; other sources continue |
| Empty file | Read as zero records |
| Malformed line | Skipped and counted; coverage is marked partial |
| Truncated final line (partial write) | Skipped and counted separately |
| Non-transcript JSONL (for example workflow journals) | Ignored and counted as non-transcript |
| File larger than `sources.max_file_mb` | Skipped and listed |
| Symlink pointing outside the source folder | Not followed, listed as skipped |
| Changed or rotated files | Re-parsed; a size and mtime cache avoids re-reading unchanged files |
| Concurrent runs | Cache writes use an exclusive lock and atomic replace; a lock timeout skips the cache update, not the report |

## 2. Boring Meter hook events (`boring-meter-hook-events`, opt-in)

| Property | Value |
| --- | --- |
| Type | Local JSONL in `<data dir>/events/instructions.jsonl` |
| Producer | This plugin's `InstructionsLoaded` hook, only when `collection.instruction_events` is true |
| Fields | `ts`, `session_id`, `file_path`, `memory_type`, `load_reason`, `size_bytes`, `line_count` |
| Values | Observed metadata. Contains no token counts |
| Missing payload fields | If `file_path` is missing, nothing is recorded |

Used by rule R1 to report how often instruction files were loaded.

## 3. Instruction files (read-only analysis)

Locations follow Claude Code's memory documentation: `~/.claude/CLAUDE.md`, `~/.claude/rules/`, `CLAUDE.md` and `CLAUDE.local.md` in the project and every parent directory, `.claude/CLAUDE.md`, `.claude/rules/` (rules with `paths` frontmatter load on demand), `AGENTS.md` when no CLAUDE.md exists, `@path` imports up to 4 hops (only inside the project or home directory), auto memory `MEMORY.md` (first 200 lines or 25KB), and nested `CLAUDE.md` files (on demand). Files over 1 MB are skipped. The nested scan is bounded to 4,000 folders or 1.5 seconds and reports when it stops early.

Sizes are measured exactly. Token figures for instruction files are estimates (characters / 4) and always labeled as estimates.

## Not available

- Billed cost, invoices, credits, and subscription quota or remaining allowance.
- Usage outside Claude Code on this machine.
- The Anthropic Usage and Cost Admin API requires an admin API key and network access. It is not used, to keep the product local and free of credentials.
- Hook payloads do not carry token usage, so hooks are not used for token collection.
