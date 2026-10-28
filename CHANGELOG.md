# Changelog

## Unreleased

- Licensed under MIT (`LICENSE`, `license` in plugin.json).
- GitHub Actions test matrix for Ubuntu 24.04, macOS and Windows with Python 3.9 and 3.12; all six jobs pass.
- Windows fixes found by CI: a lock file being released no longer makes another writer fail (it waits instead), excluded projects match with Windows path separators, and `UTC` works without a timezone database (other zone names explain how to install `tzdata`).
- Windows storage fixes: JSONL appends and lock files use binary-mode descriptors so lines end in LF, and atomic writes retry briefly when `os.replace` is blocked by a reader.
- Tests for disk-full handling during atomic writes (`STORAGE_FULL`), each platform's data directory choice, and Windows-friendly integration tests (`python -m boring_meter` instead of the sh launcher).

## 0.1.0 (2026-10-28)

First MVP release.

- Claude Code plugin with six commands (`usage`, `analyze`, `optimize`, `report`, `experiment`, `settings`) and two guidance skills.
- Transcript adapter with deduplication (including partial mid-stream lines), malformed and truncated line handling, symlink and size limits, and a size and mtime parse cache.
- Usage aggregation by period, session, model, day, and project with explicit coverage.
- API list-price cost estimation with a versioned pricing table (`anthropic-api-list-2026-10-27`), fast mode, US inference region multiplier, and Haiku 5.5 long-context prices.
- Five deterministic rules with transparent priority scoring.
- Instruction file analyzer and confirmation-gated optimizer with hash check, backup, and verification.
- Before-and-after experiments with comparability checks and four-way classification.
- Opt-in, metadata-only `InstructionsLoaded` hook.
- Local settings, retention, export, and deletion of Boring Meter's own data.
- 135 automated tests.
