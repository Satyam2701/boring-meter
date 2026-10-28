"""Before-and-after optimization experiments.

An experiment holds baseline runs and follow-up runs. Each run is a measurement of
one Claude Code session (or an explicit time window) taken from observed transcript
data. Results are classified as:

  invalid       measurements are missing, incomplete, or not comparable (for example
                different models)
  inconclusive  comparable, but the difference is within run-to-run spread, quality
                degraded, or the follow-up task was not completed
  verified      at least two runs on each side, complete data, same models, no
                comparability warnings, quality preserved or improved, task completed,
                and the mean difference is larger than the spread between runs
  directional   comparable data that does not meet the verified bar (for example a
                single run on each side, or quality not yet recorded)

A verified result means the measured difference is consistent across runs under
comparable conditions. It does not prove the change caused it.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from boring_meter.aggregate import CATEGORY_KEYS
from boring_meter.errors import BMError
from boring_meter.pricing import price_record
from boring_meter.store import atomic_write_json, file_lock, read_json

QUALITY = ("preserved", "improved", "degraded", "unknown")
COMPLETION = ("yes", "no", "unknown")
CACHE_SHARE_WARN = 0.25
REQUEST_RATIO_WARN = 2.0


def store_path(base: Path) -> Path:
    return base / "experiments" / "experiments.json"


def _load(base: Path) -> dict:
    path = store_path(base)
    data = read_json(path)
    if data is None:
        return {"schema_version": 1, "experiments": {}}
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("experiments"), dict):
        raise BMError(
            "CORRUPTED_RECORD",
            "The experiment store has an unexpected format.",
            "Move %s aside to start fresh; it was not modified." % path.name,
        )
    return data


def _save(base: Path, data: dict) -> None:
    atomic_write_json(store_path(base), data)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _get(data: dict, exp_id: str) -> dict:
    exp = data["experiments"].get(exp_id)
    if exp is None:
        matches = [k for k in data["experiments"] if k.startswith(exp_id)] if exp_id else []
        if len(matches) == 1:
            return data["experiments"][matches[0]]
        raise BMError("EXPERIMENT_NOT_FOUND", "No experiment with id '%s'." % exp_id, "List experiments with: boring-meter experiment list")
    return exp


def start(base: Path, name: str, optimization: str, task_type: str = "", project: str = "", notes: str = "") -> dict:
    if not name.strip():
        raise BMError("INVALID_ARGUMENT", "An experiment needs a name.")
    if not optimization.strip():
        raise BMError("INVALID_ARGUMENT", "Describe the optimization being tested with --change.")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "exp"
    exp_id = "%s-%s" % (slug, secrets.token_hex(3))
    exp = {
        "experiment_id": exp_id,
        "name": name.strip(),
        "optimization": optimization.strip(),
        "task_type": task_type.strip(),
        "project": project,
        "notes": notes.strip(),
        "created": _now(),
        "baseline": [],
        "followup": [],
        "quality": "unknown",
        "task_completed": {"baseline": "unknown", "followup": "unknown"},
    }
    with file_lock(store_path(base)):
        data = _load(base)
        data["experiments"][exp_id] = exp
        _save(base, data)
    return exp


def measure(records: List[dict], label: str, pricing: Optional[dict]) -> dict:
    """Summarize observed usage for one run. Never fills unknown values."""
    real = [r for r in records if not r.get("synthetic")]
    totals = {}
    complete = bool(real)
    for key in CATEGORY_KEYS:
        values = [r[key] for r in real]
        if any(v is None for v in values):
            complete = False
            totals[key] = None
        else:
            totals[key] = sum(values)
    cost, cost_note = None, None
    if pricing and real:
        amounts = [price_record(r, pricing) for r in real]
        if all(a is not None for a, _r in amounts):
            cost = str(sum((a for a, _r in amounts), Decimal(0)).quantize(Decimal("0.0001")))
        else:
            cost_note = "Not all requests could be priced."
    models = sorted({r["model"] for r in real if r.get("model")})
    versions = sorted({r["provenance"].get("claude_code_version") for r in real if r["provenance"].get("claude_code_version")})
    total = sum(totals.values()) if complete else None
    cache_share = None
    if complete and total:
        cache_share = round(totals["cache_read_tokens"] / total, 4)
    return {
        "label": label,
        "recorded": _now(),
        "requests": len(real),
        "sessions": sorted({r["session_id"] for r in real}),
        "first_ts": min((r["ts_epoch"] for r in real if r["ts_epoch"]), default=None),
        "last_ts": max((r["ts_epoch"] for r in real if r["ts_epoch"]), default=None),
        "totals": totals,
        "total_tokens": total,
        "complete": complete,
        "models": models,
        "claude_code_versions": versions,
        "cache_read_share": cache_share,
        "cost_estimate": cost,
        "cost_note": cost_note,
        "pricing_version": pricing["pricing_version"] if pricing and cost is not None else None,
    }


def add_run(base: Path, exp_id: str, side: str, run: dict) -> dict:
    if side not in ("baseline", "followup"):
        raise BMError("INVALID_ARGUMENT", "Side must be baseline or followup.")
    if run["requests"] == 0:
        raise BMError(
            "NO_DATA",
            "No usage records matched that session or time window, so nothing was recorded.",
            "Check the session id with 'boring-meter usage --sessions', or pass --since/--until.",
        )
    with file_lock(store_path(base)):
        data = _load(base)
        exp = _get(data, exp_id)
        existing = {s for r in exp["baseline"] + exp["followup"] for s in r["sessions"]}
        overlap = existing.intersection(run["sessions"])
        if overlap and run["label"].startswith("session"):
            raise BMError(
                "INVALID_EXPERIMENT",
                "Session %s is already recorded in this experiment." % sorted(overlap)[0][:8],
                "Each run should be a separate, comparable task.",
            )
        exp[side].append(run)
        _save(base, data)
    return exp


def set_outcome(base: Path, exp_id: str, quality: Optional[str], completed_side: Optional[str], completed: Optional[str]) -> dict:
    if quality is not None and quality not in QUALITY:
        raise BMError("INVALID_ARGUMENT", "Quality must be one of: %s." % ", ".join(QUALITY))
    if completed is not None and completed not in COMPLETION:
        raise BMError("INVALID_ARGUMENT", "Task completion must be one of: %s." % ", ".join(COMPLETION))
    with file_lock(store_path(base)):
        data = _load(base)
        exp = _get(data, exp_id)
        if quality is not None:
            exp["quality"] = quality
        if completed is not None:
            exp["task_completed"][completed_side or "followup"] = completed
        _save(base, data)
    return exp


def list_all(base: Path) -> List[dict]:
    return sorted(_load(base)["experiments"].values(), key=lambda e: e["created"])


def get(base: Path, exp_id: str) -> dict:
    return _get(_load(base), exp_id)


def delete(base: Path, exp_id: str) -> str:
    with file_lock(store_path(base)):
        data = _load(base)
        exp = _get(data, exp_id)
        del data["experiments"][exp["experiment_id"]]
        _save(base, data)
    return exp["experiment_id"]


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _spread(values: List[float]) -> float:
    return max(values) - min(values) if len(values) > 1 else 0.0


def compare(exp: dict) -> dict:
    base, follow = exp["baseline"], exp["followup"]
    warnings: List[str] = []
    invalid: List[str] = []
    if not base:
        invalid.append("No baseline run recorded.")
    if not follow:
        invalid.append("No follow-up run recorded.")
    runs = base + follow
    incomplete = [r for r in runs if not r["complete"]]
    if incomplete:
        invalid.append("%d run(s) are missing token categories, so totals cannot be compared." % len(incomplete))
    if base and follow:
        base_models = {m for r in base for m in r["models"]}
        follow_models = {m for r in follow for m in r["models"]}
        if base_models != follow_models:
            invalid.append("Different models were used (baseline: %s; follow-up: %s)." % (
                ", ".join(sorted(base_models)) or "none", ", ".join(sorted(follow_models)) or "none"))
        bv = {v for r in base for v in r["claude_code_versions"]}
        fv = {v for r in follow for v in r["claude_code_versions"]}
        if bv and fv and bv != fv:
            warnings.append("Claude Code versions differ (%s vs %s)." % (", ".join(sorted(bv)), ", ".join(sorted(fv))))
    result = {
        "experiment_id": exp["experiment_id"],
        "baseline_runs": len(base),
        "followup_runs": len(follow),
        "quality": exp["quality"],
        "task_completed": exp["task_completed"],
        "differences": {},
        "warnings": warnings,
        "invalid_reasons": invalid,
        "limitations": [
            "A before-and-after comparison shows association, not causation. Other changes between runs can affect usage.",
            "Single runs vary; record at least two runs on each side for a verified result.",
        ],
    }
    if invalid:
        result["classification"] = "invalid"
        return result

    for key in list(CATEGORY_KEYS) + ["total_tokens"]:
        b = [float(r["totals"][key]) for r in base] if key != "total_tokens" else [float(r["total_tokens"]) for r in base]
        f = [float(r["totals"][key]) for r in follow] if key != "total_tokens" else [float(r["total_tokens"]) for r in follow]
        mb, mf = _mean(b), _mean(f)
        result["differences"][key] = {
            "baseline_mean": round(mb, 1),
            "followup_mean": round(mf, 1),
            "difference": round(mf - mb, 1),
            "percent": round((mf - mb) / mb * 100, 1) if mb else None,
            "baseline_spread": round(_spread(b), 1),
            "followup_spread": round(_spread(f), 1),
        }
    costs_b = [r["cost_estimate"] for r in base]
    costs_f = [r["cost_estimate"] for r in follow]
    versions = {r["pricing_version"] for r in runs}
    if all(c is not None for c in costs_b + costs_f) and len(versions) == 1:
        cb = _mean([float(c) for c in costs_b])
        cf = _mean([float(c) for c in costs_f])
        result["differences"]["cost_estimate"] = {
            "baseline_mean": round(cb, 4), "followup_mean": round(cf, 4), "difference": round(cf - cb, 4),
            "percent": round((cf - cb) / cb * 100, 1) if cb else None,
            "note": "API list-price estimate (%s), not a subscription charge." % versions.pop(),
        }
    else:
        result["differences"]["cost_estimate"] = None

    share_b = [r["cache_read_share"] for r in base if r["cache_read_share"] is not None]
    share_f = [r["cache_read_share"] for r in follow if r["cache_read_share"] is not None]
    if share_b and share_f and abs(_mean(share_b) - _mean(share_f)) > CACHE_SHARE_WARN:
        warnings.append("Prompt-cache read share differs a lot (%.0f%% vs %.0f%%); caching, not the change, may explain part "
                        "of the difference." % (_mean(share_b) * 100, _mean(share_f) * 100))
    req_b = _mean([r["requests"] for r in base])
    req_f = _mean([r["requests"] for r in follow])
    if min(req_b, req_f) and max(req_b, req_f) / min(req_b, req_f) > REQUEST_RATIO_WARN:
        warnings.append("Request counts differ by more than %dx (%.0f vs %.0f); the tasks may not be equivalent." % (
            REQUEST_RATIO_WARN, req_b, req_f))

    total = result["differences"]["total_tokens"]
    noise = max(total["baseline_spread"], total["followup_spread"])
    quality = exp["quality"]
    done = exp["task_completed"].get("followup", "unknown")
    reasons = []
    if quality == "degraded":
        result["classification"] = "inconclusive"
        reasons.append("Quality was reported as degraded, so any usage reduction is not counted as a saving.")
    elif done == "no":
        result["classification"] = "inconclusive"
        reasons.append("The follow-up task was not completed.")
    elif total["difference"] == 0 or (len(base) > 1 and len(follow) > 1 and abs(total["difference"]) <= noise):
        result["classification"] = "inconclusive"
        reasons.append("The difference is within the variation between runs.")
    elif (len(base) >= 2 and len(follow) >= 2 and not warnings and quality in ("preserved", "improved")
          and done == "yes" and exp["task_completed"].get("baseline") != "no"):
        result["classification"] = "verified"
    else:
        result["classification"] = "directional"
        if len(base) < 2 or len(follow) < 2:
            reasons.append("Fewer than two runs on each side.")
        if quality == "unknown":
            reasons.append("Task quality has not been recorded, so it is not known whether quality was preserved.")
        if done != "yes":
            reasons.append("Follow-up task completion has not been confirmed.")
        if warnings:
            reasons.append("Comparability warnings are present.")
    result["classification_reasons"] = reasons
    return result
