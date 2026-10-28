"""Synthetic, anonymized test fixtures for Boring Meter.

SYNTHETIC TEST DATA ONLY. Every session id starts with "synthetic-" and every project
path starts with "/synthetic/". These files are generated into temporary directories
by the tests and must never be mixed into a real user's reports.

build(root) creates a fake Claude Code config directory:

  root/projects/-synthetic-alpha/synthetic-a1.jsonl
      valid records, a partial (mid-stream) repeat line, cached categories,
      4 unchanged reads of one file, one malformed line
  root/projects/-synthetic-alpha/synthetic-a2.jsonl
      +05:30 timezone offsets, unknown model, missing output_tokens, zero-token
      record (dated alias model), <synthetic> placeholder, truncated final line
  root/projects/-synthetic-beta/synthetic-b1.jsonl
      1-hour cache write, fast mode, inference_geo us, max_tokens stop, rewrites
  root/projects/-synthetic-beta/synthetic-b1.rotated.jsonl
      rotated copy that repeats one response from synthetic-b1 (deduplicated)
  root/projects/-synthetic-beta/workflows/journal.jsonl
      a non-transcript JSONL file (unsupported schema, ignored)
  root/projects/-synthetic-empty/empty.jsonl
      an empty file

EXPECTED holds independently hand-calculated totals and costs.
"""

import json
from decimal import Decimal
from pathlib import Path

LABEL = "synthetic test data"


def _assistant(session, cwd, ts, msg_id, req_id, model, usage, tools=(), stop="end_turn", sidechain=False):
    content = [{"type": "text", "text": "[synthetic]"}]
    for i, (name, tool_input) in enumerate(tools):
        content.append({"type": "tool_use", "id": "toolu_%s_%d" % (msg_id, i), "name": name, "input": tool_input})
    return {
        "type": "assistant", "sessionId": session, "cwd": cwd, "timestamp": ts, "requestId": req_id,
        "uuid": "uuid-%s-%s" % (msg_id, ts), "version": "2.1.299", "isSidechain": sidechain, "_fixture": LABEL,
        "message": {"id": msg_id, "type": "message", "role": "assistant", "model": model, "content": content,
                    "stop_reason": stop, "usage": usage},
    }


def _usage(inp, out, cr, cc, c5=None, c1=None, **extra):
    u = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc,
         "cache_creation": {"ephemeral_5m_input_tokens": cc if c5 is None else c5, "ephemeral_1h_input_tokens": 0 if c1 is None else c1},
         "service_tier": "standard", "speed": "standard", "inference_geo": "global"}
    u.update(extra)
    return u


def _user(session, cwd, ts, text="[synthetic prompt]"):
    return {"type": "user", "sessionId": session, "cwd": cwd, "timestamp": ts, "uuid": "u-%s-%s" % (session, ts),
            "version": "2.1.299", "_fixture": LABEL, "message": {"role": "user", "content": text}}


def _write(path: Path, lines, tail: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line if isinstance(line, str) else json.dumps(line))
            handle.write("\n")
        handle.write(tail)


A, B = "/synthetic/alpha", "/synthetic/beta"
APP = A + "/src/app.py"


def build(root: Path) -> Path:
    projects = root / "projects"
    s = "synthetic-a1"
    a1 = [
        _user(s, A, "2026-10-20T10:00:00Z"),
        # Partial mid-stream line (output 5) followed by the final line (output 100).
        _assistant(s, A, "2026-10-20T10:00:05Z", "msg_a1_1", "req_a1_1", "claude-opus-5-5", _usage(10, 5, 0, 1000)),
        _assistant(s, A, "2026-10-20T10:00:06Z", "msg_a1_1", "req_a1_1", "claude-opus-5-5", _usage(10, 100, 0, 1000)),
        _assistant(s, A, "2026-10-20T10:01:00Z", "msg_a1_2", "req_a1_2", "claude-opus-5-5", _usage(20, 200, 1000, 0),
                   tools=[("Read", {"file_path": APP})]),
        "{this line is not valid json",
    ]
    for i in range(3, 6):
        a1.append(_assistant(s, A, "2026-10-20T10:0%d:00Z" % i, "msg_a1_%d" % i, "req_a1_%d" % i, "claude-opus-5-5",
                             _usage(5, 50, 1100, 0), tools=[("Read", {"file_path": APP})]))
    _write(projects / "-synthetic-alpha" / "synthetic-a1.jsonl", a1)

    s = "synthetic-a2"
    a2 = [
        _user(s, A, "2026-10-21T08:00:00+05:30"),
        _assistant(s, A, "2026-10-21T08:00:10+05:30", "msg_a2_1", "req_a2_1", "claude-sonnet-5-5", _usage(100, 50, 0, 0)),
        _assistant(s, A, "2026-10-21T08:01:00+05:30", "msg_a2_2", "req_a2_2", "claude-imaginary-9", _usage(7, 3, 0, 0)),
        _assistant(s, A, "2026-10-21T08:02:00+05:30", "msg_a2_3", "req_a2_3", "claude-sonnet-5-5",
                   {"input_tokens": 4, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}),
        _assistant(s, A, "2026-10-21T08:03:00+05:30", "msg_a2_4", "req_a2_4", "claude-haiku-4-5-20251001", _usage(0, 0, 0, 0)),
        _assistant(s, A, "2026-10-21T08:04:00+05:30", "msg_a2_5", "req_a2_5", "<synthetic>", _usage(0, 0, 0, 0)),
    ]
    _write(projects / "-synthetic-alpha" / "synthetic-a2.jsonl", a2, tail='{"type": "assistant", "sessionId": "synthetic-a2", "mess')

    s = "synthetic-b1"
    b1_first = _assistant(s, B, "2026-10-22T12:00:00Z", "msg_b1_1", "req_b1_1", "claude-opus-5-5",
                          _usage(1, 10, 0, 2000, c5=0, c1=2000))
    b1 = [
        _user(s, B, "2026-10-22T11:59:00Z"),
        b1_first,
        _assistant(s, B, "2026-10-22T12:05:00Z", "msg_b1_2", "req_b1_2", "claude-opus-5-5",
                   dict(_usage(1000, 1000, 0, 0), speed="fast")),
        _assistant(s, B, "2026-10-22T12:06:00Z", "msg_b1_3", "req_b1_3", "claude-sonnet-5-5",
                   dict(_usage(1000000, 0, 0, 0), inference_geo="us"), stop="max_tokens"),
    ]
    for i in range(4, 7):
        b1.append(_assistant(s, B, "2026-10-22T12:1%d:00Z" % i, "msg_b1_%d" % i, "req_b1_%d" % i, "claude-opus-5-5",
                             _usage(1, 1, 0, 0), tools=[("Write", {"file_path": B + "/out.md", "content": "[synthetic]"})]))
    _write(projects / "-synthetic-beta" / "synthetic-b1.jsonl", b1)
    _write(projects / "-synthetic-beta" / "synthetic-b1.rotated.jsonl", [b1_first])
    _write(projects / "-synthetic-beta" / "workflows" / "journal.jsonl", [{"type": "step", "key": 1, "_fixture": LABEL}])
    _write(projects / "-synthetic-empty" / "empty.jsonl", [])
    return root


M = Decimal(1000000)
EXPECTED = {
    # Requests that are not <synthetic> placeholders, after deduplication.
    "requests": 5 + 4 + 6,
    "duplicates_removed": 1,
    "malformed_lines": 1,
    "truncated_files": 1,
    # Session synthetic-a1, all categories known.
    "a1": {"input_tokens": 45, "output_tokens": 450, "cache_read_tokens": 4300, "cache_creation_tokens": 1000},
    # Opus 5.5: input 4, output 20, 5m write 5, read 0.20 per million.
    "a1_cost": (Decimal(10 * 4 + 100 * 20 + 1000 * 5) + Decimal(20 * 4 + 200 * 20) + Decimal(1000) * Decimal("0.20")
                + 3 * (Decimal(5 * 4 + 50 * 20) + Decimal(1100) * Decimal("0.20"))) / M,
    # 1-hour write on Opus 5.5: 1 * 4 + 10 * 20 + 2000 * 8.
    "b1_1_cost": Decimal(1 * 4 + 10 * 20 + 2000 * 8) / M,
    # Fast mode Opus 5.5: 1000 * 8 + 1000 * 40.
    "b1_2_cost": Decimal(1000 * 8 + 1000 * 40) / M,
    # Sonnet 5.5 with inference_geo us: 1,000,000 * 2 * 1.1.
    "b1_3_cost": Decimal(2) * Decimal("1.1"),
}
