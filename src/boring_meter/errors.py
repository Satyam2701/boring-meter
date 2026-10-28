"""Structured errors with concise, actionable user-facing messages."""

from __future__ import annotations

import errno


class BMError(Exception):
    """An expected failure that should be shown to the user without a traceback."""

    exit_code = 2

    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}

    def render(self) -> str:
        text = "Boring Meter error [%s]: %s" % (self.code, self.message)
        if self.hint:
            text += "\nHint: %s" % self.hint
        return text


def from_os_error(exc: OSError, action: str, shown_path: str) -> BMError:
    """Translate an OSError into a BMError without leaking more than the shown path."""
    if exc.errno in (errno.EACCES, errno.EPERM):
        return BMError(
            "PERMISSION_DENIED",
            "Permission denied while trying to %s %s." % (action, shown_path),
            "Check the file permissions, or choose another location.",
        )
    if exc.errno == errno.ENOSPC:
        return BMError(
            "STORAGE_FULL",
            "The disk is full, so Boring Meter could not %s %s." % (action, shown_path),
            "Free some disk space, or lower retention with: boring-meter settings set retention.event_days 30",
        )
    if exc.errno == errno.EROFS:
        return BMError(
            "STORAGE_UNAVAILABLE",
            "The file system is read-only, so Boring Meter could not %s %s." % (action, shown_path),
            "Set BORING_METER_DATA_DIR to a writable directory.",
        )
    if exc.errno == errno.ENOENT:
        return BMError("NOT_FOUND", "Could not %s %s: it does not exist." % (action, shown_path))
    return BMError(
        "STORAGE_UNAVAILABLE",
        "Could not %s %s (%s)." % (action, shown_path, exc.strerror or exc.__class__.__name__),
    )
