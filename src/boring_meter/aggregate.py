"""Aggregation of normalized usage records into period summaries.

Only observed values are summed. A category total counts only records where that
category is known; records missing it are counted separately and never treated as
zero. The combined token total sums the four disjoint API categories and includes
only records where all four are known.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from boring_meter.adapters import Dataset
from boring_meter.paths import claude_config_dir
from boring_meter.pricing import ASSUMPTIONS, price_record
from boring_meter.timeutil import Period, local_day

CATEGORY_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")
FUTURE_TOLERANCE_SECONDS = 300


def _blank_totals() -> dict:
    return {k: {"sum": 0, "known": 0, "missing": 0} for k in CATEGORY_KEYS}


def _add(totals: dict, record: dict) -> None:
    for key in CATEGORY_KEYS:
        value = record.get(key)
        if value is None:
            totals[key]["missing"] += 1
        else:
            totals[key]["sum"] += value
            totals[key]["known"] += 1


def _combined(records: List[dict]) -> dict:
    complete = [r for r in records if all(r.get(k) is not None for k in CATEGORY_KEYS)]
    return {
        "sum": sum(sum(r[k] for k in CATEGORY_KEYS) for r in complete),
        "records_included": len(complete),
        "records_excluded": len(records) - len(complete),
        "definition": "input + output + cache read + cache write tokens; disjoint API categories",
    }


def cleanup_period_days() -> Optional[int]:
    """Read only cleanupPeriodDays from Claude Code's user settings, if present."""
    import json

    path = claude_config_dir() / "settings.json"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle).get("cleanupPeriodDays")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def filter_records(
    dataset: Dataset,
    period: Period,
    session_id: Optional[str] = None,
    project: Optional[str] = None,
) -> List[dict]:
    out = []
    for record in dataset.records:
        if session_id and record["session_id"] != session_id and not record["session_id"].startswith(session_id):
            continue
        if project and not _in_project(record.get("project_id"), project):
            continue
        ts = datetime.fromtimestamp(record["ts_epoch"], timezone.utc) if record["ts_epoch"] is not None else None
        if session_id is None and not period.contains(ts):
            continue
        out.append(record)
    return out


def _in_project(cwd: Optional[str], project: str) -> bool:
    if not cwd:
        return False
    root = project.rstrip("/")
    return cwd == root or cwd.startswith(root + "/")


def cost_summary(records: List[dict], pricing: Optional[dict]) -> dict:
    if pricing is None:
        return {"available": False, "reason": "Cost estimates are turned off (pricing.enabled is false)."}
    total = Decimal(0)
    priced = 0
    reasons: Counter = Counter()
    by_model: dict = defaultdict(Decimal)
    for record in records:
        cost, reason = price_record(record, pricing)
        if cost is None:
            reasons[reason] += 1
            continue
        priced += 1
        total += cost
        by_model[record["model"]] += cost
    real = [r for r in records if not r.get("synthetic")]
    unpriced_real = len(real) - priced
    return {
        "available": priced > 0,
        "kind": "estimate (locally calculated from API list prices)",
        "currency": pricing["currency"],
        "amount": _money(total) if priced else None,
        "by_model": {m: _money(v) for m, v in sorted(by_model.items(), key=lambda kv: -kv[1])},
        "records_priced": priced,
        "records_unpriced": unpriced_real,
        "unpriced_reasons": dict(reasons.most_common()),
        "complete": priced > 0 and unpriced_real == 0,
        "pricing_version": pricing["pricing_version"],
        "pricing_effective_date": pricing["effective_date"],
        "pricing_source": pricing["source"],
        "source_reported_cost": None,
        "source_reported_cost_note": "Claude Code transcripts do not contain billed cost, so no authoritative cost is available.",
        "assumptions": list(ASSUMPTIONS),
    }


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))


def summarize(
    dataset: Dataset,
    period: Period,
    tz,
    pricing: Optional[dict],
    session_id: Optional[str] = None,
    project: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    records = filter_records(dataset, period, session_id=session_id, project=project)
    real = [r for r in records if not r.get("synthetic")]
    synthetic = len(records) - len(real)

    totals = _blank_totals()
    by_model: dict = defaultdict(lambda: {"requests": 0, "totals": _blank_totals()})
    by_day: dict = defaultdict(lambda: {"requests": 0, "totals": _blank_totals()})
    by_project: dict = defaultdict(lambda: {"requests": 0, "sessions": set(), "totals": _blank_totals()})
    sessions_all: set = set()
    sessions_incomplete: set = set()
    future = 0
    for record in real:
        _add(totals, record)
        model = record.get("model") or "(unknown model)"
        by_model[model]["requests"] += 1
        _add(by_model[model]["totals"], record)
        if record["ts_epoch"] is not None:
            ts = datetime.fromtimestamp(record["ts_epoch"], timezone.utc)
            day = local_day(ts, tz)
            by_day[day]["requests"] += 1
            _add(by_day[day]["totals"], record)
            if record["ts_epoch"] > now.timestamp() + FUTURE_TOLERANCE_SECONDS:
                future += 1
        proj = record.get("project_id") or "(unknown project)"
        by_project[proj]["requests"] += 1
        by_project[proj]["sessions"].add(record["session_id"])
        _add(by_project[proj]["totals"], record)
        sessions_all.add(record["session_id"])
        if record["data_quality"] != "complete":
            sessions_incomplete.add(record["session_id"])

    coverage_notes = []
    earliest = dataset.earliest
    if period.start is not None and (earliest is None or earliest > period.start.timestamp()):
        if earliest is None:
            coverage_notes.append("No usage records are available at all.")
        else:
            coverage_notes.append(
                "The earliest available record (%s) is after the period start, so the start of the period is not covered."
                % local_day(datetime.fromtimestamp(earliest, timezone.utc), tz)
            )
    missing_any = sum(totals[k]["missing"] for k in CATEGORY_KEYS)
    if missing_any:
        coverage_notes.append("%d request(s) are missing one or more token categories; those values are unknown, not zero." % len(
            [r for r in real if r["data_quality"] != "complete"]
        ))
    if dataset.malformed_lines or dataset.truncated_files:
        coverage_notes.append(
            "%d malformed line(s) and %d truncated file ending(s) were skipped; the affected requests may be missing."
            % (dataset.malformed_lines, dataset.truncated_files)
        )
    if dataset.skipped_files:
        coverage_notes.append("%d transcript file(s) were skipped (unreadable, too large, or outside the source)." % len(dataset.skipped_files))
    if future:
        coverage_notes.append("%d record(s) have timestamps in the future; check the system clock or timezone." % future)
    retention = cleanup_period_days()
    retention_note = (
        "Claude Code keeps transcripts for %d days (cleanupPeriodDays)." % retention
        if retention is not None
        else "Claude Code deletes transcripts after cleanupPeriodDays (default 30), so older history may be missing."
    )

    if not real:
        coverage = "none"
    elif coverage_notes:
        coverage = "partial"
    else:
        coverage = "complete"

    def finish(group: dict) -> dict:
        return {"requests": group["requests"], "totals": group["totals"]}

    projects = sorted(by_project.items(), key=lambda kv: -kv[1]["requests"])
    return {
        "period": period.to_dict(),
        "filters": {"session_id": session_id, "project": project},
        "source": "claude-code-transcripts",
        "coverage": coverage,
        "coverage_notes": coverage_notes,
        "retention_note": retention_note,
        "data_window": {
            "earliest": datetime.fromtimestamp(earliest, timezone.utc).isoformat() if earliest else None,
            "latest": datetime.fromtimestamp(dataset.latest, timezone.utc).isoformat() if dataset.latest else None,
        },
        "requests": len(real),
        "synthetic_messages_excluded": synthetic,
        "sessions": len(sessions_all),
        "sessions_with_incomplete_data": len(sessions_incomplete),
        "totals": totals,
        "combined_tokens": _combined(real),
        "by_model": {m: finish(g) for m, g in sorted(by_model.items(), key=lambda kv: -kv[1]["requests"])},
        "by_day": {d: finish(g) for d, g in sorted(by_day.items())},
        "by_project": [
            {"project": p, "requests": g["requests"], "sessions": len(g["sessions"]), "totals": g["totals"]}
            for p, g in projects
        ],
        "duplicates_removed": dataset.duplicates_removed,
        "cost": cost_summary(real, pricing),
        "subscription_note": "Recorded token counts are not your remaining subscription allowance. Claude Code transcripts do not expose plan quotas.",
    }
