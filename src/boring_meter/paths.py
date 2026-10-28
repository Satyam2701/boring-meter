"""Filesystem locations and path safety checks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from boring_meter.errors import BMError


def data_dir() -> Path:
    """Boring Meter's own data directory, chosen by platform convention.

    BORING_METER_DATA_DIR overrides it. CLAUDE_PLUGIN_DATA is deliberately not used:
    Claude Code exports it to hooks but not to commands run through the Bash tool,
    so relying on it would split data across two directories.
    """
    override = os.environ.get("BORING_METER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "boring-meter"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / "boring-meter"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / "boring-meter"


def claude_config_dir() -> Path:
    """Claude Code's configuration directory (CLAUDE_CONFIG_DIR or ~/.claude)."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude"


def display_path(path) -> str:
    """Shorten a path for display by replacing the home directory with ~."""
    text = str(path)
    home = str(Path.home())
    if home and (text == home or text.startswith(home + os.sep)):
        return "~" + text[len(home):]
    return text


def is_within(child: Path, parent: Path) -> bool:
    """True when child resolves to parent or a location inside it."""
    try:
        child_r = Path(os.path.realpath(child))
        parent_r = Path(os.path.realpath(parent))
    except (OSError, ValueError):
        return False
    return child_r == parent_r or parent_r in child_r.parents


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def validate_output_path(raw: str, force: bool = False) -> Path:
    """Validate a user-selected export destination.

    Refuses empty paths, directories, missing parent directories, Claude Code's own
    data directory, and existing files unless force is set.
    """
    if not raw or not raw.strip():
        raise BMError("INVALID_OUTPUT_PATH", "The output path is empty.")
    if "\x00" in raw:
        raise BMError("INVALID_OUTPUT_PATH", "The output path contains a NUL character.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.normpath(str(path)))
    if path.exists() and path.is_dir():
        raise BMError(
            "INVALID_OUTPUT_PATH",
            "%s is a directory." % display_path(path),
            "Pass a file name, for example %s" % display_path(path / "boring-meter-report.md"),
        )
    if not path.parent.is_dir():
        raise BMError(
            "INVALID_OUTPUT_PATH",
            "The folder %s does not exist." % display_path(path.parent),
            "Create the folder first or choose an existing one.",
        )
    if is_within(path, claude_config_dir()):
        raise BMError(
            "INVALID_OUTPUT_PATH",
            "Refusing to write inside Claude Code's own directory (%s)." % display_path(claude_config_dir()),
            "Choose a destination outside it.",
        )
    if path.exists() and not force:
        raise BMError(
            "OUTPUT_EXISTS",
            "%s already exists and was not overwritten." % display_path(path),
            "Choose another file name, or confirm the overwrite by adding --force.",
        )
    return path
