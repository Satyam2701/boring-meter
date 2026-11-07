# Installation

## Requirements

- Claude Code with plugin support. Verified with 2.1.311.
- Python 3.9 or newer available as `python3` (or `python` pointing to Python 3). Verified with 3.9.6 and 3.14.7.
- No other dependencies. Nothing is downloaded at install time or at runtime.

## Install from GitHub

This repository is both the plugin and a one-plugin marketplace (`.claude-plugin/marketplace.json`, name `boring-meter`).

```bash
claude plugin marketplace add Satyam2701/boring-meter
```

```bash
claude plugin install boring-meter@boring-meter
```

Start a new session, or run `/reload-plugins` in an open one. Type `/boring-meter:` to see the six commands.

The repository must be public, or your GitHub account must have access to it (with git or `gh` signed in).

## Install from a local clone

```bash
git clone https://github.com/Satyam2701/boring-meter.git
```

```bash
claude plugin marketplace add ./boring-meter
```

```bash
claude plugin install boring-meter@boring-meter
```

For a local-path marketplace, Claude Code reads the plugin in place from that folder, so edits there take effect after `/reload-plugins`.

## Load for one session only

```bash
claude --plugin-dir ./boring-meter
```

## Updates

```bash
claude plugin marketplace update boring-meter
```

Claude Code installs a new release only when the `version` in `.claude-plugin/plugin.json` changes, so bump it for every release.

## Verify the installation

1. `claude plugin list` shows `boring-meter@boring-meter` as enabled.
2. `claude plugin details boring-meter` lists 8 skills and 1 hook (`InstructionsLoaded`).
3. In Claude Code, run `/boring-meter:usage --today`. You should see a usage overview or a clear empty state.
4. Run `boring-meter doctor` (inside Claude Code through the Bash tool, or with the full path `./boring-meter/bin/boring-meter doctor` from a clone).

These steps were run on 2026-10-28 against an empty, isolated `CLAUDE_CONFIG_DIR`: the marketplace was added, the plugin was installed, listed as enabled, inspected, its CLI ran from the installed copy, and it was uninstalled cleanly.

## How the pieces connect

- `skills/<name>/SKILL.md` define `/boring-meter:<name>`. The six command skills set `disable-model-invocation: true`, so they run only when you type them. They tell Claude to run `boring-meter <command>` with the Bash tool, pre-approved through `allowed-tools`.
- `bin/boring-meter` (sh, for macOS, Linux and Git Bash on Windows) and `bin/boring-meter.cmd` (Windows PowerShell and CMD) are the launchers. Claude Code adds a plugin's `bin/` folder to the Bash tool's PATH while the plugin is enabled. Each launcher tries `python3`, `python` and `py -3`, runs each to confirm Python 3.9 or newer (skipping Microsoft Store placeholders), then runs `scripts/run_boring_meter.py`.
- On Windows, Claude Code uses Git Bash for its Bash tool when Git for Windows is installed, and PowerShell otherwise. Both are supported.
- `hooks/hooks.json` registers an `InstructionsLoaded` hook that runs `bin/boring-meter --run-hook instructions-loaded`. It does nothing unless you opt in with `boring-meter settings set collection.instruction_events true`, and it exits quietly when Python is missing.

## Uninstall

```bash
claude plugin uninstall boring-meter@boring-meter
```

```bash
claude plugin marketplace remove boring-meter
```

Boring Meter keeps its own data outside Claude Code's plugin folder (see [privacy.md](privacy.md)), so uninstalling does not delete it. Run `boring-meter settings delete-data --yes` first, or delete the folder printed by `boring-meter settings path`.
