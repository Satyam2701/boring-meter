# Troubleshooting

Start with `boring-meter doctor`. It checks Python, the plugin files, the data directory, the pricing table, transcript access, the transcript versions seen, and unparseable data.

Errors print as `Boring Meter error [CODE]: message` with a `Hint:` line. With `--json`, errors are `{"error": {"code", "message", "hint"}}`. Exit codes: 0 success, 1 internal error or a failing doctor check, 2 user, data, or configuration error, 3 missing or unsupported runtime.

| Symptom or code | Cause | Fix |
| --- | --- | --- |
| `/boring-meter:usage` is not offered | Plugin not installed, not enabled, or not reloaded | `claude plugin list`; install per [installation.md](installation.md); run `/reload-plugins` or start a new session |
| `claude plugin validate` errors | Files moved or edited | Restore the layout: `.claude-plugin/plugin.json`, `skills/`, `hooks/hooks.json`, `bin/`, `src/` |
| `boring-meter: command not found` inside Claude Code | Plugin `bin/` not on PATH (older Claude Code, or plugin disabled) | The skills fall back to `"${CLAUDE_PLUGIN_ROOT}/bin/boring-meter"`; or run the full path yourself |
| `RUNTIME_MISSING` (exit 3) | No Python 3 on PATH | Install Python 3.9 or newer |
| `UNSUPPORTED_PYTHON` (exit 3) | Python older than 3.9 | Put a newer `python3` first on PATH |
| "No readable Claude Code transcripts were found" | Transcripts in a non-default place, `CLAUDE_CONFIG_DIR` differs, or permissions | `boring-meter sources`; `boring-meter settings set sources.extra_transcript_dirs /path` |
| "No recorded requests in this period" | No data for that period (not zero usage) | Use `--all` or a wider `--days`; transcripts older than `cleanupPeriodDays` are deleted by Claude Code |
| Coverage "partial" | Malformed or truncated lines, missing token fields, skipped files, or the period starts before the earliest record | Read the coverage notes; `boring-meter sources` lists skipped files |
| Cost "Not available" or "partial" | Unknown model, missing token category, unknown cache duration, unmodeled modifier, or pricing disabled | The unpriced reasons are listed; add prices with `pricing.file` if you have authoritative ones |
| `INVALID_PRICING` warning | Custom pricing file is invalid | Fix it, or `boring-meter settings set pricing.file ""` |
| `INVALID_CONFIG` | Invalid value in `config.json` | Fix with `settings set`, or `boring-meter settings reset --yes` |
| `CORRUPTED_RECORD` | A Boring Meter state file is not valid JSON | Move the named file aside; Claude Code data is unaffected |
| `PERMISSION_DENIED` | No access to a file or folder | Fix permissions, or set `BORING_METER_DATA_DIR` |
| `STORAGE_FULL` | Disk full | Free space; lower retention |
| `LOCK_TIMEOUT` | Another Boring Meter process is writing | Wait and retry. Locks older than 60 seconds are treated as abandoned |
| `OUTPUT_EXISTS` | Export target exists | Choose another name, or add `--force` after confirming |
| `INVALID_OUTPUT_PATH` | Directory, missing parent folder, or a path inside Claude Code's config directory | Choose a file in an existing folder |
| `INVALID_EXPERIMENT` / result `invalid` | Missing runs, incomplete data, different models, or the same session recorded twice | Record comparable runs; see `experiment show ID` reasons |
| `PROPOSAL_STALE` | The file changed after the proposal was made | Run `/boring-meter:optimize` again |
| Records with future timestamps | System clock or timezone wrong | Check the clock; set `time.timezone` if days look shifted |
| Hook events not recorded | Collection disabled, or the plugin was installed in this session | `settings set collection.instruction_events true`; `/reload-plugins` |
| Interrupted command | Ctrl+C | Safe: writes are atomic, so files are either old or complete |
| Internal error | Bug | Rerun with `BORING_METER_DEBUG=1` for a traceback |

Run with `boring-meter settings set logging.level debug` to see timings and cache notes on stderr.
