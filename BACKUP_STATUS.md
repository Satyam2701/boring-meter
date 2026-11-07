# Backup status

Checked: 2026-11-07. Repository: https://github.com/Satyam2701/boring-meter (public, branch `main`).

| Requirement | Status |
| --- | --- |
| Source code preserved | COMPLETED |
| Git history preserved | COMPLETED |
| PRDs recovered/reconstructed | COMPLETED |
| Technical documentation | COMPLETED |
| CLAUDE.md | COMPLETED |
| Claude configurations | COMPLETED |
| Environment setup | COMPLETED |
| Local assets/database backup | NOT APPLICABLE |
| GitHub push verified | COMPLETED |
| Migration guide | COMPLETED |

## Preserved on GitHub

- All source, tests, CI workflow, plugin manifest, marketplace, skills, hooks and scripts (single branch `main`, no stashes, no other branches existed).
- Full Git history of `main` (rewritten on 2026-10-28 to remove a work email; the pre-rewrite history is intentionally not kept).
- PRD (condensed faithfully from the owner's v1.0 document): `docs/PRD.md`.
- Architecture, status, pending tasks, decision log, P0 checklist, user docs.
- Release `v0.1.0-beta` with `boring-meter-0.1.0.zip` attached.
- Plugin-level Claude configuration (skills, hook) lives in the repo itself.

## Remains local only (safe to lose)

- `~/Library/Application Support/boring-meter`: regenerable cache and test-only state.
- `dist/boring-meter-0.1.0.zip`: rebuildable, and attached to the release.
- `.claude/worktrees/`: empty, created by Claude Code.

## Manual restoration (documented in MIGRATION_GUIDE.md)

- Sign in to GitHub as Satyam2701 with the `workflow` scope.
- Set `git config user.email "34920689+Satyam2701@users.noreply.github.com"` in the new clone (repo-local setting, not stored in Git). GitHub rejects pushes that would publish your private Gmail address.
- Reinstall the plugin in Claude Code and re-add the `attribution` setting to `~/.claude/settings.json`.

## Risks before formatting the old MacBook

- **Claude Code transcripts** in `~/.claude/projects` are personal usage history (Boring Meter's input data, including this project's build sessions). They are not in Git and will be lost unless you copy that folder separately. Not required to continue development.
- **Old private repo `Satyam2701/boring-meter-old`** still exists on GitHub (not on the Mac). It contains the work email in PR #1 commits; delete it when ready. Unrelated to formatting.
- Nothing else of this project exists only on the old machine.

## Missing information

None required to continue development.
