"""Deterministic, versioned optimization rules.

Priority score (documented in docs/rules.md):
    priority = 3 * confidence + 2 * benefit - effort - risk
with each component on a 1 (low) to 3 (high) scale. Confidence carries the largest
weight, so a high-confidence finding with low benefit (9 + 2 - 1 - 1 = 9) always
outranks a low-confidence finding with high benefit (3 + 6 - 1 - 1 = 7) when effort
and risk are equal. The score orders findings; it is not a savings percentage.
"""

from __future__ import annotations

import hashlib
import statistics
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from boring_meter.paths import display_path
from boring_meter.pricing import list_price_ratio, resolve_model

LEVEL = {"low": 1, "medium": 2, "high": 3}


def _fmt(n) -> str:
    return "{:,}".format(n) if isinstance(n, int) else str(n)


def _day(epoch: Optional[float]) -> str:
    if epoch is None:
        return "unknown date"
    return datetime.fromtimestamp(epoch, timezone.utc).astimezone().strftime("%Y-%m-%d")


def _short(session_id: str) -> str:
    return session_id[:8]


def score(benefit: str, confidence: str, effort: str, risk: str) -> dict:
    parts = {"benefit": LEVEL[benefit], "confidence": LEVEL[confidence], "effort": LEVEL[effort], "risk": LEVEL[risk]}
    parts["priority"] = 3 * parts["confidence"] + 2 * parts["benefit"] - parts["effort"] - parts["risk"]
    parts["formula"] = "3*confidence + 2*benefit - effort - risk (each 1 to 3)"
    return parts


def finding_id(rule_id: str, scope_key: str) -> str:
    return "%s-%s" % (rule_id.split("-")[0], hashlib.sha256(("%s|%s" % (rule_id, scope_key)).encode()).hexdigest()[:10])


def make_finding(rule: dict, scope_key: str, *, title, observed, why, action, severity, confidence, benefit, effort, risk,
                 evidence, source_ids, limitations, sessions=None) -> dict:
    return {
        "finding_id": finding_id(rule["rule_id"], scope_key),
        "rule_id": rule["rule_id"],
        "rule_version": rule["version"],
        "title": title,
        "observed": observed,
        "why_it_matters": why,
        "evidence": evidence,
        "source_ids": source_ids,
        "sessions": sessions or [],
        "severity": severity,
        "confidence": confidence,
        "effort": effort,
        "risk": risk,
        "impact_type": rule["impact_type"],
        "estimated_savings": None,
        "estimated_savings_note": "Not estimated. Measure with /boring-meter:experiment before and after the change.",
        "recommended_action": action,
        "verification_method": rule["verification"],
        "limitations": rule["limitations"] + list(limitations),
        "scores": score(benefit, confidence, effort, risk),
    }


def _rel(path: str, cwds: List[str], full: bool) -> str:
    if not full:
        for cwd in cwds:
            prefix = cwd.rstrip("/") + "/"
            if path.startswith(prefix):
                return path[len(prefix):]
    return display_path(path)


# ---------------------------------------------------------------- rule 1


def rule_instructions(ctx: dict, rule: dict) -> List[dict]:
    analysis = ctx.get("instructions")
    if not analysis:
        return []
    cfg = ctx["cfg"]
    line_limit = cfg["thresholds.instruction_lines"]
    char_limit = cfg["thresholds.instruction_chars"]
    launch = analysis["launch_files"]
    long_files = [f for f in launch if f.lines > line_limit and f.scope != "auto-memory"]
    over_total = analysis["launch_chars"] > char_limit
    within = analysis["duplicates"]["within_file"]
    across = analysis["duplicates"]["across_files"]
    blocks = analysis["large_code_blocks"]
    findings = []
    root = analysis["project_root"]
    if long_files or over_total:
        evidence = ["Always-loaded instruction text: %s characters across %d file(s), about %s tokens (estimate: characters / 4)."
                    % (_fmt(analysis["launch_chars"]), len(launch), _fmt(analysis["launch_estimated_tokens"]))]
        for f in sorted(launch, key=lambda x: -x.chars)[:5]:
            evidence.append("%s: %s lines, %s characters (%s)." % (display_path(f.path), _fmt(f.lines), _fmt(f.chars), f.scope))
        if blocks:
            evidence.append("%d code block(s) of %d+ lines are loaded every session, for example %s line %d (%d lines)."
                            % (len(blocks), 25, display_path(blocks[0]["path"]), blocks[0]["start_line"], blocks[0]["lines"]))
        if within or across:
            evidence.append("%d instruction line(s) are repeated word for word." % (len(within) + len(across)))
        events = ctx.get("instruction_loads")
        if events:
            evidence.append("Recorded instruction loads in this period: %d (from the opt-in hook)." % events)
        big = len(long_files) > 0 and analysis["launch_chars"] > char_limit
        findings.append(make_finding(
            rule, "size|" + root,
            title="Large always-loaded project instructions",
            observed="%d instruction file(s) over %d lines%s." % (
                len(long_files), line_limit,
                ", and %s characters load at every session start (threshold %s)" % (_fmt(analysis["launch_chars"]), _fmt(char_limit)) if over_total else ""),
            why="Instruction files load into context at the start of every session and after every compaction. Text that "
                "is only needed for some tasks is paid for on every request that re-sends it, and long files can reduce adherence.",
            action="Keep stable, project-wide rules in CLAUDE.md. Move task-specific reference material (long examples, "
                   "API notes, procedures) into path-scoped rules (.claude/rules/ with paths frontmatter) or a skill, which load "
                   "only when relevant. Run /boring-meter:optimize to see a proposed, reviewable change.",
            severity="medium" if big else "low",
            confidence="high" if big else "medium",
            benefit="medium" if big else "low",
            effort="medium", risk="medium",
            evidence=evidence, source_ids=["local-instruction-files"],
            limitations=["Size alone does not prove waste: some long instructions are necessary.",
                         "Token figures are estimates from character counts, not measured usage."],
        ))
    if within or across:
        evidence = []
        for dup in (within + across)[:5]:
            places = ", ".join("%s:%d" % (display_path(o["path"]), o["line"]) for o in dup["occurrences"][:4])
            evidence.append('"%s" appears at %s.' % (dup["text"][:90], places))
        findings.append(make_finding(
            rule, "dups|" + root,
            title="Repeated instruction lines",
            observed="%d instruction line(s) appear more than once in always-loaded files (%d within one file, %d across files)."
                     % (len(within) + len(across), len(within), len(across)),
            why="Every copy is re-sent with the instructions. Repetition adds context without adding information, and "
                "copies that drift apart over time can contradict each other.",
            action="Keep one copy of each instruction. /boring-meter:optimize proposes removing exact repeats within a file; "
                   "repeats across files need your decision about which file should own the rule.",
            severity="low", confidence="high", benefit="low", effort="low", risk="low",
            evidence=evidence, source_ids=["local-instruction-files"],
            limitations=["Only exact repeats (ignoring case, spacing, and bullet markers) are detected; paraphrases are not."],
        ))
    return findings


# ---------------------------------------------------------------- rule 2


def rule_repeated_reads(ctx: dict, rule: dict) -> List[dict]:
    threshold = ctx["cfg"]["thresholds.repeated_read_count"]
    full = ctx["cfg"]["privacy.show_full_paths"]
    best = {}
    for sess in ctx["sessions"]:
        for path, info in sess["reads"].items():
            key = (sess["session_id"], path)
            if info["max_unchanged"] >= threshold and info["max_unchanged"] > best.get(key, (0,))[0]:
                best[key] = (info["max_unchanged"], path, sess)
    hits = list(best.values())
    if not hits:
        return []
    hits.sort(key=lambda h: -h[0])
    sessions = sorted({h[2]["session_id"] for h in hits})
    evidence = []
    for count, path, sess in hits[:5]:
        evidence.append("%s was read %d times without an Edit or Write to it in between (session %s, %s)."
                        % (_rel(path, sess["cwds"], full), count, _short(sess["session_id"]), _day(sess["first_ts"])))
    if len(hits) > 5:
        evidence.append("%d more file and session pair(s) match." % (len(hits) - 5))
    many = len(hits) >= 5 or hits[0][0] >= threshold * 2
    return [make_finding(
        rule, "reads|" + ctx["scope_key"],
        title="Same files read repeatedly in one session",
        observed="%d file and session pair(s) where a file was read %d or more times with no recorded change in between."
                 % (len(hits), threshold),
        why="Each Read adds the file's content to the conversation again. When the file has not changed, the extra "
            "copies add context that is re-sent on every later request.",
        action="Point Claude at the specific function or line range it needs, ask it to reuse what it already read, and "
               "summarize findings from large files once instead of re-reading them.",
        severity="medium" if many else "low", confidence="medium", benefit="medium" if many else "low",
        effort="low", risk="low", evidence=evidence, source_ids=["claude-code-transcripts"], sessions=sessions,
        limitations=["Changes made outside Edit and Write (for example by Bash commands or other programs) are not visible, "
                     "so some re-reads may have been needed.",
                     "Partial reads (offset and limit) of a large file count as separate reads."],
    )]


# ---------------------------------------------------------------- rule 3


def _unrelated_dirs(cwds: List[str]) -> List[str]:
    roots = []
    for cwd in sorted(cwds, key=len):
        if not any(cwd == r or cwd.startswith(r.rstrip("/") + "/") for r in roots):
            roots.append(cwd)
    return roots


def rule_long_sessions(ctx: dict, rule: dict) -> List[dict]:
    cfg = ctx["cfg"]
    min_cache = cfg["thresholds.cache_rewrite_tokens"]
    evidence, sessions, medium = [], [], 0
    for sess in ctx["sessions"]:
        if sess["is_sidechain"] or sess["session_id"] in sessions:
            continue
        reasons = []
        roots = _unrelated_dirs(sess["cwds"])
        if len(roots) >= 2:
            reasons.append("worked in %d unrelated directories (%s)" % (len(roots), ", ".join(display_path(r) for r in roots[:3])))
            medium += 1
        gaps = [g for g in sess["idle_gaps"] if (g.get("cache_creation_after") or 0) >= min_cache]
        if gaps:
            g = max(gaps, key=lambda x: x.get("cache_creation_after") or 0)
            reasons.append("resumed after a %.1f hour pause and the next request wrote %s tokens to the prompt cache"
                           % (g["hours"], _fmt(g["cache_creation_after"])))
        if not reasons:
            continue
        if sess["compactions"]:
            reasons.append("context was compacted %d time(s)" % len(sess["compactions"]))
        sessions.append(sess["session_id"])
        evidence.append("Session %s (%s, %d prompts): %s." % (_short(sess["session_id"]), _day(sess["first_ts"]),
                                                              sess["user_prompts"], "; ".join(reasons)))
    if not evidence:
        return []
    confidence = "medium" if medium else "low"
    shown = evidence[:5] + (["%d more session(s) match." % (len(evidence) - 5)] if len(evidence) > 5 else [])
    return [make_finding(
        rule, "sessions|" + ctx["scope_key"],
        title="Sessions that continued across separate pieces of work",
        observed="%d session(s) show signals of separate tasks: unrelated working directories, or a long pause followed "
                 "by a large prompt-cache rewrite." % len(evidence),
        why="A long session re-sends its whole history with every request. After a pause longer than the cache lifetime, "
            "that history is written to the cache again at a higher rate than a cache read. Context from an earlier task "
            "rarely helps a new one.",
        action="When you start an unrelated task or return after a long break, consider /clear or a new session and give "
               "Claude a short summary of what it needs. Boring Meter never clears sessions for you.",
        severity="medium" if medium else "low", confidence=confidence, benefit="medium", effort="low", risk="medium",
        evidence=shown, source_ids=["claude-code-transcripts"], sessions=sessions,
        limitations=["A pause or a directory change does not prove the work was unrelated.",
                     "Continuing a session can be the right choice when the earlier context is still needed."],
    )]


# ---------------------------------------------------------------- rule 4


def rule_output(ctx: dict, rule: dict) -> List[dict]:
    threshold = ctx["cfg"]["thresholds.rewrite_count"]
    full = ctx["cfg"]["privacy.show_full_paths"]
    evidence, sessions = [], set()
    by_session = {}
    for s in ctx["sessions"]:
        by_session.setdefault(s["session_id"], s)  # one transcript file per session id
    truncated = [(s["max_tokens_stops"], s) for s in by_session.values() if s["max_tokens_stops"]]
    rewrites = [(n, p, s) for s in by_session.values() for p, n in s["full_writes"].items() if n >= threshold]
    if not truncated and not rewrites:
        return []
    for count, sess in sorted(truncated, key=lambda t: -t[0])[:3]:
        evidence.append("Session %s (%s): %d response(s) stopped at the output token limit (stop_reason max_tokens)."
                        % (_short(sess["session_id"]), _day(sess["first_ts"]), count))
        sessions.add(sess["session_id"])
    for count, path, sess in sorted(rewrites, key=lambda r: -r[0])[:3]:
        evidence.append("Session %s (%s): %s was rewritten in full %d times with the Write tool."
                        % (_short(sess["session_id"]), _day(sess["first_ts"]), _rel(path, sess["cwds"], full), count))
        sessions.add(sess["session_id"])
    return [make_finding(
        rule, "output|" + ctx["scope_key"],
        title="Large outputs that were cut off or regenerated",
        observed=" and ".join(part for part in (
            "%d session(s) with responses cut off at the output limit" % len(truncated) if truncated else "",
            "%d file(s) rewritten in full %d or more times in one session" % (len(rewrites), threshold) if rewrites else "",
        ) if part) + ".",
        why="A response cut off at the limit usually has to be regenerated. Rewriting a whole file to change part of it "
            "spends output tokens on unchanged content.",
        action="Ask for the exact deliverable and format up front, request large artifacts in parts, and ask for targeted "
               "edits instead of full rewrites once a file exists.",
        severity="low", confidence="medium", benefit="medium" if len(rewrites) + len(truncated) >= 3 else "low",
        effort="low", risk="low", evidence=evidence, source_ids=["claude-code-transcripts"], sessions=sorted(sessions),
        limitations=["Some full rewrites are legitimate, for example generated files.",
                     "Output volume alone is never treated as waste."],
    )]


# ---------------------------------------------------------------- rule 5


def rule_model_mismatch(ctx: dict, rule: dict) -> List[dict]:
    pricing = ctx.get("pricing")
    if not pricing:
        return []
    cfg = ctx["cfg"]
    min_requests = cfg["thresholds.min_requests_for_model_rule"]
    small = cfg["thresholds.subagent_output_tokens"]
    by_model: Dict[str, List[int]] = {}
    for record in ctx["records"]:
        if record["is_sidechain"] and not record["synthetic"] and record["output_tokens"] is not None and record["model"]:
            by_model.setdefault(record["model"], []).append(record["output_tokens"])
    priced = {m: resolve_model(m, pricing) for m in by_model}
    findings = []
    for model, outputs in sorted(by_model.items(), key=lambda kv: -len(kv[1])):
        canonical = priced.get(model)
        if not canonical or len(outputs) < min_requests:
            continue
        lighter = _lighter_candidates(canonical, pricing)
        if not lighter:
            continue  # already on a light model
        median = statistics.median(outputs)
        if median > small:
            continue
        ratios = []
        for cand in lighter[:2]:
            r = list_price_ratio(canonical, cand, pricing)
            if r:
                ratios.append("%s list prices are %d%% of %s for input and %d%% for output" % (
                    cand, round(r[0] * 100), canonical, round(r[1] * 100)))
        evidence = ["%s subagent requests ran on %s with a median of %s output tokens per request."
                    % (_fmt(len(outputs)), model, _fmt(int(median)))]
        evidence += ["Price fact (not a savings estimate): %s." % r for r in ratios]
        findings.append(make_finding(
            rule, "model|%s|%s" % (model, ctx["scope_key"]),
            title="Routine subagent work on %s" % model,
            observed="Subagent requests on %s mostly produce short outputs (median %s tokens)." % (model, _fmt(int(median))),
            why="Short, routine subagent tasks (searching, reading, summarizing) often do not need the most capable model.",
            action="Run an equivalent task with a lighter model for the subagent (for example by setting `model` in the "
                   "subagent definition) and compare results with /boring-meter:experiment before switching. Boring Meter "
                   "never changes models for you.",
            severity="low", confidence="low", benefit="medium", effort="low", risk="medium",
            evidence=evidence, source_ids=["claude-code-transcripts", "pricing:" + pricing["pricing_version"]],
            limitations=["Short output does not prove a task was simple; some short answers need careful reasoning.",
                         "Quality on a lighter model is unknown until tested on comparable tasks."],
        ))
    return findings


def _lighter_candidates(model: str, pricing: dict) -> List[str]:
    family_order = ["sonnet-5-5", "haiku-5-5", "sonnet-5", "sonnet-4-6", "haiku-4-5"]
    base = pricing["models"][model]["input"]
    names = []
    for suffix in family_order:
        name = "claude-" + suffix
        if name in pricing["models"] and name != model and pricing["models"][name]["input"] < base:
            names.append(name)
    return names


RULES: List[dict] = [
    {
        "rule_id": "R1-oversized-instructions", "version": 1, "name": "Oversized or repeated project instructions",
        "description": "Always-loaded instruction files that exceed size thresholds or repeat lines word for word.",
        "sources": ["local-instruction-files", "boring-meter-hook-events (optional)"],
        "required_evidence": "Instruction files readable from documented Claude Code locations.",
        "exclusions": "Files loaded on demand (nested CLAUDE.md, path-scoped rules) are not counted toward always-loaded size.",
        "impact_type": "potential_context_reduction",
        "verification": "Compare cache-write and input tokens at session start for an equivalent task before and after "
                        "the change, and confirm Claude still follows the moved rules.",
        "limitations": [], "check": rule_instructions,
    },
    {
        "rule_id": "R2-repeated-context-loading", "version": 1, "name": "Repeated file reads without changes",
        "description": "A file read several times in one session with no Edit or Write to it in between.",
        "sources": ["claude-code-transcripts"],
        "required_evidence": "Read tool calls with file paths in session transcripts.",
        "exclusions": "Reads separated by an Edit, Write, MultiEdit, or NotebookEdit of the same file are not counted together.",
        "impact_type": "potential_context_reduction",
        "verification": "Repeat a comparable task with narrower reads and compare input and cache tokens per session.",
        "limitations": [], "check": rule_repeated_reads,
    },
    {
        "rule_id": "R3-long-session-unrelated-work", "version": 1, "name": "Unrelated work in long sessions",
        "description": "Sessions that span unrelated directories, or resume after a long pause with a large cache rewrite.",
        "sources": ["claude-code-transcripts"],
        "required_evidence": "Session working directories and request timestamps with cache-write token counts.",
        "exclusions": "Subagent transcripts; subdirectories of the same project; pauses with small cache writes.",
        "impact_type": "potential_context_reduction",
        "verification": "Track cache-write tokens on the first request after a break, with and without starting a new session.",
        "limitations": [], "check": rule_long_sessions,
    },
    {
        "rule_id": "R4-excessive-output", "version": 1, "name": "Truncated or regenerated large outputs",
        "description": "Responses stopped at the output token limit, or files fully rewritten many times in one session.",
        "sources": ["claude-code-transcripts"],
        "required_evidence": "stop_reason values and Write tool calls with file paths.",
        "exclusions": "Token volume alone never triggers this rule.",
        "impact_type": "potential_output_reduction",
        "verification": "Compare output tokens for an equivalent deliverable before and after specifying format and scope.",
        "limitations": [], "check": rule_output,
    },
    {
        "rule_id": "R5-possible-model-mismatch", "version": 1, "name": "Routine subagent work on a top-tier model",
        "description": "Many subagent requests on a high-priced model with consistently short outputs.",
        "sources": ["claude-code-transcripts", "pricing table"],
        "required_evidence": "Model attribution per request, output tokens, and known list prices for the model.",
        "exclusions": "Main-conversation requests; models already priced near the cheapest tier; unknown models.",
        "impact_type": "potential_cost_reduction",
        "verification": "Run the same subagent task on both models with /boring-meter:experiment and compare quality and tokens.",
        "limitations": [], "check": rule_model_mismatch,
    },
]


def run_rules(ctx: dict, limit: Optional[int] = None) -> List[dict]:
    findings: Dict[str, dict] = {}
    for rule in RULES:
        for finding in rule["check"](ctx, rule):
            findings.setdefault(finding["finding_id"], finding)
    ordered = sorted(
        findings.values(),
        key=lambda f: (-f["scores"]["priority"], -f["scores"]["confidence"], f["rule_id"], f["finding_id"]),
    )
    return ordered[:limit] if limit else ordered


def rule_catalog() -> List[dict]:
    return [{k: v for k, v in rule.items() if k != "check"} for rule in RULES]
