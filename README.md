# Boring Meter

Local usage intelligence for Claude Code. Boring Meter reads the session transcripts Claude Code already keeps on your machine, summarizes the token usage they record, finds evidence-backed opportunities to reduce avoidable overhead, and helps you check whether a change actually worked.

Understand your usage. Find avoidable overhead. Improve your workflow. Verify the result.

Everything runs locally with the Python standard library. No network requests, no paid APIs, no accounts, no hosted LLM calls.

## Key features

- **Usage summaries** (`/boring-meter:usage`): input, output, cache read, and cache write tokens per period, session, model, day, and project, with explicit data coverage.
- **API cost estimates**: computed only when every token category and the model's list price are known, with the pricing version and assumptions shown. Unknown models are never priced.
- **Optimization findings** (`/boring-meter:analyze`): five deterministic rules, each finding with evidence, confidence, effort, risk, a recommended action, and limitations.
- **Instruction optimizer** (`/boring-meter:optimize`): analyzes CLAUDE.md and related files, proposes a reviewable diff, and never changes a file without explicit confirmation (with hash check, backup, and verification).
- **Reports** (`/boring-meter:report`): Markdown or JSON, printed or saved, never overwriting without confirmation.
- **Experiments** (`/boring-meter:experiment`): record baseline and follow-up runs, record quality, and get a classified comparison (verified, directional, inconclusive, or invalid).
- **Settings and privacy controls** (`/boring-meter:settings`): thresholds, pricing, retention, exclusions, export, and deletion of Boring Meter's own data.

## MVP limitations

- The only usage source is Claude Code's local transcript files. Their format is internal to Claude Code and undocumented; it was observed with Claude Code 2.1.229 to 2.1.311 and may change.
- Claude Code deletes transcripts after `cleanupPeriodDays` (default 30), so history older than that is not available.
- Transcripts contain no billed cost and no subscription quota. Boring Meter cannot show remaining plan allowance, and its cost figures are API list-price estimates, not what a subscription charges.
- Usage from claude.ai, the Claude desktop chat, other machines, or Amazon Bedrock and Google Cloud billing is not covered.
- Findings are heuristics with stated confidence. They never estimate savings; only experiments measure change.
- No HTML report, no dashboards, no team features (by design for the MVP).

## Compatibility

| Component | Verified |
| --- | --- |
| Claude Code | 2.1.311 (plugin validation, `--plugin-dir` load, marketplace install and uninstall, headless skill invocation) |
| Transcript format | Records written by Claude Code 2.1.229 to 2.1.311 |
| Python | 3.9.6 and 3.14.7 on macOS (full test suite on both) |
| Operating systems | Test suite passes in CI on Ubuntu 24.04, macOS and Windows with Python 3.9 and 3.12 (2026-10-28), and locally on macOS. Claude Code plugin install and invocation were verified on macOS only; running the `bin/boring-meter` sh launcher from Claude Code on Windows is not verified |

Other versions may work but have not been tested.

## Installation

Requirements: Claude Code with plugin support and Python 3.9 or newer on `PATH` as `python3`.

**Option 1, install from this folder (recommended):**

```bash
claude plugin marketplace add /path/to/boring-meter
```

```bash
claude plugin install boring-meter@boring-meter-local
```

Then start a new Claude Code session (or run `/reload-plugins` in a running one) and type `/boring-meter:usage`.

**Option 2, try it for one session without installing:**

```bash
claude --plugin-dir /path/to/boring-meter
```

Inside Claude Code you can also run `/plugin marketplace add /path/to/boring-meter` and `/plugin install boring-meter@boring-meter-local`.

The command-line tool also works outside Claude Code: `/path/to/boring-meter/bin/boring-meter usage --week`. When the plugin is enabled, `boring-meter` is on the PATH of Claude's Bash tool.

See [docs/installation.md](docs/installation.md) for details and verification steps.

## Command reference

| Command | What it does | Common options |
| --- | --- | --- |
| `/boring-meter:usage` | Usage summary with coverage and cost estimate | `--today`, `--week`, `--days N`, `--since/--until`, `--all`, `--session ID`, `--sessions`, `--project PATH`, `--source`, `--json` |
| `/boring-meter:analyze` | Ranked findings with evidence | period options, `--project PATH`, `--session ID`, `--limit N`, `--rules`, `--json` |
| `/boring-meter:optimize` | Instruction file proposals (diff only) | `--project PATH`, `show ID`, `save ID --output PATH`, `apply ID --confirm` |
| `/boring-meter:report` | Full report | period options, `--format markdown or json`, `--save`, `--output PATH`, `--force` |
| `/boring-meter:experiment` | Before-and-after experiments | `start`, `baseline`, `followup`, `outcome`, `list`, `show`, `delete` |
| `/boring-meter:settings` | Settings and data controls | `show`, `set KEY VALUE`, `sources`, `export`, `prune`, `reset --yes`, `delete-data --yes` |

Two further skills load automatically when relevant: `usage-intelligence` (how to read usage numbers) and `optimization-coach` (evidence-based advice). `boring-meter doctor` checks the installation.

Period semantics: `--week` is the last 7 calendar days including today, from local midnight six days ago until now. Days use your system timezone (DST aware) or `time.timezone`. Start is inclusive, end exclusive.

Typical experiment:

```bash
boring-meter experiment start --name "Trim CLAUDE.md" --change "Moved API notes to a path-scoped rule"
```

Then record two or more baseline sessions (`experiment baseline ID --session SESSION_ID`), apply the change, record two or more comparable follow-up sessions (`experiment followup ...`), record quality (`experiment outcome ID --quality preserved --completed yes`), and read the result with `experiment show ID`.

## Data sources and metrics

| Source | What it provides |
| --- | --- |
| Claude Code transcripts (`CLAUDE_CONFIG_DIR/projects/**/*.jsonl`, read-only) | Per-request input, output, cache read, and cache write tokens (with 5-minute and 1-hour split), model, session, start directory, timestamp, speed, tier, inference region, stop reason, tool names, and file paths passed to file tools |
| Boring Meter hook events (opt-in) | Which instruction files Claude Code loaded and when (metadata only) |
| Instruction files (read-only) | CLAUDE.md, CLAUDE.local.md, `.claude/rules`, AGENTS.md, imports, auto memory: sizes, repeats, code blocks |

Details, deduplication, and aggregation rules: [docs/data-sources.md](docs/data-sources.md).

## Cost estimation methodology

`cost = (input x input price + output x output price + cache reads x read price + 5-minute cache writes x 5m price + 1-hour cache writes x 1h price) / 1,000,000`

- Prices come from a versioned table (`src/boring_meter/pricing.json`, version `anthropic-api-list-2026-10-27`) taken from Anthropic's published API pricing on 2026-10-27.
- Fast mode, the US inference region multiplier (1.1x), and Claude Haiku 5.5 long-context prices are applied when the record says so.
- A request is left unpriced (and counted, with the reason) when its model has no price, a token category is missing, the cache write duration is unknown, or a modifier is not modeled. Dated model IDs map to prices only through an explicit alias table.
- Excluded: Batch discounts, Priority Tier, server-side tool fees, taxes, credits, negotiated discounts, and partner cloud pricing.
- Transcripts carry no billed cost, so there is never a source-reported cost to show.

Use your own prices with `boring-meter settings set pricing.file /path/to/pricing.json` (same format as the bundled file).

## Privacy and local storage

- Reads Claude Code files read-only and never modifies or deletes them.
- Stores only metadata: token counts, identifiers, model names, timestamps, tool names, and file paths. No prompts, responses, tool inputs, or file contents are stored.
- Makes no network requests. There is no telemetry.
- Data lives in one directory: `~/Library/Application Support/boring-meter` (macOS), `$XDG_DATA_HOME/boring-meter` or `~/.local/share/boring-meter` (Linux), `%LOCALAPPDATA%\boring-meter` (Windows), or `BORING_METER_DATA_DIR`. Files are created with owner-only permissions where supported.

Full details: [docs/privacy.md](docs/privacy.md).

## Configuration

Run `boring-meter settings show` for every setting with its description. Main options:

| Setting | Default | Purpose |
| --- | --- | --- |
| `sources.claude_transcripts` | true | Read Claude Code transcripts |
| `sources.extra_transcript_dirs` | [] | Extra transcript folders |
| `collection.instruction_events` | false | Opt-in instruction load hook |
| `pricing.enabled`, `pricing.file` | true, bundled | Cost estimates and pricing source |
| `thresholds.*` | see `settings show` | Rule thresholds |
| `retention.event_days`, `retention.export_days` | 90, 90 | Retention for Boring Meter's own data |
| `privacy.excluded_projects` | [] | Projects left out of everything |
| `privacy.show_full_paths` | false | Full paths in findings |
| `time.timezone` | system | Calendar day timezone |
| `logging.level` | warning | Diagnostics on stderr |

Settings apply on the next command. Nothing requires restarting Claude Code except installing or updating the plugin itself (use `/reload-plugins`).

## Testing

```bash
python3 -m unittest discover -s tests -t .
```

The suite has 147 tests: unit tests for every module (including each platform branch of the data directory choice, simulated, and disk-full handling during atomic writes), integration tests that run the real launcher as a subprocess (on Windows they run `python -m boring_meter` with `src` on `PYTHONPATH` instead, and the missing-runtime launcher test is skipped) (acceptance scenarios A to L, offline execution with sockets blocked, missing Python runtime, concurrent writers, the hook script, a 10,000-record benchmark), and plugin validation through the `claude` CLI when it is installed. All fixtures are synthetic and generated into temporary directories (`tests/fixtures/build.py`).

GitHub Actions runs the same command on `ubuntu-24.04`, `macos-latest` and `windows-latest` with Python 3.9 and 3.12 (`.github/workflows/tests.yml`). The `claude` CLI is not installed there, so plugin validation is skipped in CI. On Windows, two more tests skip: the daylight-saving test (Windows Python has no timezone database unless `tzdata` is installed) and the sh launcher runtime test.

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md). Start with `boring-meter doctor`.

## Uninstall

```bash
claude plugin uninstall boring-meter@boring-meter-local
```

Optionally remove the marketplace with `claude plugin marketplace remove boring-meter-local`. Boring Meter's own data directory is not inside Claude Code's plugin data folder, so delete it explicitly if you want it gone: run `boring-meter settings delete-data --yes` before uninstalling, or remove the directory shown by `boring-meter settings path`.

## Contributing

- Keep the runtime dependency-free (Python standard library only) and the core pipeline offline.
- Every new rule needs the metadata in `rules.py`, unit tests, and documentation in [docs/rules.md](docs/rules.md).
- Never add a value that is not observed or derived from observed data. Unknown stays unknown.
- Writing rule: no em dash characters anywhere. The test suite enforces this.
- Run the full test suite before submitting changes.

## License

No license has been selected yet. Until one is chosen, all rights are reserved by the author.
