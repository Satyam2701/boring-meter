# Architecture and tech stack

All content VERIFIED against the code on 2026-11-07 unless marked.

## Tech stack

| Item | Choice | Notes |
| --- | --- | --- |
| Runtime | Python 3.9+ standard library only | No third-party packages, no lockfile needed. Tested on 3.9.6, 3.12 (CI), 3.14.7 |
| Launchers | `bin/boring-meter` (sh) and `bin/boring-meter.cmd` (Windows) | Try `python3`, `python`, `py -3`, run each to confirm 3.9+, then run `scripts/run_boring_meter.py`. Exit 3 if no Python; `--run-hook` exits 0 instead |
| Host | Claude Code plugin | Verified with Claude Code 2.1.311 |
| Tests | `unittest` | `python3 -m unittest discover -s tests -t .` |
| CI | GitHub Actions `.github/workflows/tests.yml` | Ubuntu 24.04, macOS, Windows x Python 3.9 and 3.12 |
| Storage | JSON and JSONL files | No database, no server |
| Network | None | Core never makes network requests (tested with sockets blocked) |

APIs and databases: NOT APPLICABLE. Boring Meter calls no external API and uses no database. The Anthropic Usage and Cost Admin API was deliberately not used (needs an admin key and network).

## Repository layout

```text
.claude-plugin/plugin.json        plugin manifest (name boring-meter, version 0.1.0, MIT)
.claude-plugin/marketplace.json   one-plugin marketplace named boring-meter (source "./")
bin/boring-meter                  sh launcher (macOS, Linux, Git Bash), on the Bash tool PATH while the plugin is enabled
bin/boring-meter.cmd              Windows launcher (PowerShell, CMD)
scripts/run_boring_meter.py       shared Python entry point; finds src/ from its own location
.gitattributes                    LF endings everywhere (a CRLF sh launcher breaks Git Bash), CRLF for .cmd
skills/<name>/SKILL.md            usage, analyze, optimize, report, experiment, settings (user-only, disable-model-invocation)
                                  usage-intelligence, optimization-coach (model-invocable guidance)
hooks/hooks.json                  InstructionsLoaded hook (runs the launcher with --run-hook)
scripts/hook_instructions_loaded.py  opt-in metadata recorder; always exits 0
src/boring_meter/                 engine (modules below)
tests/unit, tests/integration     unittest suites; tests/fixtures/build.py generates synthetic data
docs/                             user and project documentation
```

## Engine modules (`src/boring_meter/`)

| Module | Responsibility |
| --- | --- |
| `cli.py` | argparse commands, text and JSON rendering, empty states, retention maintenance, doctor |
| `adapters.py` | source discovery, transcript parsing, normalization, dedup, parse cache, hook events |
| `aggregate.py` | period filtering, category totals, coverage, cost summary |
| `pricing.py` + `pricing.json` | versioned list-price table and per-record cost |
| `rules.py` | five rules, finding structure, priority scoring |
| `instructions.py` | discovery and analysis of CLAUDE.md, rules, imports, auto memory |
| `optimize.py` | proposals (diff), confirmed apply with hash check and backup |
| `experiments.py` | runs, comparability checks, classification |
| `config.py` | settings schema, validation, persistence |
| `store.py` | atomic writes, lock files, tolerant JSONL reading |
| `paths.py` | data directory, Claude config directory, output path validation |
| `timeutil.py` | timestamp parsing, timezones, periods |
| `render.py`, `errors.py` | plain-text helpers, structured errors |

## Data flow

1. `adapters.load_dataset` walks `CLAUDE_CONFIG_DIR/projects/**/*.jsonl` (default `~/.claude/projects`) plus configured extra folders, read-only.
2. `scan_transcript` turns each assistant line with `message.usage` into a normalized record (four disjoint token categories, model, session, start directory, timestamp, speed, tier, region) and collects session signals (tool names, Read/Write paths, compactions, idle gaps). No message text is kept.
3. Duplicates merge by `message.id` + `requestId`; the line with the highest `output_tokens` wins (earlier lines can carry partial mid-stream counts).
4. Results are cached per file by size and mtime in the data directory (`cache/transcripts-a1-c3.json`; bump `CACHE_FORMAT` when scan output changes).
5. Commands filter by period, project or session, then aggregate, price, run rules, or measure experiment runs.

## Local data (outside Git, regenerable)

Data directory: `~/Library/Application Support/boring-meter` (macOS), `$XDG_DATA_HOME/boring-meter` or `~/.local/share/boring-meter` (Linux), `%LOCALAPPDATA%\boring-meter` (Windows), overridable with `BORING_METER_DATA_DIR`. Holds config, parse cache, opt-in hook events, experiments, proposals, backups and exports. See [privacy.md](privacy.md).

## Environment variables (all optional, no secrets)

| Variable | Purpose |
| --- | --- |
| `BORING_METER_DATA_DIR` | Override the data directory |
| `CLAUDE_CONFIG_DIR` | Claude Code config directory to read transcripts from (default `~/.claude`) |
| `BORING_METER_DEBUG=1` | Show tracebacks for internal errors |

No `.env` file is used, so there is no `.env.example`.

## Key invariants

- Unknown values stay `None`, never 0. Totals count only known values and report missing counts.
- Costs are priced only when every category and modifier is known; dated model ids map only through the explicit alias table.
- Files are changed only by `optimize apply ... --confirm` after a hash check and backup.
- No em dash anywhere in the repository (enforced by `tests/unit/test_copy_rules.py`).
