"""Local, read-only analysis of Claude Code instruction files.

Locations follow the Claude Code memory documentation:
  loaded at launch: ~/.claude/CLAUDE.md, ~/.claude/rules/*.md, CLAUDE.md and
  CLAUDE.local.md in the project directory and every directory above it,
  ./.claude/CLAUDE.md, ./.claude/rules/*.md without `paths` frontmatter, AGENTS.md
  when no CLAUDE.md exists, @path imports (up to 4 hops), and the first 200 lines
  or 25KB of auto memory (MEMORY.md).
  loaded on demand: CLAUDE.md files in subdirectories, and rules with `paths`.

Sizes are measured exactly (characters, lines). Token figures are estimates
(characters / 4) and are always labeled as estimates, never as observed usage.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from boring_meter.paths import claude_config_dir, display_path, is_within

MAX_FILE_BYTES = 1024 * 1024
IMPORT_MAX_HOPS = 4
NESTED_SCAN_MAX_DIRS = 4000
NESTED_SCAN_SECONDS = 1.5
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", ".tox", ".cache"}
MIN_DUP_CHARS = 25
LARGE_CODE_BLOCK_LINES = 25
AUTO_MEMORY_LINES = 200
AUTO_MEMORY_BYTES = 25 * 1024

IMPORT_RE = re.compile(r"(?:^|\s)@((?:~|\.{1,2})?/?[\w./~-]+\.\w+)")


@dataclass
class InstructionFile:
    path: str
    scope: str  # user, user-rule, project, local, project-rule, ancestor, import, agents, auto-memory, nested, path-rule
    loaded: str  # "launch" or "on demand"
    chars: int
    lines: int
    text: str = field(repr=False, default="")
    note: str = ""

    @property
    def est_tokens(self) -> int:
        return round(self.chars / 4)

    def to_dict(self, project_root: Optional[Path] = None) -> dict:
        return {
            "path": display_path(self.path),
            "scope": self.scope,
            "loaded": self.loaded,
            "chars": self.chars,
            "lines": self.lines,
            "estimated_tokens": self.est_tokens,
            "estimated_tokens_method": "characters / 4 (estimate, not measured)",
            "note": self.note,
        }


def _read(path: Path) -> Optional[str]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _has_paths_frontmatter(text: str) -> bool:
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    return bool(re.search(r"^paths\s*:", text[3:end], re.MULTILINE))


def _strip_code(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _imports(text: str, base: Path) -> List[Path]:
    found = []
    for match in IMPORT_RE.finditer(_strip_code(text)):
        raw = match.group(1)
        if raw.startswith("~"):
            target = Path(raw).expanduser()
        elif raw.startswith("/"):
            target = Path(raw)
        else:
            target = base / raw
        found.append(Path(os.path.normpath(str(target))))
    return found


def _project_memory_dir(project_root: Path) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(project_root))
    return claude_config_dir() / "projects" / slug / "memory"


def _make(path: Path, scope: str, loaded: str, text: str, note: str = "") -> InstructionFile:
    return InstructionFile(str(path), scope, loaded, len(text), text.count("\n") + (1 if text and not text.endswith("\n") else 0), text, note)


def discover(project_root: Path, include_user: bool = True) -> dict:
    """Find instruction files for a project. Reads files only from documented locations."""
    project_root = Path(os.path.realpath(project_root))
    files: List[InstructionFile] = []
    skipped: List[str] = []
    seen: set = set()

    def add(path: Path, scope: str, loaded: str, note: str = "") -> Optional[InstructionFile]:
        real = os.path.realpath(path)
        if real in seen or not path.is_file():
            return None
        text = _read(path)
        if text is None:
            skipped.append("%s (unreadable or larger than 1 MB)" % display_path(path))
            return None
        seen.add(real)
        item = _make(path, scope, loaded, text, note)
        files.append(item)
        return item

    home_claude = claude_config_dir()
    if include_user:
        add(home_claude / "CLAUDE.md", "user", "launch")
        rules = home_claude / "rules"
        if rules.is_dir():
            for rule in sorted(rules.rglob("*.md")):
                text = _read(rule) or ""
                add(rule, "user-rule", "on demand" if _has_paths_frontmatter(text) else "launch")

    # Project directory and every ancestor (launch).
    chain = [project_root] + list(project_root.parents)
    has_claude_md = False
    for directory in chain:
        scope = "project" if directory == project_root else "ancestor"
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            item = add(directory / name, "local" if name == "CLAUDE.local.md" and scope == "project" else scope, "launch")
            if item:
                has_claude_md = True
        if directory == project_root:
            if add(directory / ".claude" / "CLAUDE.md", "project", "launch"):
                has_claude_md = True
    if not has_claude_md:
        for directory in chain:
            add(directory / "AGENTS.md", "agents", "launch", "Loaded because no CLAUDE.md was found.")

    rules_dir = project_root / ".claude" / "rules"
    if rules_dir.is_dir():
        for rule in sorted(rules_dir.rglob("*.md")):
            text = _read(rule) or ""
            if _has_paths_frontmatter(text):
                add(rule, "path-rule", "on demand")
            else:
                add(rule, "project-rule", "launch")

    # Auto memory: only the first 200 lines or 25KB load.
    memory = _project_memory_dir(project_root) / "MEMORY.md"
    if memory.is_file():
        text = _read(memory)
        if text is not None:
            loaded_text = "\n".join(text.splitlines()[:AUTO_MEMORY_LINES])[:AUTO_MEMORY_BYTES]
            seen.add(os.path.realpath(memory))
            files.append(_make(memory, "auto-memory", "launch", loaded_text, "Only the first 200 lines or 25KB load."))

    # @imports from launch-loaded files, up to 4 hops, within the project or ~/.claude or home.
    frontier = [(f, 0) for f in files if f.loaded == "launch"]
    while frontier:
        item, depth = frontier.pop(0)
        if depth >= IMPORT_MAX_HOPS:
            continue
        for target in _imports(item.text, Path(item.path).parent):
            if not (is_within(target, project_root) or is_within(target, Path.home())):
                skipped.append("%s (import outside the project and home directory, not read)" % display_path(target))
                continue
            imported = add(target, "import", "launch", "Imported by %s" % display_path(item.path))
            if imported:
                frontier.append((imported, depth + 1))

    # Nested CLAUDE.md files (on demand), bounded scan.
    nested_complete = True
    started = time.monotonic()
    visited = 0
    for dirpath, dirnames, filenames in os.walk(str(project_root), followlinks=False):
        visited += 1
        if visited > NESTED_SCAN_MAX_DIRS or time.monotonic() - started > NESTED_SCAN_SECONDS:
            nested_complete = False
            break
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        if Path(dirpath) == project_root:
            continue
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            if name in filenames:
                add(Path(dirpath) / name, "nested", "on demand")

    return {
        "project_root": str(project_root),
        "files": files,
        "skipped": skipped,
        "nested_scan_complete": nested_complete,
    }


def _normalize(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^([-*+]|\d+[.)])\s+", "", text)
    return re.sub(r"\s+", " ", text).lower()


def _content_lines(text: str):
    """Yield (line_number, raw_line, normalized) for prose lines outside code fences."""
    in_code = False
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code or not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped == "---":
            continue
        norm = _normalize(raw)
        if len(norm) >= MIN_DUP_CHARS:
            yield number, raw, norm


def duplicate_lines(files: List[InstructionFile]) -> dict:
    """Exact duplicate instruction lines (after whitespace and bullet normalization)."""
    occurrences: Dict[str, list] = {}
    for item in files:
        for number, raw, norm in _content_lines(item.text):
            occurrences.setdefault(norm, []).append((item.path, number, raw.strip()))
    within, across = [], []
    for norm, places in occurrences.items():
        if len(places) < 2:
            continue
        paths = {p for p, _n, _r in places}
        entry = {"text": places[0][2][:160], "occurrences": [{"path": p, "line": n} for p, n, _r in places]}
        (within if len(paths) == 1 else across).append(entry)
    return {"within_file": within, "across_files": across}


def code_blocks(item: InstructionFile) -> List[dict]:
    blocks, start, in_code = [], None, False
    for number, raw in enumerate(item.text.splitlines(), 1):
        if raw.strip().startswith("```"):
            if not in_code:
                start, in_code = number, True
            else:
                length = number - start - 1
                if length >= LARGE_CODE_BLOCK_LINES:
                    blocks.append({"path": item.path, "start_line": start, "lines": length})
                in_code = False
    return blocks


def sections(item: InstructionFile) -> List[dict]:
    """Markdown sections by heading with their sizes, largest first."""
    result, current, start, size = [], "(top of file)", 1, 0
    for number, raw in enumerate(item.text.splitlines(), 1):
        if re.match(r"^#{1,6}\s", raw):
            if size:
                result.append({"heading": current, "start_line": start, "chars": size})
            current, start, size = raw.strip("# ").strip()[:80], number, 0
        else:
            size += len(raw) + 1
    if size:
        result.append({"heading": current, "start_line": start, "chars": size})
    return sorted(result, key=lambda s: -s["chars"])


def analyze(project_root: Path, include_user: bool = True) -> dict:
    found = discover(project_root, include_user=include_user)
    files: List[InstructionFile] = found["files"]
    launch = [f for f in files if f.loaded == "launch"]
    dups = duplicate_lines(launch)
    blocks = [b for f in launch for b in code_blocks(f)]
    return {
        "project_root": found["project_root"],
        "files": files,
        "launch_files": launch,
        "launch_chars": sum(f.chars for f in launch),
        "launch_lines": sum(f.lines for f in launch),
        "launch_estimated_tokens": round(sum(f.chars for f in launch) / 4),
        "duplicates": dups,
        "large_code_blocks": blocks,
        "largest_sections": {f.path: sections(f)[:3] for f in launch},
        "skipped": found["skipped"],
        "nested_scan_complete": found["nested_scan_complete"],
    }
