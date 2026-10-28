"""Local storage helpers: atomic writes, a portable lock, and tolerant JSONL reading."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple

from boring_meter.errors import BMError, from_os_error
from boring_meter.paths import display_path, ensure_private_dir

LOCK_STALE_SECONDS = 60.0


@contextmanager
def file_lock(target: Path, timeout: float = 10.0):
    """Exclusive advisory lock using an O_EXCL lock file next to target.

    Works on every platform without extra dependencies. A lock file older than
    LOCK_STALE_SECONDS is treated as abandoned by a crashed writer and removed.
    """
    lock_path = Path(str(target) + ".lock")
    ensure_private_dir(lock_path.parent)
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, ("%d %f" % (os.getpid(), time.time())).encode())
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise BMError(
                    "LOCK_TIMEOUT",
                    "Another Boring Meter process is writing %s." % display_path(target),
                    "Wait a moment and run the command again.",
                )
            time.sleep(0.05)
        except OSError as exc:
            raise from_os_error(exc, "lock", display_path(target))
    try:
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except OSError:
            pass


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    """Write text so readers see either the old file or the complete new one."""
    ensure_private_dir(path.parent)
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_name, mode)
        except OSError:
            pass
        os.replace(tmp_name, str(path))
        tmp_name = None
    except OSError as exc:
        raise from_os_error(exc, "write", display_path(path))
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def read_json(path: Path):
    """Read a JSON file. Returns None when missing; raises BMError when corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise BMError(
            "CORRUPTED_RECORD",
            "%s is not valid JSON (line %d)." % (display_path(path), exc.lineno),
        )
    except OSError as exc:
        raise from_os_error(exc, "read", display_path(path))


def append_jsonl(path: Path, obj) -> None:
    """Append one JSON object as a single line, under the file lock."""
    line = json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n"
    with file_lock(path):
        ensure_private_dir(path.parent)
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError as exc:
            raise from_os_error(exc, "append to", display_path(path))


def iter_jsonl(path: Path) -> Iterator[Tuple[int, Optional[dict], Optional[str]]]:
    """Yield (line_number, object, error) for each non-blank line.

    error is None for valid lines, "truncated" for an unterminated final line that
    does not parse (a partial write), and "malformed" for other unparseable lines.
    A malformed line never stops the iteration.
    """
    with open(path, "rb") as handle:
        previous = None
        lineno = 0
        for raw in handle:
            if previous is not None:
                yield _parse_line(previous, lineno, final=False)
            lineno += 1
            previous = raw
        if previous is not None:
            yield _parse_line(previous, lineno, final=True)


def _parse_line(raw: bytes, lineno: int, final: bool):
    stripped = raw.strip()
    if not stripped:
        return lineno, None, "blank"
    try:
        obj = json.loads(stripped.decode("utf-8", errors="replace"))
    except ValueError:
        if final and not raw.endswith(b"\n"):
            return lineno, None, "truncated"
        return lineno, None, "malformed"
    if not isinstance(obj, dict):
        return lineno, None, "malformed"
    return lineno, obj, None
