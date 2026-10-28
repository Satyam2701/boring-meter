"""Usage source adapters, source discovery, normalization, and deduplication.

Adapter: claude-code-transcripts (version 1)
  Reads Claude Code's local session transcripts (JSONL) read-only. Each assistant
  line carries the Anthropic API `usage` object for the request that produced it.
  Claude Code writes one line per content block, so one API response can appear on
  several lines with the same message.id and requestId. Those repeats are merged into
  one record, keeping the line with the highest output_tokens because earlier lines can
  hold a partial, mid-stream output count. Responses copied into another file (for
  example a forked session) are deduplicated across files by the same key.

  Token semantics (Anthropic Messages API): input_tokens, cache_creation_input_tokens,
  cache_read_input_tokens and output_tokens are disjoint categories. input_tokens does
  not include cache reads or cache writes, so the four values may be added to get the
  total tokens processed for a request. Thinking tokens are a subset of output tokens
  and are never added again.

Adapter: boring-meter-hook-events (version 1)
  Events written by this plugin's own InstructionsLoaded hook when the user opts in.
  Metadata only (file path, size, load reason). No token values.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from boring_meter import SCHEMA_VERSION
from boring_meter.errors import BMError
from boring_meter.paths import claude_config_dir, display_path, is_within
from boring_meter.store import atomic_write_text, file_lock, iter_jsonl
from boring_meter.timeutil import parse_ts

TRANSCRIPT_SOURCE = "claude-code-transcripts"
TRANSCRIPT_ADAPTER_VERSION = 1
HOOK_SOURCE = "boring-meter-hook-events"
HOOK_ADAPTER_VERSION = 1

FILE_MODIFYING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

TRANSCRIPT_SOURCE_INFO = {
    "source_id": TRANSCRIPT_SOURCE,
    "source_type": "local JSONL files written by Claude Code",
    "adapter_version": TRANSCRIPT_ADAPTER_VERSION,
    "discovery": "CLAUDE_CONFIG_DIR (or ~/.claude) /projects/**/*.jsonl, plus sources.extra_transcript_dirs",
    "supported_fields": [
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens (with 5m and 1h split when present)",
        "model",
        "session_id",
        "project directory (cwd)",
        "timestamp",
        "speed, service_tier, inference_geo",
        "tool-call names and file paths (for optimization rules; no file contents)",
    ],
    "schema": "Undocumented Claude Code transcript format, observed with Claude Code 2.1.229 to 2.1.311",
    "timestamp_semantics": "UTC time Claude Code wrote the line, close to when the response finished",
    "values": "observed (copied from the API usage object, never inferred)",
    "limitations": [
        "The transcript format is internal to Claude Code and may change without notice.",
        "Claude Code deletes transcripts older than cleanupPeriodDays (default 30), so older history may be missing.",
        "Transcripts do not say whether a request was billed through a subscription or the API.",
        "Requests that failed before a response was written are not recorded.",
    ],
}

HOOK_SOURCE_INFO = {
    "source_id": HOOK_SOURCE,
    "source_type": "local JSONL written by this plugin's InstructionsLoaded hook (opt-in)",
    "adapter_version": HOOK_ADAPTER_VERSION,
    "discovery": "<Boring Meter data directory>/events/instructions.jsonl",
    "supported_fields": ["session_id", "file_path", "memory_type", "load_reason", "size_bytes", "line_count"],
    "timestamp_semantics": "Local clock time when the hook ran, stored with its UTC offset",
    "values": "observed metadata; contains no token counts",
    "limitations": ["Only records loads that happen after collection is enabled."],
}


def _int_or_none(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _rel(path: str, cwd: Optional[str]) -> str:
    if cwd and isinstance(path, str) and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1 :]
    return path


@dataclass
class FileResult:
    path: str
    size: int
    mtime_ns: int
    records: List[dict] = field(default_factory=list)
    sessions: Dict[str, dict] = field(default_factory=dict)
    line_count: int = 0
    malformed_lines: List[int] = field(default_factory=list)
    truncated: bool = False
    recognized_lines: int = 0
    status: str = "ok"
    note: str = ""

    def to_cache(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "records": self.records,
            "sessions": self.sessions,
            "line_count": self.line_count,
            "malformed_lines": self.malformed_lines,
            "truncated": self.truncated,
            "recognized_lines": self.recognized_lines,
            "status": self.status,
            "note": self.note,
        }

    @classmethod
    def from_cache(cls, data: dict) -> "FileResult":
        return cls(**data)


def _new_session(session_id: str, sidechain: bool) -> dict:
    return {
        "session_id": session_id,
        "is_sidechain": sidechain,
        "first_ts": None,
        "last_ts": None,
        "cwds": [],
        "user_prompts": 0,
        "requests": 0,
        "compactions": [],
        "tool_counts": {},
        "reads": {},
        "full_writes": {},
        "max_tokens_stops": 0,
        "idle_gaps": [],
        "models": [],
        "versions": [],
    }


def scan_transcript(path: Path, idle_gap_hours: int = 4) -> FileResult:
    """Parse one transcript file into normalized usage records and session signals.

    Never stores message text, prompts, tool inputs, or tool output. Keeps only token
    counts, identifiers, tool names, file paths passed to file tools, and timestamps.
    """
    st = path.stat()
    result = FileResult(path=str(path), size=st.st_size, mtime_ns=st.st_mtime_ns)
    sidechain_file = "subagents" in path.parts
    by_id: Dict[str, dict] = {}
    unchanged_reads: Dict[tuple, int] = {}
    seen_tool_ids: set = set()
    gap_seconds = idle_gap_hours * 3600

    for lineno, obj, error in iter_jsonl(path):
        result.line_count = lineno
        if error == "blank":
            continue
        if error == "truncated":
            result.truncated = True
            continue
        if error:
            result.malformed_lines.append(lineno)
            continue
        kind = obj.get("type")
        if kind not in ("assistant", "user", "system", "attachment", "summary") and "sessionId" not in obj:
            continue
        result.recognized_lines += 1
        session_id = obj.get("sessionId") if isinstance(obj.get("sessionId"), str) else None
        if not session_id:
            continue
        sess = result.sessions.get(session_id)
        if sess is None:
            sess = result.sessions[session_id] = _new_session(session_id, sidechain_file or bool(obj.get("isSidechain")))
        ts = parse_ts(obj.get("timestamp"))
        ts_epoch = ts.timestamp() if ts else None
        if ts_epoch is not None:
            if sess["first_ts"] is None or ts_epoch < sess["first_ts"]:
                sess["first_ts"] = ts_epoch
            if sess["last_ts"] is None or ts_epoch > sess["last_ts"]:
                sess["last_ts"] = ts_epoch
        cwd = obj.get("cwd") if isinstance(obj.get("cwd"), str) else None
        if cwd and cwd not in sess["cwds"]:
            sess["cwds"].append(cwd)
        version = obj.get("version")
        if isinstance(version, str) and version not in sess["versions"]:
            sess["versions"].append(version)

        if kind == "system" and obj.get("subtype") == "compact_boundary":
            meta = obj.get("compactMetadata") if isinstance(obj.get("compactMetadata"), dict) else {}
            sess["compactions"].append(
                {"ts": ts_epoch, "trigger": meta.get("trigger"), "pre_tokens": _int_or_none(meta.get("preTokens"))}
            )
            continue

        if kind == "user":
            message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            content = message.get("content")
            is_prompt = False
            if isinstance(content, str):
                is_prompt = True
            elif isinstance(content, list):
                types = {c.get("type") for c in content if isinstance(c, dict)}
                is_prompt = bool(types) and "tool_result" not in types
            if is_prompt and not obj.get("isMeta") and not obj.get("isCompactSummary"):
                sess["user_prompts"] += 1
            continue

        if kind != "assistant":
            continue
        message = obj.get("message") if isinstance(obj.get("message"), dict) else None
        if message is None:
            continue

        # Tool-call signals (names and file paths only).
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name") if isinstance(block.get("name"), str) else "unknown"
            block_id = block.get("id")
            if block_id:
                # The same tool call can appear on repeated lines of one response.
                if block_id in seen_tool_ids:
                    continue
                seen_tool_ids.add(block_id)
            sess["tool_counts"][name] = sess["tool_counts"].get(name, 0) + 1
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            fpath = tool_input.get("file_path") or tool_input.get("notebook_path")
            if not isinstance(fpath, str) or not fpath:
                continue
            key = (session_id, fpath)
            if name == "Read":
                unchanged_reads[key] = unchanged_reads.get(key, 0) + 1
                entry = sess["reads"].setdefault(fpath, {"count": 0, "max_unchanged": 0})
                entry["count"] += 1
                entry["max_unchanged"] = max(entry["max_unchanged"], unchanged_reads[key])
            elif name in FILE_MODIFYING_TOOLS:
                unchanged_reads[key] = 0
                if name == "Write":
                    sess["full_writes"][fpath] = sess["full_writes"].get(fpath, 0) + 1

        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        msg_id = message.get("id") if isinstance(message.get("id"), str) else None
        req_id = obj.get("requestId") if isinstance(obj.get("requestId"), str) else None
        if msg_id and req_id:
            record_id = "cc:%s:%s" % (msg_id, req_id)
        elif msg_id:
            record_id = "cc:%s" % msg_id
        elif isinstance(obj.get("uuid"), str):
            record_id = "cc-line:%s" % obj["uuid"]
        else:
            # Documented fallback fingerprint: file path + line number.
            record_id = "cc-fp:" + hashlib.sha256(("%s:%d" % (path, lineno)).encode()).hexdigest()[:24]

        cache_split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
        details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), dict) else {}
        server = usage.get("server_tool_use") if isinstance(usage.get("server_tool_use"), dict) else {}
        model = message.get("model") if isinstance(message.get("model"), str) else None
        record = {
            "schema_version": SCHEMA_VERSION,
            "record_id": record_id,
            "source": TRANSCRIPT_SOURCE,
            "adapter_version": TRANSCRIPT_ADAPTER_VERSION,
            "session_id": session_id,
            "project_id": cwd,
            "timestamp": obj.get("timestamp") if isinstance(obj.get("timestamp"), str) else None,
            "ts_epoch": ts_epoch,
            "model": model,
            "synthetic": model == "<synthetic>",
            "input_tokens": _int_or_none(usage.get("input_tokens")),
            "output_tokens": _int_or_none(usage.get("output_tokens")),
            "cache_read_tokens": _int_or_none(usage.get("cache_read_input_tokens")),
            "cache_creation_tokens": _int_or_none(usage.get("cache_creation_input_tokens")),
            "other_token_metrics": {
                "cache_creation_5m": _int_or_none(cache_split.get("ephemeral_5m_input_tokens")),
                "cache_creation_1h": _int_or_none(cache_split.get("ephemeral_1h_input_tokens")),
                "thinking_tokens_subset_of_output": _int_or_none(details.get("thinking_tokens")),
                "web_search_requests": _int_or_none(server.get("web_search_requests")),
                "web_fetch_requests": _int_or_none(server.get("web_fetch_requests")),
            },
            "speed": usage.get("speed") if isinstance(usage.get("speed"), str) else None,
            "service_tier": usage.get("service_tier") if isinstance(usage.get("service_tier"), str) else None,
            "inference_geo": usage.get("inference_geo") if isinstance(usage.get("inference_geo"), str) else None,
            "stop_reason": message.get("stop_reason") if isinstance(message.get("stop_reason"), str) else None,
            "is_sidechain": sidechain_file or bool(obj.get("isSidechain")),
            "cost_amount": None,
            "cost_currency": None,
            "provenance": {"file": str(path), "line": lineno, "claude_code_version": version},
        }
        core = [record[k] for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")]
        record["data_quality"] = "complete" if all(v is not None for v in core) else (
            "partial" if any(v is not None for v in core) else "no_token_fields"
        )
        # Repeated lines of one response can carry a partial, mid-stream output count.
        # Keep the line with the highest output_tokens (the final count); on ties keep
        # the later line.
        previous = by_id.get(record_id)
        if previous is None or (record["output_tokens"] or 0) >= (previous["output_tokens"] or 0):
            by_id[record_id] = record

    for record in by_id.values():
        sess = result.sessions.get(record["session_id"])
        if sess is None:
            continue
        sess["requests"] += 1
        if record["model"] and record["model"] not in sess["models"]:
            sess["models"].append(record["model"])
        if record["stop_reason"] == "max_tokens":
            sess["max_tokens_stops"] += 1
    # Attribute each request to the directory its session started in, so a session that
    # changes into a subdirectory is not split into several projects.
    for record in by_id.values():
        sess = result.sessions.get(record["session_id"])
        record["provenance"]["cwd"] = record["project_id"]
        if sess and sess["cwds"]:
            record["project_id"] = sess["cwds"][0]
    result.records = sorted(by_id.values(), key=lambda r: (r["ts_epoch"] or 0, r["provenance"]["line"]))
    _attach_gap_evidence(result, gap_seconds)
    if result.line_count and result.recognized_lines == 0:
        result.status = "not_transcript"
        result.note = "No Claude Code transcript lines were recognized; ignored."
    return result


def _attach_gap_evidence(result: FileResult, gap_seconds: float) -> None:
    """Find long pauses between consecutive requests in a session and record the
    cache-write tokens of the first request after each pause."""
    per_session: Dict[str, list] = {}
    for record in result.records:
        if record["ts_epoch"] is not None and not record["synthetic"]:
            per_session.setdefault(record["session_id"], []).append(record)
    for session_id, records in per_session.items():
        sess = result.sessions.get(session_id)
        if sess is None:
            continue
        for prev, cur in zip(records, records[1:]):
            gap = cur["ts_epoch"] - prev["ts_epoch"]
            if gap >= gap_seconds:
                sess["idle_gaps"].append(
                    {
                        "ts": cur["ts_epoch"],
                        "hours": round(gap / 3600, 1),
                        "cache_creation_after": cur["cache_creation_tokens"],
                        "prompt_tokens_after": _sum_known(
                            cur["input_tokens"], cur["cache_creation_tokens"], cur["cache_read_tokens"]
                        ),
                    }
                )


def _sum_known(*values):
    if any(v is None for v in values):
        return None
    return sum(values)


# ---------------------------------------------------------------- discovery


@dataclass
class SourceStatus:
    source_id: str
    location: str
    status: str  # ok, missing, empty, unreadable, disabled
    files: int = 0
    bytes: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "location": self.location,
            "status": self.status,
            "files": self.files,
            "bytes": self.bytes,
            "note": self.note,
        }


def transcript_roots(cfg: dict) -> List[Path]:
    roots = [claude_config_dir() / "projects"]
    for extra in cfg.get("sources.extra_transcript_dirs", []):
        roots.append(Path(extra).expanduser())
    return roots


def list_transcript_files(root: Path, max_bytes: int, skipped: list) -> List[Path]:
    """Walk a transcript root without following symlinked directories.

    Symlinked files are included only when they resolve inside the root.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.endswith(".jsonl"):
                continue
            full = Path(dirpath) / name
            try:
                if full.is_symlink() and not is_within(full, root):
                    skipped.append((str(full), "symlink points outside the source directory"))
                    continue
                size = full.stat().st_size
            except OSError:
                skipped.append((str(full), "unreadable"))
                continue
            if size > max_bytes:
                skipped.append((str(full), "larger than sources.max_file_mb"))
                continue
            found.append(full)
    found.sort()
    return found


def discover_sources(cfg: dict, base_data_dir: Path) -> List[SourceStatus]:
    statuses = []
    if not cfg.get("sources.claude_transcripts", True):
        statuses.append(SourceStatus(TRANSCRIPT_SOURCE, "-", "disabled", note="Disabled in settings."))
    else:
        for root in transcript_roots(cfg):
            shown = display_path(root)
            if not root.exists():
                statuses.append(SourceStatus(TRANSCRIPT_SOURCE, shown, "missing", note="Directory not found."))
                continue
            if not os.access(str(root), os.R_OK | os.X_OK):
                statuses.append(SourceStatus(TRANSCRIPT_SOURCE, shown, "unreadable", note="Permission denied."))
                continue
            skipped: list = []
            files = list_transcript_files(root, cfg.get("sources.max_file_mb", 512) * 1024 * 1024, skipped)
            total = 0
            for f in files:
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
            note = "%d file(s) skipped" % len(skipped) if skipped else ""
            statuses.append(SourceStatus(TRANSCRIPT_SOURCE, shown, "ok" if files else "empty", len(files), total, note))
    events = base_data_dir / "events" / "instructions.jsonl"
    if not cfg.get("collection.instruction_events", False):
        statuses.append(
            SourceStatus(HOOK_SOURCE, display_path(events), "disabled", note="Opt in with: settings set collection.instruction_events true")
        )
    elif events.exists():
        statuses.append(SourceStatus(HOOK_SOURCE, display_path(events), "ok", 1, events.stat().st_size))
    else:
        statuses.append(SourceStatus(HOOK_SOURCE, display_path(events), "empty", note="Enabled; no events recorded yet."))
    return statuses


# ---------------------------------------------------------------- dataset


@dataclass
class Dataset:
    records: List[dict]
    sessions: List[dict]
    files: List[dict]
    sources: List[SourceStatus]
    duplicates_removed: int
    malformed_lines: int
    truncated_files: int
    unsupported_files: int
    skipped_files: List[tuple]
    cache_note: str = ""

    @property
    def earliest(self) -> Optional[float]:
        values = [r["ts_epoch"] for r in self.records if r["ts_epoch"] is not None]
        return min(values) if values else None

    @property
    def latest(self) -> Optional[float]:
        values = [r["ts_epoch"] for r in self.records if r["ts_epoch"] is not None]
        return max(values) if values else None


CACHE_FORMAT = 3  # bump whenever scan_transcript output changes


def _cache_path(base_data_dir: Path) -> Path:
    return base_data_dir / "cache" / ("transcripts-a%d-c%d.json" % (TRANSCRIPT_ADAPTER_VERSION, CACHE_FORMAT))


def _load_cache(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"files": {}}


def _excluded(project: Optional[str], excluded: List[str]) -> bool:
    if not project or not excluded:
        return False
    project_n = os.path.normcase(os.path.normpath(project))
    for prefix in excluded:
        p = os.path.normcase(os.path.normpath(os.path.expanduser(prefix)))
        if project_n == p or project_n.startswith(p.rstrip(os.sep) + os.sep):
            return True
    return False


def load_dataset(cfg: dict, base_data_dir: Path, use_cache: Optional[bool] = None) -> Dataset:
    """Discover sources, parse transcripts (with a size+mtime cache), and deduplicate."""
    sources = discover_sources(cfg, base_data_dir)
    use_cache = cfg.get("cache.enabled", True) if use_cache is None else use_cache
    idle_hours = cfg.get("thresholds.idle_gap_hours", 4)
    skipped: List[tuple] = []
    paths: List[Path] = []
    if cfg.get("sources.claude_transcripts", True):
        max_bytes = cfg.get("sources.max_file_mb", 512) * 1024 * 1024
        for root in transcript_roots(cfg):
            if root.is_dir():
                paths.extend(list_transcript_files(root, max_bytes, skipped))

    cache_file = _cache_path(base_data_dir)
    cache = _load_cache(cache_file) if use_cache else {"files": {}}
    cache_key_extra = "gap%d" % idle_hours
    results: List[FileResult] = []
    dirty = False
    for p in paths:
        key = str(p)
        try:
            st = p.stat()
        except OSError:
            skipped.append((key, "unreadable"))
            continue
        cached = cache["files"].get(key)
        if (
            cached
            and cached.get("size") == st.st_size
            and cached.get("mtime_ns") == st.st_mtime_ns
            and cached.get("extra") == cache_key_extra
        ):
            results.append(FileResult.from_cache(cached["result"]))
            continue
        try:
            res = scan_transcript(p, idle_hours)
        except PermissionError:
            skipped.append((key, "permission denied"))
            continue
        except OSError:
            skipped.append((key, "unreadable"))
            continue
        results.append(res)
        cache["files"][key] = {
            "size": res.size,
            "mtime_ns": res.mtime_ns,
            "extra": cache_key_extra,
            "result": res.to_cache(),
        }
        dirty = True
    live = {str(p) for p in paths}
    stale = [k for k in cache["files"] if k not in live]
    for k in stale:
        del cache["files"][k]
        dirty = True
    cache_note = ""
    if use_cache and dirty:
        try:
            with file_lock(cache_file, timeout=2.0):
                atomic_write_text(cache_file, json.dumps(cache, separators=(",", ":")))
        except BMError as exc:
            cache_note = "Cache not updated (%s)." % exc.code

    excluded = cfg.get("privacy.excluded_projects", [])
    merged: Dict[str, dict] = {}
    duplicates = 0
    sessions: List[dict] = []
    files_info = []
    malformed = truncated = unsupported = 0
    for res in results:
        files_info.append(
            {
                "path": res.path,
                "status": res.status,
                "lines": res.line_count,
                "malformed_lines": len(res.malformed_lines),
                "truncated": res.truncated,
                "records": len(res.records),
            }
        )
        malformed += len(res.malformed_lines)
        truncated += 1 if res.truncated else 0
        unsupported += 1 if res.status == "not_transcript" else 0
        for record in res.records:
            if _excluded(record["project_id"], excluded):
                continue
            existing = merged.get(record["record_id"])
            if existing is not None:
                duplicates += 1
                if (record["output_tokens"] or 0) <= (existing["output_tokens"] or 0):
                    continue
            merged[record["record_id"]] = record
        for sess in res.sessions.values():
            if sess["cwds"] and all(_excluded(c, excluded) for c in sess["cwds"]):
                continue
            entry = dict(sess)
            entry["file"] = res.path
            sessions.append(entry)
    records = sorted(merged.values(), key=lambda r: (r["ts_epoch"] or 0, r["record_id"]))
    return Dataset(
        records=records,
        sessions=sessions,
        files=files_info,
        sources=sources,
        duplicates_removed=duplicates,
        malformed_lines=malformed,
        truncated_files=truncated,
        unsupported_files=unsupported,
        skipped_files=skipped,
        cache_note=cache_note,
    )


# ---------------------------------------------------------------- hook events


def events_path(base_data_dir: Path) -> Path:
    return base_data_dir / "events" / "instructions.jsonl"


def load_instruction_events(base_data_dir: Path) -> List[dict]:
    path = events_path(base_data_dir)
    if not path.exists():
        return []
    events = []
    for _lineno, obj, error in iter_jsonl(path):
        if error or obj is None:
            continue
        if obj.get("schema_version") != 1 or not isinstance(obj.get("file_path"), str):
            continue
        events.append(obj)
    return events


def prune_events(base_data_dir: Path, retention_days: int, now: Optional[float] = None) -> int:
    """Delete Boring Meter's own hook events older than the retention period.

    Returns the number of events removed. Never touches Claude Code's files.
    """
    if retention_days <= 0:
        return 0
    path = events_path(base_data_dir)
    if not path.exists():
        return 0
    cutoff = (now or time.time()) - retention_days * 86400
    kept, removed = [], 0
    with file_lock(path):
        for _lineno, obj, error in iter_jsonl(path):
            if error or obj is None:
                removed += 1 if error and error != "blank" else 0
                continue
            ts = parse_ts(obj.get("ts"))
            if ts is not None and ts.timestamp() < cutoff:
                removed += 1
                continue
            kept.append(json.dumps(obj, sort_keys=True, ensure_ascii=False))
        if removed:
            atomic_write_text(path, "".join(line + "\n" for line in kept))
    return removed
