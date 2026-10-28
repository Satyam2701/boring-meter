"""Reviewable proposals for instruction files. Nothing is applied without confirmation.

Only one kind of change is ever applied automatically, and only after explicit
confirmation: removing later word-for-word repeats of an instruction line within the
same file (the first occurrence is kept). Everything else (moving sections, resolving
repeats across files) is advisory and printed as copyable instructions.

Applying a proposal:
  1. checks the file still matches the hash recorded when the proposal was made,
  2. saves a backup copy in the data directory,
  3. writes the new content atomically,
  4. re-reads the file and verifies its hash,
  5. reports exactly what changed.
"""

from __future__ import annotations

import difflib
import hashlib
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from boring_meter.errors import BMError, from_os_error
from boring_meter.instructions import _content_lines
from boring_meter.paths import display_path, ensure_private_dir, validate_output_path
from boring_meter.store import atomic_write_json, atomic_write_text, read_json


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def proposals_dir(base: Path) -> Path:
    return base / "proposals"


def dedupe_text(text: str) -> tuple:
    """Remove later exact repeats of prose lines. Returns (new_text, removed_line_numbers)."""
    seen = set()
    remove = set()
    for number, _raw, norm in _content_lines(text):
        if norm in seen:
            remove.add(number)
        else:
            seen.add(norm)
    if not remove:
        return text, []
    lines = text.splitlines(keepends=True)
    kept = [line for i, line in enumerate(lines, 1) if i not in remove]
    return "".join(kept), sorted(remove)


def build(analysis: dict, base: Path) -> dict:
    """Create proposals for the analyzed project and store them for review."""
    created: List[dict] = []
    advisory: List[str] = []
    for item in analysis["launch_files"]:
        if item.scope in ("auto-memory",):
            continue
        path = Path(item.path)
        try:
            current = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise from_os_error(exc, "read", display_path(path))
        new_text, removed = dedupe_text(current)
        if not removed:
            continue
        diff = "".join(difflib.unified_diff(
            current.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=display_path(path) + " (current)", tofile=display_path(path) + " (proposed)",
        ))
        proposal_id = "p-" + secrets.token_hex(4)
        record = {
            "proposal_id": proposal_id,
            "kind": "remove-repeated-lines",
            "target": str(path),
            "created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "original_sha256": _sha(current),
            "proposed_sha256": _sha(new_text),
            "removed_lines": removed,
            "expected_benefit": "Removes %d repeated line(s), about %d characters, from text loaded every session."
                                % (len(removed), len(current) - len(new_text)),
            "risk": "Low: the first copy of each line is kept. Check that no repeat was intentional emphasis.",
            "applied": None,
        }
        folder = ensure_private_dir(proposals_dir(base) / proposal_id)
        atomic_write_json(folder / "proposal.json", record)
        atomic_write_text(folder / "proposed.txt", new_text)
        atomic_write_text(folder / "change.diff", diff)
        record["diff"] = diff
        created.append(record)
    for dup in analysis["duplicates"]["across_files"][:5]:
        places = ", ".join("%s:%d" % (display_path(o["path"]), o["line"]) for o in dup["occurrences"][:4])
        advisory.append('Decide which file should own "%s" (found at %s) and delete the other copies.' % (dup["text"][:80], places))
    for block in analysis["large_code_blocks"][:5]:
        advisory.append(
            "Consider moving the %d-line code block at %s line %d into a separate file and referencing it as plain text "
            "(not an @import, which would still load it every session), or into a path-scoped rule."
            % (block["lines"], display_path(block["path"]), block["start_line"])
        )
    for path, secs in analysis["largest_sections"].items():
        if secs and secs[0]["chars"] >= 4000:
            advisory.append(
                'The section "%s" in %s is %d characters. If it only matters for some tasks, move it to '
                ".claude/rules/<topic>.md with a paths: frontmatter so it loads only for matching files."
                % (secs[0]["heading"], display_path(path), secs[0]["chars"])
            )
    return {"proposals": created, "advisory": advisory}


def load(base: Path, proposal_id: str) -> dict:
    if not proposal_id.startswith("p-") or not proposal_id[2:].isalnum():
        raise BMError("INVALID_ARGUMENT", "'%s' is not a proposal id." % proposal_id)
    folder = proposals_dir(base) / proposal_id
    record = read_json(folder / "proposal.json")
    if record is None:
        raise BMError("PROPOSAL_NOT_FOUND", "No proposal with id %s." % proposal_id, "Create one with: boring-meter optimize")
    record["folder"] = str(folder)
    return record


def show(base: Path, proposal_id: str) -> dict:
    record = load(base, proposal_id)
    record["diff"] = Path(record["folder"], "change.diff").read_text(encoding="utf-8")
    return record


def save_copy(base: Path, proposal_id: str, output: str, force: bool = False) -> Path:
    """Write the proposed content to a new file chosen by the user. Never the target itself."""
    record = load(base, proposal_id)
    dest = validate_output_path(output, force=force)
    if dest.resolve() == Path(record["target"]).resolve():
        raise BMError("INVALID_OUTPUT_PATH", "Use 'optimize apply' to change the original file, not 'optimize save'.")
    text = Path(record["folder"], "proposed.txt").read_text(encoding="utf-8")
    atomic_write_text(dest, text, mode=0o644)
    return dest


def apply(base: Path, proposal_id: str, confirmed: bool) -> dict:
    record = load(base, proposal_id)
    target = Path(record["target"])
    if not confirmed:
        raise BMError(
            "CONFIRMATION_REQUIRED",
            "Not applied. Applying a proposal changes %s and needs explicit confirmation." % display_path(target),
            "Review it with 'boring-meter optimize show %s', then rerun apply with --confirm." % proposal_id,
        )
    if record.get("applied"):
        raise BMError("PROPOSAL_STALE", "Proposal %s was already applied on %s." % (proposal_id, record["applied"]))
    try:
        current = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise from_os_error(exc, "read", display_path(target))
    if _sha(current) != record["original_sha256"]:
        raise BMError(
            "PROPOSAL_STALE",
            "%s changed after the proposal was made, so it was not modified." % display_path(target),
            "Run /boring-meter:optimize again to create a fresh proposal.",
        )
    proposed = Path(record["folder"], "proposed.txt").read_text(encoding="utf-8")
    backup_dir = ensure_private_dir(base / "backups")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / ("%s-%s-%s" % (stamp, proposal_id, target.name))
    try:
        shutil.copy2(str(target), str(backup))
    except OSError as exc:
        raise from_os_error(exc, "back up", display_path(target))
    mode = target.stat().st_mode & 0o777
    atomic_write_text(target, proposed, mode=mode)
    written = target.read_text(encoding="utf-8")
    if _sha(written) != record["proposed_sha256"]:
        shutil.copy2(str(backup), str(target))
        raise BMError("APPLY_FAILED", "Verification failed after writing %s; the backup was restored." % display_path(target))
    record["applied"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    record["backup"] = str(backup)
    folder = Path(record.pop("folder"))
    atomic_write_json(folder / "proposal.json", record)
    return {
        "proposal_id": proposal_id,
        "target": display_path(target),
        "removed_lines": record["removed_lines"],
        "backup": display_path(backup),
        "verified": True,
    }
