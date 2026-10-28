"""Command-line interface for Boring Meter."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from boring_meter import __version__, adapters, aggregate, config, experiments, instructions, optimize, rules
from boring_meter.errors import BMError
from boring_meter.paths import data_dir, display_path, ensure_private_dir, validate_output_path
from boring_meter.pricing import load_pricing
from boring_meter.render import banner, bullet, heading, kv, money, num, para, token_value
from boring_meter.store import atomic_write_text
from boring_meter.timeutil import parse_ts, resolve_period, resolve_timezone

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
VERIFIED_CLAUDE_CODE = "2.1.229 to 2.1.311"
LOG_LEVELS = {"error": 0, "warning": 1, "info": 2, "debug": 3}


class Context:
    def __init__(self, args):
        self.args = args
        self.base = data_dir()
        self.cfg = config.load(self.base)
        self.tz = resolve_timezone(self.cfg["time.timezone"])
        self._dataset = None
        self._pricing = "unset"
        self.warnings: List[str] = []

    def log(self, level: str, message: str) -> None:
        if LOG_LEVELS[level] <= LOG_LEVELS[self.cfg["logging.level"]]:
            sys.stderr.write("[boring-meter %s] %s\n" % (level, message))

    @property
    def dataset(self) -> adapters.Dataset:
        if self._dataset is None:
            started = time.monotonic()
            self._dataset = adapters.load_dataset(self.cfg, self.base)
            self.log("debug", "loaded %d records in %.2fs" % (len(self._dataset.records), time.monotonic() - started))
            if self._dataset.cache_note:
                self.log("warning", self._dataset.cache_note)
        return self._dataset

    @property
    def pricing(self):
        if self._pricing == "unset":
            try:
                self._pricing = load_pricing(self.cfg)
            except BMError as exc:
                self.warnings.append("Cost estimates unavailable: %s" % exc.message)
                self._pricing = None
        return self._pricing

    def period(self):
        a = self.args
        return resolve_period(
            today=getattr(a, "today", False), week=getattr(a, "week", False), days=getattr(a, "days", None),
            since=getattr(a, "since", None), until=getattr(a, "until", None), all_time=getattr(a, "all", False),
            default_days=self.cfg["report.default_days"], tz=self.tz,
        )


def emit_json(obj) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, sort_keys=False, default=str, ensure_ascii=False) + "\n")


def emit(lines: List[str]) -> None:
    sys.stdout.write("\n".join(lines).rstrip() + "\n")


def _project_arg(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise BMError("INVALID_ARGUMENT", "Project directory %s does not exist." % display_path(path))
    return os.path.realpath(str(path))


def _sources_ok(ds: adapters.Dataset) -> bool:
    return any(s.source_id == adapters.TRANSCRIPT_SOURCE and s.status == "ok" for s in ds.sources)


# ------------------------------------------------------------------ sources


def sources_payload(ctx: Context) -> dict:
    ds = ctx.dataset
    return {
        "sources": [s.to_dict() for s in ds.sources],
        "adapters": [adapters.TRANSCRIPT_SOURCE_INFO, adapters.HOOK_SOURCE_INFO],
        "transcript_files_parsed": len(ds.files),
        "requests_found": len(ds.records),
        "duplicates_removed": ds.duplicates_removed,
        "malformed_lines": ds.malformed_lines,
        "truncated_files": ds.truncated_files,
        "unsupported_files": ds.unsupported_files,
        "skipped_files": [{"path": display_path(p), "reason": r} for p, r in ds.skipped_files],
        "unavailable_metrics": [
            "Billed cost (transcripts contain no cost; estimates use list prices)",
            "Subscription plan limits or remaining allowance",
            "Usage from claude.ai, the desktop chat, or other machines",
        ],
    }


def cmd_sources(ctx: Context) -> int:
    payload = sources_payload(ctx)
    if ctx.args.json:
        emit_json(payload)
        return 0
    lines = banner("Data Sources")
    for s in payload["sources"]:
        lines += kv(s["source_id"], "%s, %s" % (s["status"], s["location"]))
        if s["files"]:
            lines += kv("  files", "%s (%s MB)" % (num(s["files"]), round(s["bytes"] / 1048576, 1)))
        if s["note"]:
            lines += kv("  note", s["note"])
    lines += [""] + kv("Requests found", num(payload["requests_found"]))
    lines += kv("Duplicates merged", num(payload["duplicates_removed"]))
    lines += kv("Malformed lines", num(payload["malformed_lines"]))
    lines += kv("Truncated files", num(payload["truncated_files"]))
    lines += kv("Non-transcript files", "%s (ignored)" % num(payload["unsupported_files"]))
    if payload["skipped_files"]:
        lines += kv("Skipped files", num(len(payload["skipped_files"])))
        for item in payload["skipped_files"][:5]:
            lines += bullet("%s: %s" % (item["path"], item["reason"]))
    lines += [""] + heading("Metrics available from transcripts")
    for field in adapters.TRANSCRIPT_SOURCE_INFO["supported_fields"]:
        lines += bullet(field)
    lines += [""] + heading("Not available")
    for item in payload["unavailable_metrics"]:
        lines += bullet(item)
    emit(lines)
    return 0


# ------------------------------------------------------------------ usage


def _empty_state(ctx: Context, summary: Optional[dict]) -> List[str]:
    ds = ctx.dataset
    lines = []
    if not ctx.cfg["sources.claude_transcripts"]:
        lines += para("No usage source is enabled. Transcript reading is turned off in settings.")
        lines += para("Enable it with: boring-meter settings set sources.claude_transcripts true")
    elif not _sources_ok(ds):
        lines += para("No readable Claude Code transcripts were found.")
        for s in ds.sources:
            if s.source_id == adapters.TRANSCRIPT_SOURCE:
                lines += bullet(("%s: %s %s" % (s.location, s.status, s.note)).rstrip())
        lines += [""] + para(
            "Claude Code writes transcripts to CLAUDE_CONFIG_DIR/projects (default ~/.claude/projects). If yours are "
            "elsewhere, add the folder with: boring-meter settings set sources.extra_transcript_dirs /path/to/dir"
        )
        lines += para("Instruction analysis still works: run /boring-meter:analyze --project .")
    elif not ds.records:
        lines += para("Transcripts were found, but none contain token usage records.")
        lines += para("This can happen with a new installation or an unsupported transcript format. "
                      "Run 'boring-meter sources' for details.")
    else:
        window = summary["data_window"] if summary else {}
        lines += para("No recorded requests in this period. This is not a zero-usage result: there is simply no data "
                      "for the period.")
        if window.get("earliest"):
            lines += para("Available records span %s to %s. Try --all or a wider --days value."
                          % (window["earliest"][:10], window["latest"][:10]))
    return lines


def _resolve_session(ctx: Context, raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    if raw.startswith("${") or raw == "current":
        raise BMError("INVALID_ARGUMENT", "The current session id was not substituted.",
                      "Pass an explicit id; list them with: boring-meter usage --sessions")
    matches = {r["session_id"] for r in ctx.dataset.records if r["session_id"].startswith(raw)}
    if not matches:
        raise BMError("NO_DATA", "No usage records for session '%s'." % raw,
                      "The transcript may not be written yet, or the id is wrong. List sessions with: boring-meter usage --sessions")
    if len(matches) > 1:
        raise BMError("INVALID_ARGUMENT", "Session prefix '%s' matches %d sessions; use more characters." % (raw, len(matches)))
    return matches.pop()


def cmd_usage(ctx: Context) -> int:
    a = ctx.args
    if a.source:
        return cmd_sources(ctx)
    if a.sessions:
        return cmd_sessions(ctx)
    session = _resolve_session(ctx, a.session)
    period = ctx.period()
    project = _project_arg(a.project)
    summary = aggregate.summarize(ctx.dataset, period, ctx.tz, ctx.pricing, session_id=session, project=project)
    top = None
    if summary["requests"] and not a.no_findings:
        found = rules.run_rules(_rule_context(ctx, period, project, session, with_instructions=False), limit=1)
        top = found[0] if found else None
    if a.json:
        summary["top_finding"] = top
        summary["warnings"] = ctx.warnings
        emit_json(summary)
        return 0
    lines = banner("Usage Overview")
    lines += kv("Period", "Session %s" % session if session else summary["period"]["label"])
    lines += kv("Source", "Local Claude Code session transcripts (observed values)")
    if project:
        lines += kv("Project", display_path(project))
    lines += kv("Coverage", summary["coverage"].capitalize())
    if not summary["requests"]:
        emit(lines + [""] + _empty_state(ctx, summary))
        return 0
    for note in summary["coverage_notes"]:
        lines += bullet(note, indent=23)
    lines.append("")
    t = summary["totals"]
    lines += kv("Requests", num(summary["requests"]))
    lines += kv("Sessions", "%s (%s with incomplete data)" % (num(summary["sessions"]), num(summary["sessions_with_incomplete_data"])))
    lines += kv("Input tokens", token_value(t["input_tokens"]))
    lines += kv("Output tokens", token_value(t["output_tokens"]))
    lines += kv("Cache read tokens", token_value(t["cache_read_tokens"]))
    lines += kv("Cache write tokens", token_value(t["cache_creation_tokens"]))
    comb = summary["combined_tokens"]
    total = num(comb["sum"]) if comb["records_included"] else "unknown"
    if comb["records_excluded"]:
        total += " (excludes %s incomplete request(s))" % num(comb["records_excluded"])
    lines += kv("Total tokens", total)
    lines += ["", ] + heading("By model")
    for model, group in list(summary["by_model"].items())[:6]:
        tot = group["totals"]
        known = all(tot[k]["missing"] == 0 for k in tot)
        size = num(sum(tot[k]["sum"] for k in tot)) + " tokens" if known else "incomplete data"
        lines.append("  %-26s %8s req  %s" % (model[:26], num(group["requests"]), size))
    if 1 < len(summary["by_day"]) <= 14:
        lines += [""] + heading("By day")
        for day, group in summary["by_day"].items():
            tot = group["totals"]
            known = all(tot[k]["missing"] == 0 for k in tot)
            size = num(sum(tot[k]["sum"] for k in tot)) + " tokens" if known else "incomplete data"
            lines.append("  %s  %8s req  %s" % (day, num(group["requests"]), size))
    if len(summary["by_project"]) > 1 and not project:
        lines += [""] + heading("Top projects")
        for item in summary["by_project"][:5]:
            shown = display_path(item["project"])
            shown = shown if len(shown) <= 40 else "..." + shown[-37:]
            lines.append("  %-40s %6s req" % (shown, num(item["requests"])))
    lines += [""] + _cost_lines(summary["cost"])
    lines += [""] + para("Note: " + summary["subscription_note"])
    if top:
        lines += [""] + heading("Top opportunity")
        lines += para("%s (confidence: %s)" % (top["title"], top["confidence"]), indent=2)
        lines += para(top["observed"], indent=2)
        lines += ["", "Run /boring-meter:analyze for details."]
    for w in ctx.warnings:
        lines += [""] + para("Warning: " + w)
    emit(lines)
    return 0


def _cost_lines(cost: dict) -> List[str]:
    if not cost.get("available"):
        reason = cost.get("reason")
        if not reason and cost.get("unpriced_reasons"):
            reason = "No request could be priced: %s." % ", ".join(
                "%s (%d)" % (k, v) for k, v in list(cost["unpriced_reasons"].items())[:3])
        return kv("API cost estimate", "Not available") + para(reason or "No priced requests.", indent=2)
    lines = kv("API cost estimate", "%s%s" % (money(cost["amount"], cost["currency"]), "" if cost["complete"] else " (partial)"))
    lines += para("List-price estimate (pricing %s). Not what a Claude subscription charges; excludes discounts, "
                  "credits, taxes and tool fees." % cost["pricing_version"], indent=2)
    if cost["records_unpriced"]:
        reasons = ", ".join("%s: %d" % (k, v) for k, v in list(cost["unpriced_reasons"].items())[:3])
        lines += para("%s request(s) not priced and not included (%s)." % (num(cost["records_unpriced"]), reasons), indent=2)
    return lines


def cmd_sessions(ctx: Context) -> int:
    period = ctx.period()
    records = aggregate.filter_records(ctx.dataset, period)
    groups = {}
    for r in records:
        if r.get("synthetic"):
            continue
        g = groups.setdefault(r["session_id"], {"session_id": r["session_id"], "project": r["project_id"], "requests": 0,
                                                "first": r["ts_epoch"], "last": r["ts_epoch"], "tokens": 0, "complete": True})
        g["requests"] += 1
        g["last"] = r["ts_epoch"] or g["last"]
        if r["data_quality"] == "complete":
            g["tokens"] += r["input_tokens"] + r["output_tokens"] + r["cache_read_tokens"] + r["cache_creation_tokens"]
        else:
            g["complete"] = False
    items = sorted(groups.values(), key=lambda g: -(g["last"] or 0))
    if ctx.args.json:
        emit_json({"period": period.to_dict(), "sessions": items})
        return 0
    lines = banner("Sessions") + kv("Period", period.label) + [""]
    if not items:
        emit(lines + _empty_state(ctx, None))
        return 0
    for g in items[:30]:
        when = datetime.fromtimestamp(g["last"], timezone.utc).astimezone(ctx.tz).strftime("%Y-%m-%d %H:%M") if g["last"] else "?"
        size = num(g["tokens"]) + " tokens" if g["complete"] else "incomplete"
        lines.append("%s  %s  %5s req  %s" % (g["session_id"][:8], when, num(g["requests"]), size))
        lines.append("          %s" % display_path(g["project"] or "(unknown project)"))
    if len(items) > 30:
        lines.append("... %d more (use --json for all)" % (len(items) - 30))
    emit(lines)
    return 0


# ------------------------------------------------------------------ analyze


def _rule_context(ctx: Context, period, project, session, with_instructions=True, instructions_root=None) -> dict:
    records = aggregate.filter_records(ctx.dataset, period, session_id=session, project=project)
    session_ids = {r["session_id"] for r in records}
    sessions = [s for s in ctx.dataset.sessions if s["session_id"] in session_ids]
    analysis = None
    if with_instructions:
        root = instructions_root or project or os.getcwd()
        analysis = instructions.analyze(Path(root))
    loads = None
    if analysis is not None and ctx.cfg["collection.instruction_events"]:
        events = adapters.load_instruction_events(ctx.base)
        paths = {f.path for f in analysis["launch_files"]}
        loads = sum(1 for e in events if e.get("file_path") in paths and period.contains(parse_ts(e.get("ts"))))
    return {
        "cfg": ctx.cfg, "records": records, "sessions": sessions, "instructions": analysis, "pricing": ctx.pricing,
        "instruction_loads": loads, "scope_key": "%s|%s|%s" % (period.kind, project or "*", session or "*"),
    }


def render_finding(f: dict, index: int) -> List[str]:
    lines = ["%d. %s" % (index, f["title"])]
    lines += kv("   Confidence", "%s   Severity: %s   Effort: %s   Risk: %s" % (f["confidence"], f["severity"], f["effort"], f["risk"]), 14)
    s = f["scores"]
    lines += kv("   Priority", "%d (confidence %d, benefit %d, effort %d, risk %d)" % (
        s["priority"], s["confidence"], s["benefit"], s["effort"], s["risk"]), 14)
    lines += ["   What was observed:"] + para(f["observed"], indent=5)
    lines += ["   Evidence:"]
    for e in f["evidence"]:
        lines += bullet(e, indent=5)
    lines += ["   Why it matters:"] + para(f["why_it_matters"], indent=5)
    lines += ["   Recommended action:"] + para(f["recommended_action"], indent=5)
    lines += ["   Impact category: %s (savings not estimated)" % f["impact_type"]]
    lines += ["   How to verify:"] + para(f["verification_method"], indent=5)
    lines += ["   Limitations:"]
    for lim in f["limitations"]:
        lines += bullet(lim, indent=5)
    lines += ["   Finding id: %s (rule %s v%d)" % (f["finding_id"], f["rule_id"], f["rule_version"]), ""]
    return lines


def cmd_analyze(ctx: Context) -> int:
    a = ctx.args
    if a.rules:
        catalog = rules.rule_catalog()
        if a.json:
            emit_json(catalog)
        else:
            lines = banner("Rule Catalog")
            for r in catalog:
                lines += ["%s (v%d): %s" % (r["rule_id"], r["version"], r["name"])] + para(r["description"], indent=2)
                lines += para("Exclusions: " + r["exclusions"], indent=2) + [""]
            emit(lines)
        return 0
    period = ctx.period()
    project = _project_arg(a.project)
    session = _resolve_session(ctx, a.session)
    rctx = _rule_context(ctx, period, project, session, with_instructions=not a.no_instructions)
    limit = a.limit or ctx.cfg["report.max_findings"]
    all_findings = rules.run_rules(rctx)
    findings = all_findings[:limit]
    payload = {
        "period": period.to_dict(),
        "project": project,
        "session": session,
        "instruction_root": rctx["instructions"]["project_root"] if rctx["instructions"] else None,
        "requests_analyzed": len(rctx["records"]),
        "sessions_analyzed": len(rctx["sessions"]),
        "findings_total": len(all_findings),
        "findings": findings,
        "scoring": "priority = 3*confidence + 2*benefit - effort - risk (1 to 3 each); ordering only, not a savings estimate",
        "files_modified": [],
    }
    if a.json:
        emit_json(payload)
        return 0
    lines = banner("Analysis")
    lines += kv("Period", "Session %s" % session if session else period.label)
    lines += kv("Transcript data", "%s request(s) in %s session(s)" % (num(payload["requests_analyzed"]), num(payload["sessions_analyzed"])))
    if payload["instruction_root"]:
        lines += kv("Instructions from", display_path(payload["instruction_root"]))
    lines += kv("Findings", "%d shown of %d, highest priority first" % (len(findings), len(all_findings)))
    lines.append("")
    if not findings:
        lines += para("No findings. None of the %d rules found evidence that meets its threshold in this data. "
                      "This does not prove there is no avoidable overhead; it means none was detectable." % len(rules.RULES))
        if not payload["requests_analyzed"]:
            lines += [""] + para("No transcript requests were in scope, so only instruction files were checked.")
    for i, f in enumerate(findings, 1):
        lines += render_finding(f, i)
    lines += para("No files were modified. Run /boring-meter:optimize for reviewable instruction changes.")
    emit(lines)
    return 0


# ------------------------------------------------------------------ optimize


def cmd_optimize(ctx: Context) -> int:
    a = ctx.args
    if a.action == "show":
        rec = optimize.show(ctx.base, _need_id(a))
        if a.json:
            emit_json(rec)
        else:
            lines = banner("Proposal %s" % rec["proposal_id"]) + kv("Target", display_path(rec["target"]))
            lines += kv("Status", "applied %s" % rec["applied"] if rec.get("applied") else "not applied")
            lines += kv("Benefit", rec["expected_benefit"]) + kv("Risk", rec["risk"]) + ["", rec["diff"]]
            emit(lines)
        return 0
    if a.action == "apply":
        result = optimize.apply(ctx.base, _need_id(a), confirmed=a.confirm)
        if a.json:
            emit_json(result)
        else:
            emit(banner("Proposal applied") + kv("File", result["target"]) + kv("Removed lines", ", ".join(map(str, result["removed_lines"])))
                 + kv("Backup", result["backup"]) + kv("Verified", "yes, file content matches the proposal"))
        return 0
    if a.action == "save":
        if not a.output:
            raise BMError("INVALID_ARGUMENT", "optimize save needs --output PATH.")
        dest = optimize.save_copy(ctx.base, _need_id(a), a.output, force=a.force)
        if a.json:
            emit_json({"saved": str(dest)})
        else:
            emit(["Proposed content saved to %s. The original file was not changed." % display_path(dest)])
        return 0
    root = _project_arg(a.project) or os.getcwd()
    analysis = instructions.analyze(Path(root))
    result = optimize.build(analysis, ctx.base)
    files = [f.to_dict() for f in analysis["files"]]
    if a.json:
        emit_json({"project_root": analysis["project_root"], "instruction_files": files,
                   "launch_chars": analysis["launch_chars"], "proposals": result["proposals"],
                   "advisory": result["advisory"], "skipped": analysis["skipped"], "files_modified": []})
        return 0
    lines = banner("Instruction Optimization") + kv("Project", display_path(analysis["project_root"]))
    lines += kv("Always loaded", "%s characters in %d file(s), about %s tokens (estimate)" % (
        num(analysis["launch_chars"]), len(analysis["launch_files"]), num(analysis["launch_estimated_tokens"])))
    lines += [""] + heading("Instruction files")
    if not files:
        lines += para("No instruction files were found for this project.", indent=2)
    for f in files:
        shown = f["path"] if len(f["path"]) <= 44 else "..." + f["path"][-41:]
        lines.append("  %-44s %6s lines  %s" % (shown, num(f["lines"]), f["loaded"]))
    for s in analysis["skipped"]:
        lines += bullet("Skipped: " + s)
    if not analysis["nested_scan_complete"]:
        lines += bullet("The subdirectory scan stopped early (large repository); nested files may be missing.")
    lines += [""] + heading("Proposed changes")
    if not result["proposals"]:
        lines += para("None. No word-for-word repeated lines were found within a single file.", indent=2)
    for p in result["proposals"]:
        lines += ["Proposal %s: %s" % (p["proposal_id"], display_path(p["target"]))]
        lines += para(p["expected_benefit"], indent=2) + para("Risk: " + p["risk"], indent=2) + ["", p["diff"]]
        lines += para("Nothing has been changed. To apply after review: boring-meter optimize apply %s --confirm" % p["proposal_id"])
        lines += para("To save a copy instead: boring-meter optimize save %s --output PATH" % p["proposal_id"]) + [""]
    if result["advisory"]:
        lines += heading("Suggestions to apply yourself")
        for item in result["advisory"]:
            lines += bullet(item)
    emit(lines)
    return 0


def _need_id(a) -> str:
    if not a.id:
        raise BMError("INVALID_ARGUMENT", "This action needs a proposal id.")
    return a.id


# ------------------------------------------------------------------ report


def build_report(ctx: Context) -> dict:
    period = ctx.period()
    project = _project_arg(ctx.args.project)
    summary = aggregate.summarize(ctx.dataset, period, ctx.tz, ctx.pricing, project=project)
    rctx = _rule_context(ctx, period, project, None, with_instructions=True)
    findings = rules.run_rules(rctx, limit=ctx.cfg["report.max_findings"])
    exps = []
    for exp in experiments.list_all(ctx.base):
        comparison = experiments.compare(exp)
        exps.append({"experiment_id": exp["experiment_id"], "name": exp["name"], "optimization": exp["optimization"],
                     "classification": comparison["classification"], "comparison": comparison})
    return {
        "generated": datetime.now(timezone.utc).astimezone(ctx.tz).isoformat(timespec="seconds"),
        "boring_meter_version": __version__,
        "summary": summary,
        "findings": findings,
        "experiments": {
            "verified": [e for e in exps if e["classification"] == "verified"],
            "unverified": [e for e in exps if e["classification"] != "verified"],
        },
        "sources": [s.to_dict() for s in ctx.dataset.sources],
        "warnings": ctx.warnings,
    }


def report_markdown(rep: dict) -> str:
    s = rep["summary"]
    out = ["# Boring Meter Report", "", "Generated: %s" % rep["generated"], ""]
    out += ["## Period and data completeness", "", "- Period: %s" % s["period"]["label"],
            "- Source: local Claude Code session transcripts (observed values)", "- Coverage: %s" % s["coverage"]]
    out += ["- %s" % n for n in s["coverage_notes"]] + ["- %s" % s["retention_note"], ""]
    out += ["## Observed usage", ""]
    if not s["requests"]:
        out += ["No recorded requests in this period. This is missing data, not zero usage.", ""]
    else:
        t = s["totals"]
        out += ["| Metric | Value |", "| --- | --- |",
                "| Requests | %s |" % num(s["requests"]), "| Sessions | %s |" % num(s["sessions"]),
                "| Input tokens | %s |" % token_value(t["input_tokens"]), "| Output tokens | %s |" % token_value(t["output_tokens"]),
                "| Cache read tokens | %s |" % token_value(t["cache_read_tokens"]),
                "| Cache write tokens | %s |" % token_value(t["cache_creation_tokens"]),
                "| Total tokens (complete requests) | %s |" % num(s["combined_tokens"]["sum"]), ""]
        out += ["| Model | Requests |", "| --- | --- |"] + ["| %s | %s |" % (m, num(g["requests"])) for m, g in s["by_model"].items()] + [""]
    out += ["## API cost estimate", ""]
    c = s["cost"]
    if c.get("available"):
        out += ["- Estimate: %s%s" % (money(c["amount"], c["currency"]), "" if c["complete"] else " (partial: %d request(s) unpriced)" % c["records_unpriced"]),
                "- Pricing version: %s (effective %s)" % (c["pricing_version"], c["pricing_effective_date"])]
        out += ["- Assumption: %s" % x for x in c["assumptions"]] + [""]
    else:
        out += ["Not available: %s" % (c.get("reason") or "no request could be priced."), ""]
    out += ["> %s" % s["subscription_note"], "", "## Top findings", ""]
    if not rep["findings"]:
        out += ["No findings met their evidence thresholds.", ""]
    for i, f in enumerate(rep["findings"], 1):
        out += ["### %d. %s" % (i, f["title"]), "", "- Confidence: %s; severity: %s; effort: %s; risk: %s; priority %d"
                % (f["confidence"], f["severity"], f["effort"], f["risk"], f["scores"]["priority"]),
                "- Observed: %s" % f["observed"]]
        out += ["- Evidence: %s" % e for e in f["evidence"]]
        out += ["- Recommended action: %s" % f["recommended_action"], "- Verify: %s" % f["verification_method"],
                "- Limitations: %s" % " ".join(f["limitations"]), ""]
    out += ["## Optimization outcomes", "", "### Verified", ""]
    if not rep["experiments"]["verified"]:
        out += ["None yet.", ""]
    for e in rep["experiments"]["verified"]:
        d = e["comparison"]["differences"]["total_tokens"]
        out += ["- %s (%s): total tokens %s%% per run, quality %s" % (e["name"], e["experiment_id"], d["percent"], e["comparison"]["quality"])]
    out += ["", "### Not verified (directional, inconclusive, or invalid)", ""]
    if not rep["experiments"]["unverified"]:
        out += ["None.", ""]
    for e in rep["experiments"]["unverified"]:
        out += ["- %s (%s): %s. %s" % (e["name"], e["experiment_id"], e["classification"],
                                         " ".join(e["comparison"].get("classification_reasons") or e["comparison"]["invalid_reasons"]))]
    out += ["", "## Data sources", ""] + ["- %s: %s (%s)" % (x["source_id"], x["status"], x["location"]) for x in rep["sources"]]
    return "\n".join(out).rstrip() + "\n"


def cmd_report(ctx: Context) -> int:
    a = ctx.args
    rep = build_report(ctx)
    fmt = a.format
    text = json.dumps(rep, indent=2, default=str, ensure_ascii=False) + "\n" if fmt == "json" else report_markdown(rep)
    if a.output or a.save:
        if a.output:
            dest = validate_output_path(a.output, force=a.force)
        else:
            folder = ensure_private_dir(ctx.base / "exports")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            dest = validate_output_path(str(folder / ("report-%s.%s" % (stamp, "json" if fmt == "json" else "md"))), force=False)
        atomic_write_text(dest, text, mode=0o600)
        emit(["Report written to %s" % display_path(dest)])
        return 0
    sys.stdout.write(text)
    return 0


# ------------------------------------------------------------------ experiment


def _window_records(ctx: Context, a):
    project = _project_arg(getattr(a, "project", None))
    if a.session:
        session = _resolve_session(ctx, a.session)
        records = [r for r in ctx.dataset.records if r["session_id"] == session]
        if project:
            records = [r for r in records if aggregate._in_project(r["project_id"], project)]
        return records, "session %s" % session
    if not (a.start and a.end):
        raise BMError("INVALID_ARGUMENT", "Pass --session ID, or both --from and --to timestamps.")
    start, end = _parse_moment(a.start, ctx.tz, "--from"), _parse_moment(a.end, ctx.tz, "--to")
    if end <= start:
        raise BMError("INVALID_ARGUMENT", "--to must be after --from.")
    records = [r for r in ctx.dataset.records if r["ts_epoch"] is not None and start.timestamp() <= r["ts_epoch"] < end.timestamp()
               and (not project or aggregate._in_project(r["project_id"], project))]
    return records, "window %s to %s" % (start.isoformat(), end.isoformat())


def _parse_moment(text: str, tz, flag: str) -> datetime:
    parsed = parse_ts(text)
    if parsed:
        return parsed
    try:
        naive = datetime.fromisoformat(text)
    except ValueError:
        raise BMError("INVALID_ARGUMENT", "%s expects a time like 2026-10-28T14:00, got '%s'." % (flag, text))
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


def cmd_experiment(ctx: Context) -> int:
    a = ctx.args
    act = a.exp_action
    if act == "start":
        exp = experiments.start(ctx.base, a.name, a.change, a.task_type or "", _project_arg(a.project) or "", a.notes or "")
        if a.json:
            emit_json(exp)
        else:
            emit(banner("Experiment started") + kv("Id", exp["experiment_id"]) + kv("Testing", exp["optimization"]) + [""]
                 + para("Next: run the task once as it is now, then record it with: boring-meter experiment baseline %s "
                        "--session <session id>. Apply the change, repeat an equivalent task, and record it with "
                        "'experiment followup'. Two or more runs on each side are needed for a verified result." % exp["experiment_id"]))
        return 0
    if act in ("baseline", "followup"):
        records, label = _window_records(ctx, a)
        run = experiments.measure(records, label, ctx.pricing)
        exp = experiments.add_run(ctx.base, a.id, act, run)
        if a.json:
            emit_json(run)
        else:
            lines = banner("%s recorded" % act.capitalize()) + kv("Experiment", exp["experiment_id"]) + kv("Run", label)
            lines += kv("Requests", num(run["requests"])) + kv("Models", ", ".join(run["models"]) or "unknown")
            lines += kv("Total tokens", num(run["total_tokens"]) if run["total_tokens"] is not None else "incomplete data")
            if not run["complete"]:
                lines += para("Some token categories are missing, so this run cannot be used for a valid comparison.")
            emit(lines)
        return 0
    if act == "outcome":
        exp = experiments.set_outcome(ctx.base, a.id, a.quality, a.side, a.completed)
        if a.json:
            emit_json(exp)
        else:
            emit(["Recorded for %s: quality %s; task completed (baseline %s, follow-up %s)." % (
                exp["experiment_id"], exp["quality"], exp["task_completed"]["baseline"], exp["task_completed"]["followup"])])
        return 0
    if act == "list":
        items = experiments.list_all(ctx.base)
        rows = [{"experiment_id": e["experiment_id"], "name": e["name"], "baseline_runs": len(e["baseline"]),
                 "followup_runs": len(e["followup"]), "classification": experiments.compare(e)["classification"]} for e in items]
        if a.json:
            emit_json(rows)
        else:
            lines = banner("Experiments")
            if not rows:
                lines += para("No experiments yet. Start one with: boring-meter experiment start --name NAME --change \"what you changed\"")
            for r in rows:
                lines.append("%-30s %-12s baseline %d, follow-up %d  %s" % (r["experiment_id"], r["classification"], r["baseline_runs"], r["followup_runs"], r["name"][:30]))
            emit(lines)
        return 0
    if act == "show":
        exp = experiments.get(ctx.base, _need_id(a))
        comparison = experiments.compare(exp)
        if a.json:
            emit_json({"experiment": exp, "comparison": comparison})
            return 0
        lines = banner("Experiment %s" % exp["experiment_id"]) + kv("Name", exp["name"]) + kv("Change tested", exp["optimization"])
        if exp["task_type"]:
            lines += kv("Task type", exp["task_type"])
        lines += kv("Runs", "baseline %d, follow-up %d" % (len(exp["baseline"]), len(exp["followup"])))
        lines += kv("Quality", exp["quality"]) + kv("Result", comparison["classification"].upper())
        for reason in comparison["invalid_reasons"] + comparison.get("classification_reasons", []):
            lines += bullet(reason)
        if comparison["differences"]:
            lines += [""] + heading("Mean per run (follow-up minus baseline)")
            names = {"input_tokens": "Input", "output_tokens": "Output", "cache_read_tokens": "Cache read",
                     "cache_creation_tokens": "Cache write", "total_tokens": "Total tokens"}
            for key, label in names.items():
                d = comparison["differences"][key]
                pct = "" if d["percent"] is None else " (%+.1f%%)" % d["percent"]
                lines.append("  %-13s %14s -> %-14s %+.0f%s" % (label, num(int(d["baseline_mean"])), num(int(d["followup_mean"])), d["difference"], pct))
            c = comparison["differences"].get("cost_estimate")
            lines += ["  Cost estimate %s" % ("%+.4f USD per run (%s)" % (c["difference"], c["note"]) if c else "not comparable")]
        if comparison["warnings"]:
            lines += [""] + heading("Comparability warnings")
            for w in comparison["warnings"]:
                lines += bullet(w)
        lines += [""] + heading("Limitations")
        for lim in comparison["limitations"]:
            lines += bullet(lim)
        if exp["quality"] == "unknown":
            lines += [""] + para("Quality is unknown, so these numbers do not show that quality was preserved. Record it with: "
                                 "boring-meter experiment outcome %s --quality preserved|improved|degraded --completed yes|no" % exp["experiment_id"])
        emit(lines)
        return 0
    if act == "delete":
        if not a.yes:
            raise BMError("CONFIRMATION_REQUIRED", "Deleting an experiment is permanent.", "Rerun with --yes to confirm.")
        removed = experiments.delete(ctx.base, _need_id(a))
        emit(["Deleted experiment %s from Boring Meter's data. No Claude Code data was touched." % removed])
        return 0
    raise BMError("INVALID_ARGUMENT", "Unknown experiment action.")


# ------------------------------------------------------------------ settings


def cmd_settings(ctx: Context) -> int:
    a = ctx.args
    act = a.set_action or "show"
    if act == "show":
        rows = [{"key": k, "value": ctx.cfg[k], "default": spec[1], "description": spec[2],
                 "applies": spec[3].get("reload", "Immediately, on the next command.")} for k, spec in config.SCHEMA.items()]
        if a.json:
            emit_json({"data_dir": str(ctx.base), "config_file": str(config.config_path(ctx.base)), "settings": rows,
                       "sources": [s.to_dict() for s in adapters.discover_sources(ctx.cfg, ctx.base)]})
            return 0
        lines = banner("Settings") + kv("Data directory", display_path(ctx.base)) + [""]
        for r in rows:
            mark = "" if r["value"] == r["default"] else "  (changed)"
            lines.append("%s = %s%s" % (r["key"], json.dumps(r["value"]), mark))
            lines += para(r["description"], indent=4)
        lines += [""] + para("Change a value: boring-meter settings set KEY VALUE. Settings apply on the next command; "
                             "hook collection applies to the next instruction load. Nothing requires restarting Claude Code "
                             "unless the plugin itself was just installed or updated (then run /reload-plugins).")
        emit(lines)
        return 0
    if act == "set":
        if not a.key or a.value is None:
            raise BMError("INVALID_ARGUMENT", "Usage: boring-meter settings set KEY VALUE")
        value = config.parse_cli_value(a.key, a.value)
        values = dict(ctx.cfg)
        values[a.key] = value
        config.validate({"config_version": config.CONFIG_VERSION, "values": values}, "new settings")
        config.save(values, ctx.base)
        note = config.SCHEMA[a.key][3].get("reload", "Takes effect on the next command.")
        emit(["%s = %s" % (a.key, json.dumps(value)), note])
        return 0
    if act == "reset":
        if not a.yes:
            raise BMError("CONFIRMATION_REQUIRED", "Resetting replaces all settings with defaults.", "Rerun with --yes to confirm.")
        config.save(config.defaults(), ctx.base)
        emit(["Settings reset to defaults."])
        return 0
    if act == "path":
        emit([str(ctx.base)])
        return 0
    if act == "sources":
        return cmd_sources(ctx)
    if act == "export":
        if not a.output:
            raise BMError("INVALID_ARGUMENT", "settings export needs --output PATH.")
        dest = validate_output_path(a.output, force=a.force)
        bundle = {"exported": datetime.now(timezone.utc).isoformat(), "boring_meter_version": __version__,
                  "settings": ctx.cfg, "experiments": experiments.list_all(ctx.base),
                  "instruction_events": adapters.load_instruction_events(ctx.base)}
        atomic_write_text(dest, json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", mode=0o600)
        emit(["Exported Boring Meter's own records to %s." % display_path(dest)])
        return 0
    if act == "prune":
        removed = _maintenance(ctx, force=True)
        emit(["Removed %d hook event(s) and %d saved export(s) past retention. Claude Code's own files were not touched."
              % removed])
        return 0
    if act == "delete-data":
        if not a.yes:
            raise BMError("CONFIRMATION_REQUIRED",
                          "This deletes everything in %s (Boring Meter's settings, cache, experiments, events, proposals, "
                          "backups and exports). Claude Code transcripts are never deleted." % display_path(ctx.base),
                          "Rerun with --yes to confirm.")
        if ctx.base.exists():
            if ctx.base.resolve() in (Path.home().resolve(), Path("/").resolve()):
                raise BMError("INVALID_PATH", "Refusing to delete the home or root directory.")
            shutil.rmtree(str(ctx.base))
        emit(["Deleted %s. Claude Code transcripts were not touched." % display_path(ctx.base)])
        return 0
    raise BMError("INVALID_ARGUMENT", "Unknown settings action.")


def _maintenance(ctx: Context, force: bool = False):
    """Apply retention to Boring Meter's own data at most once a day."""
    stamp = ctx.base / "cache" / "last-maintenance"
    try:
        if not force and stamp.exists() and time.time() - stamp.stat().st_mtime < 86400:
            return (0, 0)
    except OSError:
        return (0, 0)
    events = adapters.prune_events(ctx.base, ctx.cfg["retention.event_days"])
    exports = 0
    days = ctx.cfg["retention.export_days"]
    folder = ctx.base / "exports"
    if days > 0 and folder.is_dir():
        cutoff = time.time() - days * 86400
        for item in folder.glob("report-*"):
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink()
                    exports += 1
            except OSError:
                pass
    try:
        ensure_private_dir(stamp.parent)
        stamp.touch()
    except OSError:
        pass
    return (events, exports)


# ------------------------------------------------------------------ doctor


def cmd_doctor(ctx: Context) -> int:
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "status": "ok" if ok is True else ("warning" if ok is None else "problem"), "detail": detail})

    check("Python version", sys.version_info >= (3, 9), sys.version.split()[0])
    manifest = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    skills_dir = PLUGIN_ROOT / "skills"
    expected = ["usage", "analyze", "optimize", "report", "experiment", "settings"]
    missing = [s for s in expected if not (skills_dir / s / "SKILL.md").is_file()]
    check("Plugin files", manifest.is_file() and not missing,
          "manifest and %d command skills found" % len(expected) if not missing else "missing: %s" % ", ".join(missing or ["plugin.json"]))
    try:
        ensure_private_dir(ctx.base)
        probe = ctx.base / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        check("Data directory writable", True, display_path(ctx.base))
    except OSError as exc:
        check("Data directory writable", False, "%s (%s)" % (display_path(ctx.base), exc.strerror))
    try:
        load_pricing(ctx.cfg)
        check("Pricing table", True, "valid")
    except BMError as exc:
        check("Pricing table", False, exc.message)
    ds = ctx.dataset
    check("Transcript source", _sources_ok(ds), "; ".join("%s: %s" % (s.location, s.status) for s in ds.sources if s.source_id == adapters.TRANSCRIPT_SOURCE))
    versions = sorted({r["provenance"].get("claude_code_version") for r in ds.records if r["provenance"].get("claude_code_version")},
                      key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")])
    if versions:
        check("Transcript versions", True,
              "%s to %s (developed against %s)" % (versions[0], versions[-1], VERIFIED_CLAUDE_CODE))
    check("Unparseable data", None if (ds.malformed_lines or ds.truncated_files) else True,
          "%d malformed line(s), %d truncated file(s); %d non-transcript file(s) ignored" % (ds.malformed_lines, ds.truncated_files, ds.unsupported_files))
    check("Network use", True, "none: Boring Meter makes no network requests")
    if ctx.args.json:
        emit_json(checks)
    else:
        lines = banner("Doctor")
        for c in checks:
            lines += kv(c["check"], "%s: %s" % (c["status"].upper(), c["detail"]), 34)
        emit(lines)
    return 0 if all(c["status"] != "problem" for c in checks) else 1


# ------------------------------------------------------------------ parser


def _period_flags(p) -> None:
    g = p.add_argument_group("period (calendar days in your timezone)")
    g.add_argument("--today", action="store_true", help="the current calendar day")
    g.add_argument("--week", action="store_true", help="the last 7 calendar days including today")
    g.add_argument("--days", type=int, help="the last N calendar days including today")
    g.add_argument("--since", help="first day, YYYY-MM-DD")
    g.add_argument("--until", help="last day (inclusive), YYYY-MM-DD")
    g.add_argument("--all", action="store_true", help="all available records")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="boring-meter", description="Local usage intelligence for Claude Code. No network use.")
    parser.add_argument("--version", action="version", version="boring-meter %s" % __version__)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("usage", help="summarize recorded usage")
    _period_flags(p)
    p.add_argument("--session", help="one session id (or unique prefix)")
    p.add_argument("--sessions", action="store_true", help="list sessions in the period")
    p.add_argument("--project", help="only this project directory")
    p.add_argument("--source", action="store_true", help="show data sources instead")
    p.add_argument("--no-findings", action="store_true", help="skip the top opportunity")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("sources", help="show discovered data sources")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("analyze", help="find possible inefficiencies")
    _period_flags(p)
    p.add_argument("--project", help="project directory (default: current directory)")
    p.add_argument("--session", help="one session id (or unique prefix)")
    p.add_argument("--limit", type=int, help="maximum findings")
    p.add_argument("--no-instructions", action="store_true", help="skip instruction file analysis")
    p.add_argument("--rules", action="store_true", help="list the rule catalog")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("optimize", help="propose instruction file improvements")
    p.add_argument("action", nargs="?", default="propose", choices=["propose", "show", "apply", "save"])
    p.add_argument("id", nargs="?", help="proposal id for show, apply, save")
    p.add_argument("--project", help="project directory (default: current directory)")
    p.add_argument("--confirm", action="store_true", help="confirm applying a reviewed proposal")
    p.add_argument("--output", help="destination file for save")
    p.add_argument("--force", action="store_true", help="allow replacing an existing output file")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("report", help="produce a full report")
    _period_flags(p)
    p.add_argument("--project", help="only this project directory")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.add_argument("--save", action="store_true", help="save under the data directory's exports folder")
    p.add_argument("--output", help="write to this file")
    p.add_argument("--force", action="store_true", help="allow replacing an existing output file")
    p.add_argument("--json", action="store_true", help="same as --format json")

    p = sub.add_parser("experiment", help="before-and-after experiments")
    p.add_argument("exp_action", choices=["start", "baseline", "followup", "outcome", "list", "show", "delete"])
    p.add_argument("id", nargs="?", help="experiment id")
    p.add_argument("--name")
    p.add_argument("--change", help="the optimization being tested")
    p.add_argument("--task-type")
    p.add_argument("--notes")
    p.add_argument("--project")
    p.add_argument("--session", help="session id to record as a run")
    p.add_argument("--from", dest="start", help="run window start, ISO time")
    p.add_argument("--to", dest="end", help="run window end, ISO time")
    p.add_argument("--quality", choices=list(experiments.QUALITY))
    p.add_argument("--completed", choices=list(experiments.COMPLETION))
    p.add_argument("--side", choices=["baseline", "followup"], default="followup")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("settings", help="inspect and change local settings")
    p.add_argument("set_action", nargs="?", default="show",
                   choices=["show", "set", "reset", "path", "sources", "export", "prune", "delete-data"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--output")
    p.add_argument("--force", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("doctor", help="check installation and data access")
    p.add_argument("--json", action="store_true")
    return parser


COMMANDS = {
    "usage": cmd_usage, "sources": cmd_sources, "analyze": cmd_analyze, "optimize": cmd_optimize, "report": cmd_report,
    "experiment": cmd_experiment, "settings": cmd_settings, "doctor": cmd_doctor,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "report" and getattr(args, "json", False):
        args.format = "json"
    try:
        ctx = Context(args)
        if args.command not in ("settings", "doctor"):
            try:
                _maintenance(ctx)
            except BMError as exc:
                ctx.log("warning", "retention cleanup skipped: %s" % exc.message)
        return COMMANDS[args.command](ctx)
    except BMError as exc:
        if getattr(args, "json", False):
            emit_json({"error": exc.to_dict()})
        else:
            sys.stderr.write(exc.render() + "\n")
        return exc.exit_code
    except KeyboardInterrupt:
        sys.stderr.write("Boring Meter: interrupted. No partial files were written.\n")
        return 130
    except Exception as exc:  # pragma: no cover - last-resort guard
        if os.environ.get("BORING_METER_DEBUG"):
            raise
        sys.stderr.write(
            "Boring Meter internal error (%s). Rerun with BORING_METER_DEBUG=1 for details.\n" % exc.__class__.__name__
        )
        return 1
