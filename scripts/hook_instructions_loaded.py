"""InstructionsLoaded hook for Boring Meter.

Reads the hook payload from stdin and, only when the user has enabled
collection.instruction_events, appends one metadata record: session id, file path,
memory type, load reason, file size, and line count. File contents are never stored.

Always exits 0 so a problem here can never interrupt Claude Code.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


def main() -> int:
    try:
        from boring_meter import config
        from boring_meter.adapters import events_path
        from boring_meter.paths import data_dir
        from boring_meter.store import append_jsonl

        base = data_dir()
        cfg = config.load(base)
        if not cfg.get("collection.instruction_events", False):
            return 0
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        file_path = payload.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            return 0  # missing required field: record nothing rather than a partial guess
        size = lines = None
        try:
            st = os.stat(file_path)
            size = st.st_size
            if size <= 1024 * 1024:
                with open(file_path, "rb") as handle:
                    lines = handle.read().count(b"\n")
        except OSError:
            pass

        def text(key):
            value = payload.get(key)
            return value if isinstance(value, str) else None

        append_jsonl(
            events_path(base),
            {
                "schema_version": 1,
                "source": "boring-meter-hook-events",
                "event": "InstructionsLoaded",
                "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "session_id": text("session_id"),
                "file_path": file_path,
                "memory_type": text("memory_type"),
                "load_reason": text("load_reason"),
                "size_bytes": size,
                "line_count": lines,
            },
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
