# Boring Meter PRD (v1.0)

Source: the "Boring Meter: End-to-End Product and Technical PRD for Claude Code" (v1.0, status "Ready for implementation") that the owner supplied in the build session on 2026-10-27. This file is a faithful condensation of that document: every requirement is kept, wording is shortened. All content here is **VERIFIED** (taken from the owner's PRD) unless marked otherwise. Where the PRD and the official Claude Code documentation disagree, the documentation wins (PRD rule).

## 1. Directive

Build Boring Meter as a complete, working Claude Code plugin. Inspect the environment first, read official Claude Code plugin, skill, command, hook and settings docs, and never invent APIs, hook events, payload fields, CLI options or usage data sources. No paid APIs, hosted LLMs, paid databases, mandatory external services, authentication or account creation. Never fabricate token counts, costs, quota percentages, savings or findings. Separate observed data, derived calculations, estimates and recommendations. Local by default. Never automatically change project files, delete data, clear sessions or run destructive optimizations. Include unit and integration tests, fixtures, error handling, accessibility and documentation. Keep the first release small and reliable. **Never use em dashes** in any generated text. Never claim a test, build or install succeeded unless it ran and passed. When data or platform capability is missing, document the limitation and implement a safe fallback.

## 2. Vision

A local usage intelligence and optimization companion, not just a token counter. Promise: understand your usage, find avoidable overhead, improve your workflow, verify the result.

User problems: no view of historical usage; long sessions and extra context increase usage; instruction files may be large or repetitive; repeated expensive operations go unnoticed; hard to tell useful complexity from overhead; token counts do not say what to do; no evidence that an optimization worked.

Principles: accuracy over impressive metrics; actionable insights over decorative dashboards; privacy by default; no paid API dependency; recommendations before automation; measured outcomes over promised savings; minimal setup; graceful degradation when data is missing.

## 3. Goals and non-goals

MVP goals: valid plugin; read supported local usage data; summaries by session and date; separate input, output, cached and other token categories when available; API cost only when usage and pricing exist; at least three useful optimization detections; every finding with evidence, impact, confidence and action; local analysis of project instructions and selected config files; terminal and JSON reports; before-and-after experiments; core works offline; tests and docs for install, config and troubleshooting.

Non-goals: hosted dashboard, accounts, team admin or cloud sync, external AI analysis, automatic model switching, automatic context clearing, automatic deletion or rewriting of user files, subscription billing, guarantees about remaining subscription quota, universal multi-provider tracking, browser extension or desktop app, elaborate visualization. A local static HTML report is allowed only without server, external resources or extra dependencies.

## 4. Users and jobs

Primary: developers using Claude Code daily. Secondary: technical founders, AI power users, large-project maintainers, multi-repo users, users managing API cost or subscription limits.

Jobs: Understand (where usage goes), Diagnose (what is inefficient), Improve (a specific change), Validate (did usage drop without hurting quality), Control (notice unusual usage with data actually available).

## 5. Priorities

- **P0 (first release):** valid plugin; namespaced slash commands; local usage discovery; robust parsing; session and daily summaries; token category breakdowns; cost estimation with explicit assumptions; project instruction analyzer; rule-based engine; recommendations with evidence and confidence; terminal report and JSON export; before-and-after experiments; local settings and privacy controls; automated tests and docs.
- **P1 (after MVP validation):** more rules; configurable thresholds; detailed project comparisons; better historical reporting; optional static HTML report; more verified data adapters; user-defined exclusions.
- **P2 (deferred):** team reports, remote sync, paid tiers, hosted dashboards, cross-provider analytics, predictive budget optimization.

Do not start P1 or P2 until P0 passes acceptance.

## 6. Platform research

Verify plugins, hooks, skills, CLI reference and Anthropic usage/cost docs before coding. Implement a discovery phase that reports supported and unavailable sources. If no reliable historical token data exists, stay useful through instruction analysis and supported live collection, never fabricated numbers.

## 7. Architecture

Logical layout: plugin manifest; commands (usage, analyze, optimize, report, experiment, settings); skills (usage interpretation, optimization guidance); hooks (supported event collection, local persistence); core engine (discovery, adapters, normalization, aggregation, cost, rules, experiment comparison); local storage (settings, normalized records, experiments); reporting (terminal, JSON, optional static HTML). Prefer the simplest verified runtime, standard libraries, no network at runtime, no database servers (append-only JSONL acceptable), no LLM calls in analysis.

## 8. Commands

- **`/boring-meter:usage`**: default recent period; `--today`; `--week` (documented boundaries); `--session`; `--json`; `--source`. Show period and source; input and output separately; cache read and creation only where supported; identify missing metrics; API cost only with valid pricing; clear empty state; never imply token counts equal remaining subscription allowance.
- **`/boring-meter:analyze`**: `--project`, `--session`, `--limit`, `--json`. Rank by documented priority; evidence and source; why inefficient; next steps; uncertainty; no duplicate findings; never modify files.
- **`/boring-meter:optimize`**: eligible files only; detect duplicated or irrelevant instructions where deterministic; propose revised content or diff; preserve intent; never overwrite without explicit confirmation; offer a safe way to save or copy the proposal.
- **`/boring-meter:report`**: period and completeness; observed usage; top findings; costs only where supported; verified and unverified outcomes separately; JSON; write only to an explicit destination or a documented default inside the data directory; never overwrite without confirmation.
- **`/boring-meter:experiment`**: start; record baseline; record follow-up; compare equivalent runs; mark quality preserved, improved, degraded or unknown; history. Never label savings verified without comparable data.
- **`/boring-meter:settings`**: show sources; toggle optional collection; thresholds; pricing assumptions; retention; inspect data directory; export or delete Boring Meter's own records; explain which changes need a new session or reload.

## 9. Data collection

Each adapter declares: source id, type, discovery method, fields, schema or version, timestamp semantics, completeness, limitations, error status, observed vs derived.

Discovery: find documented local sources only (never scan the whole file system), validate paths and formats, report readable vs unreadable and unsupported formats, report available metrics, continue past failing sources.

Normalized record (internal, versioned): `schema_version`, `record_id`, `source`, `session_id`, `project_id`, `timestamp`, `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `other_token_metrics`, `cost_amount`, `cost_currency`, `data_quality`, `provenance`. Rules: unknown stays null, genuine zero stays zero; keep provenance; stable ids and dedup; keep original timestamps; never sum incompatible metrics; never infer tokens from text length as actual usage; record schema and adapter versions; quarantine malformed records without losing the rest.

Dedup: stable source ids, else a documented deterministic fingerprint; never by timestamp and token count alone.

File handling: missing, empty, invalid JSON, partial writes, truncated JSONL, permission errors, rotated files, symlinks (do not follow outside configured directories), unexpected sizes, unsupported schema versions, duplicates, concurrent invocations. Atomic writes for config and state.

## 10. Calculations and cost

Aggregate only compatible observed values per period: input, output, cache read, cache creation, sessions with usable and incomplete data, usage by model, daily or session trends. Confirm whether cache categories are subsets of input before totaling. Document aggregation per adapter.

Cost = sum of applicable categories x unit prices. Versioned pricing with currency and unit; distinguish source-reported cost from local estimates; record pricing version and date; price cache read and creation separately; handle aliases and missing pricing explicitly; never use another model's price; no cost for unknown categories; state exclusions (discounts, credits, taxes). Subscription usage is not API billing: never turn subscription token counts into dollar savings without a justified model.

Missing data: missing output is not zero; partial periods marked incomplete; overlapping sources deduplicated and explained; clear empty state with a supported collection path.

## 11. Rules engine

Deterministic and versioned, no LLM. Each rule: id and version, name, description, sources, required evidence, detection logic, exclusions, severity, confidence, recommended action, impact category, verification method, limitations, unit tests.

Required MVP rules:
1. Oversized project instructions (configurable thresholds; flag duplication or task-specific guidance only with evidence).
2. Repeated context loading (only when records support it; re-reads may be legitimate).
3. Unrelated work in long sessions (only with reliable task signals; never clear sessions).
4. Excessive output (explicit evidence only; token volume alone is insufficient).
5. Possible model mismatch (needs model attribution and model characteristics; never switch models or claim savings without pricing and comparable results).

Finding fields: `finding_id`, `rule_id`, `title`, `evidence`, `source_ids`, `severity`, `confidence`, `impact_type`, `estimated_savings`, `recommended_action`, `verification_method`, `limitations`.

Priority: transparent scoring from expected benefit, confidence, effort and quality risk; components visible; no implied savings percentage; a speculative finding must not outrank a high-confidence one just because it sounds impactful.

Safety before any applied change: show current content, show diff, explain benefit and risk, get explicit approval, back up, smallest change, verify, report. Otherwise give copyable instructions.

## 12. Experiments

Workflow: unique id; record task type, model, project, baseline; record the optimization; apply manually or by confirmed action; repeat a comparable task; record follow-up; capture user-reported quality and completion; diff only comparable metrics; classify verified, directional, inconclusive or invalid; keep history locally. Flag differences in context, caching, model version, output requirements and tool use. No causation claims. Metrics: input, output, comparable total and API cost differences; completion; quality; completeness; confidence and limitations. Unknown quality means no claim that quality was preserved.

## 13. Storage and privacy

Platform-conventional data directory; store only what reporting and experiments need. Defaults: local only, no analytics, no LLM requests, no hidden uploads, no secrets, no full prompts or responses unless strictly necessary and enabled, no env vars or credentials, no tracking of unrelated repos, no destructive changes to source data. Config: data directory, sources, collection, retention, pricing, reporting, excluded paths, log level. Retention never deletes original Claude Code data. Security: restrict permissions, validate paths and output destinations, prevent traversal, no shell commands from untrusted strings, redact logs, never execute analyzed content, no network in core processing.

## 14. Terminal UX

Concise and consistent. Usage overview shows period, source, coverage, input, output, cache read, cache creation, sessions, API estimate (if supported), top opportunity and a pointer to analyze. Placeholders are never shown as data. Each finding: title, observation, why it matters, action, impact category, confidence, effort, risks and limitations, verification. Explicit empty states for: no records, no source, no token fields, no findings, no pricing, incomplete period, unsupported format, storage unavailable, permission denied. Never show unavailable values as zero usage. Accessibility: meaningful headings, no color-only status, readable contrast, screen-reader and plain-text friendly, no animation, narrow widths, respect non-interactive use.

## 15. Errors

Actionable messages without leaking sensitive data for: incorrect install, unsupported Claude Code version, missing runtime, unavailable source, corrupted record, permission denied, storage full, invalid config, unknown pricing, unsupported schema, duplicate events, concurrent writers, invalid experiment comparison, failed export, invalid output path, interrupted collection, clock or timezone mismatch, missing hook payload fields. Remain usable when optional capabilities fail; never silently discard large amounts of data.

## 16. Performance

Targets: usage summary under 2 s for up to 10,000 normalized records; instruction scan under 2 s for small to medium repos; avoid re-parsing unchanged files; memory proportional to data; explicit size limits; interrupted writes never corrupt the store; one bad record never blocks the rest. Benchmark and document deviations.

## 17. Testing

Unit: adapters, timestamps, aggregation, missing values, cache semantics, pricing, aliases, dedup, findings, scoring, experiments, config validation, path safety, JSON serialization, retention. Integration: command execution, discovery, report generation, rule engine, JSON export, settings persistence, concurrent writes, invalid records, unsupported schemas, no-network execution, missing runtime, install and command discovery. Synthetic, clearly labeled fixtures for every case in the PRD list (valid, empty, missing fields, zero tokens, cache categories, unknown models and pricing, duplicates, malformed and truncated, multiple projects and sessions, timezone offsets, rotated files, unsupported schemas, large files, partial periods).

Acceptance scenarios A to L: first installation; valid weekly totals with coverage; missing metrics stay unknown; cost matches independent calculation; unknown pricing produces no price; oversized instructions produce a finding; unapproved change leaves the file unchanged; one corrupted record leaves the rest usable; comparable experiment computes valid differences and keeps quality uncertainty; no external transmission or raw content persisted; offline operation; no-data environment explains the limitation without inventing data.

## 18. Definition of done

Current plugin format; discoverable and executable commands; documented sources; source semantics preserved; unknowns stay unknown; reproducible costs; at least three tested rules; evidence and action on every finding; confirmation before file changes; no paid APIs; documented privacy and retention; working experiments; unit, integration and end-to-end tests pass; complete install and troubleshooting docs; no secrets or unnecessary content collected; no em dashes; nothing claimed complete without verification.

## 19. Implementation sequence

Phases: inspect and plan; plugin foundation; data foundation; usage reporting; optimization engine; experiments and privacy; QA and release. Keep a working state after every phase.

## 20. README requirements

Overview, features, MVP limitations, verified compatibility, installation, command reference, data sources and metrics, cost methodology, privacy and storage, configuration, testing, troubleshooting, uninstall, contribution guidance, license only once deliberately chosen. No invented badges, download counts, quotes, performance results or savings.

## 21. Release validation (research targets, not forecasts)

Private beta with 10 to 20 Claude Code users: observe installation success, which insights are useful, recommendation adoption, comparable before-and-after usage, whether users would miss the product; test willingness to pay only after repeated value. No hosted analytics or paid features until recurring demand is shown.
