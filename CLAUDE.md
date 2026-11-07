# Boring Meter: notes for Claude Code sessions

Boring Meter is a Claude Code plugin (public beta, v0.1.0) that reads Claude Code's local session transcripts, summarizes token usage, estimates API list-price cost, finds evidence-backed optimization opportunities, and runs before-and-after experiments. Fully local: Python standard library, no network, no paid APIs.

Repository: https://github.com/Satyam2701/boring-meter (public, MIT, owner GitHub account **Satyam2701**).

## Read before significant changes

- [docs/PRD.md](docs/PRD.md): product requirements (source of truth)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): stack, layout, modules, data flow, invariants
- [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md): status, known gaps, pending tasks, release process
- [docs/DECISION_LOG.md](docs/DECISION_LOG.md): why things are the way they are
- [docs/requirements-checklist.md](docs/requirements-checklist.md): P0 audit with evidence
- User docs: [README.md](README.md), [docs/installation.md](docs/installation.md), [docs/data-sources.md](docs/data-sources.md), [docs/rules.md](docs/rules.md), [docs/privacy.md](docs/privacy.md), [docs/troubleshooting.md](docs/troubleshooting.md)

Update the relevant docs (and `CHANGELOG.md`) whenever functionality or architecture changes.

## Commands

```bash
python3 -m unittest discover -s tests -t .      # full suite (147 tests)
./bin/boring-meter usage --week                  # run the CLI from the repo
./bin/boring-meter doctor                        # installation check
claude plugin validate .                         # plugin manifest check
claude --plugin-dir .                            # load this checkout for one session
```

## Rules for this project

- **Never use the em dash character** in any file, output, docs, commit or release text. A test enforces it.
- Python standard library only; must run on Python 3.9. No network calls in the core.
- Never fabricate numbers: unknown stays `None`, never 0. No savings claims without a verified experiment.
- Never modify user files without explicit confirmation (see `optimize.py`).
- Transcript format is undocumented: keep parsing defensive and bump `CACHE_FORMAT` in `adapters.py` when scan output changes.
- Keep Linux/Windows compatibility (CI matrix covers both).
- No co-author attribution lines in commits or PR descriptions (owner preference).
- For releases, bump `version` in `.claude-plugin/plugin.json`; see the release process in `docs/CURRENT_STATUS.md`.
- `claude plugin validate` warns that this `CLAUDE.md` is at the plugin root. It is intended for development sessions and is not loaded as plugin context; the warning is expected.

## GitHub notes

- Push with the Satyam2701 account. If `gh` has several accounts, use `GH_TOKEN=$(gh auth token -h github.com -u Satyam2701) git push`.
- Pushing workflow files needs the `workflow` scope: `gh auth refresh -h github.com -s workflow` (while Satyam2701 is active).

## Immediate next steps

See "Pending tasks" in [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md): delete the old `boring-meter-old` repo, run the beta with testers, verify Windows inside Claude Code.
- Commit email must be the noreply address `34920689+Satyam2701@users.noreply.github.com`: GitHub rejects pushes that publish the private Gmail address (GH007).
