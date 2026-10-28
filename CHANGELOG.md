# Changelog

## Unreleased

- GitHub Actions test matrix for Ubuntu, macOS and Windows with Python 3.9 and 3.12 (configured, not yet run).
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
