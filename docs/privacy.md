# Privacy and local storage

## Defaults

- Local-only processing. Boring Meter makes no network requests; the test suite runs every core command with sockets blocked.
- No telemetry, analytics, uploads, accounts, or external LLM calls.
- Claude Code's own files are opened read-only and never modified or deleted.
- No prompts, responses, tool inputs, tool outputs, file contents, environment variables, or credentials are stored.
- Optional collection (the instruction load hook) is off until you enable it.

## What is stored

All data lives in one directory:

| Platform | Location |
| --- | --- |
| macOS | `~/Library/Application Support/boring-meter` |
| Linux | `$XDG_DATA_HOME/boring-meter`, or `~/.local/share/boring-meter` |
| Windows | `%LOCALAPPDATA%\boring-meter` |
| Any | `BORING_METER_DATA_DIR` overrides the above |

`boring-meter settings path` prints it. Folders are created with owner-only permissions (0700) and files with 0600 where the file system supports it.

| Path | Contents | Retention |
| --- | --- | --- |
| `config.json` | Settings you changed | Until reset |
| `cache/transcripts-*.json` | Parsed metadata per transcript file: token counts, ids, model, timestamps, tool names, file paths used by file tools | Entries for deleted transcripts are dropped on the next run |
| `events/instructions.jsonl` | Opt-in instruction load metadata | `retention.event_days` (default 90) |
| `experiments/experiments.json` | Experiments and their measured runs | Until you delete them |
| `proposals/` | Proposed instruction file changes and diffs | Until you delete the data directory |
| `backups/` | Copies of files before an approved `optimize apply` | Until you delete them |
| `exports/` | Reports saved with `--save` | `retention.export_days` (default 90) |

Retention cleanup runs at most once a day, or on demand with `boring-meter settings prune`. It only touches Boring Meter's own files, never Claude Code transcripts.

## Controls

- Leave projects out of everything: `boring-meter settings set privacy.excluded_projects "/path/a,/path/b"`.
- Show full paths instead of project-relative paths in findings: `privacy.show_full_paths`.
- Turn off transcript reading: `sources.claude_transcripts false`.
- Turn off the parse cache: `cache.enabled false`.
- Export Boring Meter's own records: `boring-meter settings export --output FILE`.
- Delete all of Boring Meter's data: `boring-meter settings delete-data --yes`.

## Security measures

- Output paths are validated: no directories, no missing parent folders, nothing inside Claude Code's config directory, and no overwriting without `--force`.
- Proposal ids are validated before any path is built from them.
- Imports in instruction files are followed only inside the project or home directory. Symlinks out of transcript folders are not followed.
- No shell commands are built from data. The skills tell Claude to refuse arguments containing shell metacharacters.
- Analyzed files are never executed.
- Error messages show shortened paths (`~`) and no file contents.
