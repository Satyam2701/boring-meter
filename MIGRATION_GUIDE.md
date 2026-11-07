# Migration guide: new MacBook

Everything needed is on GitHub. Nothing has to be copied from the old machine.

## 1. Install software

```bash
xcode-select --install
```

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

```bash
brew install git gh python@3.12
```

Install Claude Code (see https://code.claude.com/docs) and sign in. Python 3.9 or newer is required; the macOS system `python3` also works.

## 2. Connect GitHub (account Satyam2701)

```bash
gh auth login -h github.com -s workflow
```

Choose GitHub.com, HTTPS, and sign in as **Satyam2701**. The `workflow` scope is needed to push changes to `.github/workflows/`.

```bash
gh auth setup-git
```

## 3. Clone and set your commit identity

```bash
git clone https://github.com/Satyam2701/boring-meter.git ~/Desktop/boring-meter
```

```bash
cd ~/Desktop/boring-meter && git config user.name "Satyam Tiwari" && git config user.email "34920689+Satyam2701@users.noreply.github.com"
```

## 4. Verify the project

```bash
./scripts/setup-new-machine.sh
```

This checks the tools, runs the full test suite, and runs `boring-meter doctor`. There are no dependencies to install and no environment variables or secrets to configure.

## 5. Restore Claude Code configuration (machine-level)

Install the plugin for daily use:

```bash
claude plugin marketplace add Satyam2701/boring-meter
```

```bash
claude plugin install boring-meter@boring-meter
```

Turn off Claude co-author attribution in commits and PRs (was set on the old machine). Add this to `~/.claude/settings.json`, merging with anything already there:

```json
{ "attribution": { "commit": "", "pr": "" } }
```

## 6. Continue working

```bash
cd ~/Desktop/boring-meter && claude
```

Claude reads `CLAUDE.md`, which points to the PRD, architecture, status and decision log.

## What does not move (by design)

- Boring Meter's local data (`~/Library/Application Support/boring-meter`): parse cache and test-only state, regenerated automatically.
- Claude Code transcripts (`~/.claude/projects`): Boring Meter's input data. History from the old Mac will not be on the new one unless you copy that folder yourself; it is personal usage data and does not belong in Git.
- `dist/boring-meter-0.1.0.zip`: rebuild with `git archive` (see docs/CURRENT_STATUS.md); also attached to the GitHub release.
