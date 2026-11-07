# Current status and pending tasks

Snapshot: 2026-11-07. VERIFIED unless marked.

## Status

- Version **0.1.0**, released publicly as **v0.1.0-beta** ("Boring Meter 0.1.0 (Beta)", marked Latest) at https://github.com/Satyam2701/boring-meter with `boring-meter-0.1.0.zip` attached.
- Repository is **public**, MIT licensed, default branch `main`, single branch.
- All PRD P0 requirements are implemented; see [requirements-checklist.md](requirements-checklist.md).
- 154 tests pass locally (macOS, Python 3.9.6 and 3.14.7) and in CI on Ubuntu 24.04, macOS and Windows with Python 3.9 and 3.12. On Windows CI this includes the `.cmd` launcher, the sh launcher under Git Bash, missing-Python handling, and the hook through the launcher (2026-11-07).
- Install verified in Claude Code 2.1.311 on macOS: GitHub marketplace install (signed in and anonymous), local clone, zip, `--plugin-dir`.
- Installed on the owner's old MacBook (user scope, from `Satyam2701/boring-meter`).
- Performance: 10,000 records summarized in 0.34 s cold and 0.20 s cached; about 18,000 real transcript lines parse in about 1.3 s cold.

## Known gaps

- A full Claude Code session on Windows has not been observed. Both launchers pass on Windows CI. Known limit: without Git for Windows, Claude Code runs the shell-form hook in PowerShell, which cannot run the sh launcher, so a hook error notice may appear (the plugin's commands still work through `boring-meter.cmd`).
- The typed `/boring-meter:usage` command was not observed in the desktop Code tab; a fresh session ran the guidance skill instead because command skills are user-only. The CLI path was verified headless.
- R3 can flag Claude desktop scratch folders as "unrelated directories" (heuristic false positive seen on real data).
- `claude plugin validate` warns about the root `CLAUDE.md` (it is for development sessions, not plugin context; harmless).

## Pending tasks

| Priority | Task | Status |
| --- | --- | --- |
| Owner | Delete the old private repo `Satyam2701/boring-meter-old` (it contained the work email in PR #1 commits) | DONE 2026-11-07 |
| Beta | Recruit 10 to 20 testers, collect `boring-meter report --save` output and feedback (PRD section 21) | Not started |
| P1 | Windows launcher fix (`.cmd` launcher, robust Python detection, hook via launcher) | DONE 2026-11-07, CI verified |
| Beta | Confirm a real Claude Code session on Windows (a beta tester) | Not started |
| P1 | Rule: costly cache rewrite after resuming a session past cache expiry | Idea |
| P1 | Project comparisons, historical trends, optional static HTML report, more adapters | Not started |
| Optional | Plugin icon (`.claude-plugin/icon.png`, 512 to 2048 px) for directory listing | Not started |
| Optional | Submit to Anthropic's plugin directory | Not started |

## Release process (VERIFIED from what was done)

1. Bump `version` in `.claude-plugin/plugin.json` and update `CHANGELOG.md`.
2. Run the test suite; push to `main`; wait for CI green.
3. `git archive --format=zip --prefix=boring-meter/ -o dist/boring-meter-X.Y.Z.zip HEAD`
4. `gh release create vX.Y.Z --repo Satyam2701/boring-meter --title "..." --notes-file notes.md dist/boring-meter-X.Y.Z.zip`
5. Users update with `claude plugin marketplace update boring-meter`.
