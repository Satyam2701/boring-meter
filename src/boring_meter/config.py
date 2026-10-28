"""Local configuration: defaults, schema validation, and persistence."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from boring_meter.errors import BMError
from boring_meter.paths import data_dir, display_path
from boring_meter.store import atomic_write_json, file_lock, read_json

CONFIG_VERSION = 1

# key: (type, default, description, extra)
# extra may hold: min, max, choices, reload (what is needed for the change to apply)
SCHEMA = {
    "sources.claude_transcripts": ("bool", True, "Read Claude Code session transcripts (read-only).", {}),
    "sources.extra_transcript_dirs": (
        "list",
        [],
        "Additional directories that contain Claude Code transcript .jsonl files.",
        {},
    ),
    "sources.max_file_mb": ("int", 512, "Skip transcript files larger than this many MB.", {"min": 1, "max": 100000}),
    "collection.instruction_events": (
        "bool",
        False,
        "Record which instruction files Claude Code loads (InstructionsLoaded hook). Metadata only.",
        {"reload": "Takes effect for the next instruction load. If the plugin was installed in this session, run /reload-plugins first."},
    ),
    "pricing.enabled": ("bool", True, "Show API list-price cost estimates when pricing is known.", {}),
    "pricing.file": ("path", "", "Use this pricing JSON file instead of the bundled table.", {}),
    "thresholds.instruction_lines": (
        "int",
        200,
        "Flag always-loaded instruction files longer than this many lines (official guidance: under 200).",
        {"min": 10, "max": 100000},
    ),
    "thresholds.instruction_chars": (
        "int",
        40000,
        "Flag always-loaded instruction text larger than this many characters in total.",
        {"min": 1000, "max": 10000000},
    ),
    "thresholds.repeated_read_count": (
        "int",
        4,
        "Flag a file read this many times in one session with no edit in between.",
        {"min": 2, "max": 1000},
    ),
    "thresholds.rewrite_count": (
        "int",
        3,
        "Flag a file fully rewritten (Write tool) this many times in one session.",
        {"min": 2, "max": 1000},
    ),
    "thresholds.idle_gap_hours": (
        "int",
        4,
        "Treat a pause this long inside one session as a possible task switch.",
        {"min": 1, "max": 720},
    ),
    "thresholds.cache_rewrite_tokens": (
        "int",
        20000,
        "Minimum cache-write tokens after a long pause before it is reported.",
        {"min": 0, "max": 100000000},
    ),
    "thresholds.subagent_output_tokens": (
        "int",
        1500,
        "Median output tokens per subagent request at or below which the work is treated as routine.",
        {"min": 1, "max": 1000000},
    ),
    "thresholds.min_requests_for_model_rule": (
        "int",
        20,
        "Minimum subagent requests on one model before the model rule runs.",
        {"min": 1, "max": 1000000},
    ),
    "retention.event_days": (
        "int",
        90,
        "Delete Boring Meter's own collected hook events older than this. 0 keeps them forever.",
        {"min": 0, "max": 36500},
    ),
    "retention.export_days": (
        "int",
        90,
        "Delete reports saved under the data directory's exports folder older than this. 0 keeps them.",
        {"min": 0, "max": 36500},
    ),
    "report.default_days": ("int", 7, "Default reporting period in calendar days.", {"min": 1, "max": 3650}),
    "report.max_findings": ("int", 5, "Default number of findings shown.", {"min": 1, "max": 100}),
    "privacy.excluded_projects": (
        "list",
        [],
        "Project directories to leave out of every report and analysis.",
        {},
    ),
    "privacy.show_full_paths": (
        "bool",
        False,
        "Show full file paths in findings instead of paths relative to the project.",
        {},
    ),
    "time.timezone": ("str", "", "IANA timezone for calendar days, for example Europe/Berlin. Empty means system time.", {}),
    "logging.level": ("choice", "warning", "Diagnostic detail written to stderr.", {"choices": ["error", "warning", "info", "debug"]}),
    "cache.enabled": ("bool", True, "Cache parsed transcript metadata to speed up repeated runs.", {}),
}

TRUE_WORDS = {"true", "yes", "on", "1"}
FALSE_WORDS = {"false", "no", "off", "0"}


def defaults() -> dict:
    return {key: copy.deepcopy(spec[1]) for key, spec in SCHEMA.items()}


def config_path(base: Path | None = None) -> Path:
    return (base or data_dir()) / "config.json"


def _validate_value(key: str, value):
    kind, _default, _desc, extra = SCHEMA[key]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
    elif kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be a whole number")
        if "min" in extra and value < extra["min"]:
            raise ValueError("must be at least %d" % extra["min"])
        if "max" in extra and value > extra["max"]:
            raise ValueError("must be at most %d" % extra["max"])
    elif kind == "list":
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise ValueError("must be a list of non-empty strings")
    elif kind in ("str", "path"):
        if not isinstance(value, str):
            raise ValueError("must be text")
        if key == "time.timezone" and value:
            from boring_meter.timeutil import resolve_timezone

            resolve_timezone(value)
    elif kind == "choice":
        if value not in extra["choices"]:
            raise ValueError("must be one of: %s" % ", ".join(extra["choices"]))
    return value


def validate(raw: dict, source: str) -> dict:
    if not isinstance(raw, dict):
        raise BMError("INVALID_CONFIG", "%s must contain a JSON object." % source, "Run: boring-meter settings reset --yes")
    values = raw.get("values", {})
    if not isinstance(values, dict):
        raise BMError("INVALID_CONFIG", "%s has no valid 'values' object." % source, "Run: boring-meter settings reset --yes")
    version = raw.get("config_version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise BMError(
            "INVALID_CONFIG",
            "%s uses configuration version %r, but this Boring Meter expects %d." % (source, version, CONFIG_VERSION),
            "Back the file up, then run: boring-meter settings reset --yes",
        )
    merged = defaults()
    problems = []
    for key, value in values.items():
        if key not in SCHEMA:
            problems.append("%s: unknown setting" % key)
            continue
        try:
            merged[key] = _validate_value(key, value)
        except (ValueError, BMError) as exc:
            msg = exc.message if isinstance(exc, BMError) else str(exc)
            problems.append("%s: %s" % (key, msg))
    if problems:
        raise BMError(
            "INVALID_CONFIG",
            "%s has invalid settings: %s." % (source, "; ".join(problems)),
            "Fix them with 'boring-meter settings set KEY VALUE', or run 'boring-meter settings reset --yes'.",
        )
    return merged


def load(base: Path | None = None) -> dict:
    path = config_path(base)
    raw = read_json(path) if path.exists() else None
    if raw is None:
        return defaults()
    return validate(raw, display_path(path))


def save(values: dict, base: Path | None = None) -> None:
    path = config_path(base)
    changed = {k: v for k, v in values.items() if k in SCHEMA and v != SCHEMA[k][1]}
    with file_lock(path):
        atomic_write_json(path, {"config_version": CONFIG_VERSION, "values": changed})


def parse_cli_value(key: str, text: str):
    if key not in SCHEMA:
        close = [k for k in SCHEMA if key.split(".")[-1] in k]
        raise BMError(
            "INVALID_CONFIG",
            "Unknown setting '%s'." % key,
            ("Did you mean: %s? " % ", ".join(close) if close else "") + "List settings with: boring-meter settings show",
        )
    kind = SCHEMA[key][0]
    try:
        if kind == "bool":
            low = text.strip().lower()
            if low in TRUE_WORDS:
                value = True
            elif low in FALSE_WORDS:
                value = False
            else:
                raise ValueError("must be true or false")
        elif kind == "int":
            value = int(text.strip())
        elif kind == "list":
            stripped = text.strip()
            if stripped.startswith("["):
                value = json.loads(stripped)
            elif stripped == "":
                value = []
            else:
                value = [part.strip() for part in stripped.split(",") if part.strip()]
        else:
            value = text.strip()
        return _validate_value(key, value)
    except (ValueError, json.JSONDecodeError) as exc:
        raise BMError("INVALID_CONFIG", "Invalid value for %s: %s." % (key, exc))
