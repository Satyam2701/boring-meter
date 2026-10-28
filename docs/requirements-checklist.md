# P0 requirements checklist

Audit of the PRD's P0 scope and Definition of Done against this implementation (2026-10-28). Evidence points to code or tests.

## P0 scope

| Requirement | Status | Evidence |
| --- | --- | --- |
| Valid Claude Code plugin package | Done | `claude plugin validate` passes; `PluginValidation` test |
| Namespaced slash commands | Done | `skills/*/SKILL.md` give `/boring-meter:usage`, `analyze`, `optimize`, `report`, `experiment`, `settings`; discovered by `claude plugin details`; headless `/boring-meter:usage` run succeeded |
| Local usage data discovery | Done | `adapters.discover_sources`, `boring-meter sources`; documented locations only |
| Robust parsing of supported records | Done | `scan_transcript`; tests for malformed, truncated, empty, non-transcript, symlink, large files |
| Session and daily summaries | Done | `aggregate.summarize` (`by_day`, `--session`, `--sessions`) |
| Token category breakdowns | Done | Four categories plus 5m and 1h cache write split |
| Basic cost estimation with explicit assumptions | Done | `pricing.py`, `pricing.json`; Scenario D and E tests |
| Project instruction analyzer | Done | `instructions.py`; discovery tests |
| Rule-based optimization engine | Done | `rules.py`, five rules with metadata and tests |
| Recommendations with evidence and confidence | Done | Finding structure; `test_rules.py` |
| Terminal report and JSON export | Done | `report` (Markdown and JSON, `--save`, `--output`); every command has `--json` |
| Before-and-after experiment recording | Done | `experiments.py`; unit and CLI tests |
| Local settings and privacy controls | Done | `config.py`, `settings` command, exclusions, retention, export, delete |
| Automated tests and documentation | Done | 135 tests; README and `docs/` |

## Acceptance scenarios

| Scenario | Status | Test |
| --- | --- | --- |
| A First installation | Passed | Clean isolated install, list, details, uninstall (manual run, 2026-10-28); `PluginValidation`; headless invocation |
| B Valid usage data | Passed | `test_b_valid_usage_totals_and_coverage` |
| C Missing metrics | Passed | `test_c_missing_output_reported_as_unknown` |
| D Cost estimation | Passed | `test_d_cost_matches_independent_calculation`, `test_pricing.py` |
| E Unknown pricing | Passed | `test_e_unknown_pricing_not_fabricated` |
| F Optimization finding | Passed | `test_f_findings_with_evidence_and_no_modification` |
| G Safe optimization | Passed | `test_g_safe_optimization_flow`, `test_apply_without_confirmation_leaves_file_unchanged` |
| H Invalid data | Passed | `test_h_corrupted_record_keeps_valid_records` |
| I Experiment validation | Passed | `test_i_experiment_cli_flow`, `test_experiments.py` |
| J Privacy | Passed | `test_j_k_no_network_and_no_raw_content`, `test_no_message_content_is_stored` |
| K Offline mode | Passed | Same test, with sockets blocked |
| L No data access | Passed | `test_l_no_data_access_empty_state` |

## Error cases (PRD section 15)

| Case | Handling |
| --- | --- |
| Plugin installed incorrectly | `boring-meter doctor` checks plugin files; `claude plugin validate` |
| Unsupported Claude Code version | Transcript versions shown by `doctor`; files without recognizable lines are ignored and counted; "no token usage records" empty state. No hard version gate (see limitations) |
| Runtime dependency missing | Launcher exits 3 with `RUNTIME_MISSING`; Python older than 3.9 exits 3 (tested for missing runtime) |
| Usage source unavailable | Source status and empty state (Scenario L) |
| Corrupted local record | Malformed lines skipped and counted; corrupt cache rebuilt; corrupt state files raise `CORRUPTED_RECORD` |
| Permission denied | `PERMISSION_DENIED` mapping; unreadable transcripts listed as skipped |
| Storage full | `STORAGE_FULL` mapping (not exercised by a test) |
| Invalid configuration | `INVALID_CONFIG` with hint (tested) |
| Unknown model pricing | Left unpriced with reason (tested) |
| Unsupported source schema | Non-transcript files ignored; config and pricing schema versions checked (tested) |
| Duplicate events | Deduplication by stable key (tested) |
| Concurrent writers | Lock files and atomic writes (thread and process tests) |
| Invalid experiment comparison | `invalid` classification with reasons (tested) |
| Failed report export | `OUTPUT_EXISTS`, `INVALID_OUTPUT_PATH` (tested) |
| Invalid output path | Validated (tested) |
| Interrupted collection | Atomic writes; Ctrl+C message; stale locks recovered (tested) |
| Clock or timezone mismatch | Future timestamps flagged (tested); configurable timezone |
| Missing hook payload fields | Nothing recorded without `file_path` (tested) |

## Definition of Done

| Item | Status |
| --- | --- |
| Follows the current official plugin format | Yes (validated with Claude Code 2.1.311) |
| Required commands discoverable and executable | Yes |
| Supported data sources documented | Yes (`docs/data-sources.md`) |
| Token values preserve source semantics | Yes |
| Unknown metrics remain unknown | Yes |
| Cost calculations reproducible | Yes (versioned table, hand-calculated tests) |
| At least three rules implemented and tested | Yes (five) |
| Every finding has evidence and an action | Yes |
| File modifications require explicit confirmation | Yes |
| Local reporting without paid APIs | Yes |
| Privacy and retention documented | Yes (`docs/privacy.md`) |
| Experiments work with valid data | Yes |
| Unit and integration tests pass | Yes, 135 of 135 on Python 3.9.6 and 3.14.7 |
| End-to-end tests in a supported environment | Yes on macOS with Claude Code 2.1.311; not run on Linux or Windows |
| Installation and troubleshooting documentation | Yes |
| No secrets or unnecessary user content collected | Yes |
| No em dashes | Yes (enforced by `test_copy_rules.py`) |

## Not done or partial

- License: not selected (owner decision). `claude plugin validate --profile directory` flags this for directory submission.
- Linux and Windows: implemented, not tested.
- Storage-full handling is implemented but not exercised by an automated test.
- No hard Claude Code version gate: the transcript format is undocumented, so compatibility is detected from data instead.
