# Optimization rules

The rules engine is deterministic and versioned. It uses no LLM. `boring-meter analyze --rules` prints the catalog.

## Finding structure

Every finding includes: `finding_id` (stable hash of rule and scope), `rule_id`, `rule_version`, `title`, `observed`, `why_it_matters`, `evidence` (concrete observations), `source_ids`, `sessions`, `severity`, `confidence`, `effort`, `risk`, `impact_type`, `estimated_savings` (always null), `recommended_action`, `verification_method`, `limitations`, and `scores`.

## Priority score

```
priority = 3 x confidence + 2 x benefit - effort - risk      (each component 1 to 3)
```

Raw components are shown with every finding. Confidence has the largest weight, so a high-confidence, low-benefit finding (9 + 2 - 1 - 1 = 9) ranks above a low-confidence, high-benefit one (3 + 6 - 1 - 1 = 7) when effort and risk are equal. The score orders findings and never implies a savings percentage. Ties break on confidence, then rule id. Duplicate finding ids are dropped.

## Rules

### R1 Oversized or repeated project instructions (v1)

- Evidence: always-loaded instruction files (see [data-sources.md](data-sources.md)), opt-in load events.
- Detection: any always-loaded file longer than `thresholds.instruction_lines` (default 200, the official guidance), or total always-loaded text over `thresholds.instruction_chars` (default 40,000). A separate finding for word-for-word repeated lines (ignoring case, spacing, and bullet markers; lines of at least 25 characters, outside code blocks).
- Exclusions: on-demand files (nested CLAUDE.md, path-scoped rules). Auto memory is not counted toward the line limit.
- Action: keep stable project-wide rules; move task-specific reference to path-scoped rules or skills; remove repeats (`/boring-meter:optimize`).
- Limitations: size alone does not prove waste; token figures are estimates.

### R2 Repeated context loading (v1)

- Evidence: `Read` tool calls with file paths per session.
- Detection: one file read at least `thresholds.repeated_read_count` times (default 4) in one session with no `Edit`, `Write`, `MultiEdit`, or `NotebookEdit` of that file in between.
- Exclusions: reads separated by a recorded modification.
- Limitations: changes made by Bash or other programs are invisible; partial reads of large files count separately.

### R3 Unrelated work in long sessions (v1)

- Evidence: session working directories and request timestamps with cache-write tokens.
- Detection: a main session that worked in two or more unrelated directories (medium confidence), or resumed after a pause of at least `thresholds.idle_gap_hours` (default 4) where the next request wrote at least `thresholds.cache_rewrite_tokens` (default 20,000) to the prompt cache (low confidence). Compactions are reported as supporting context only.
- Exclusions: subagent transcripts; subdirectories of the same project; small cache writes.
- Action: consider a new session or `/clear` for unrelated work. Never done automatically.

### R4 Excessive output (v1)

- Evidence: `stop_reason` and `Write` tool calls.
- Detection: responses stopped at the output limit (`max_tokens`), or one file fully rewritten at least `thresholds.rewrite_count` times (default 3) in one session. Token volume alone never triggers this rule.
- Limitations: some full rewrites are legitimate.

### R5 Possible model mismatch (v1)

- Evidence: per-request model and output tokens on subagent requests, and the pricing table.
- Detection: at least `thresholds.min_requests_for_model_rule` (default 20) subagent requests on a model that has a cheaper listed alternative, with median output at or below `thresholds.subagent_output_tokens` (default 1,500). Low confidence.
- Evidence includes list-price ratios as facts, not as savings.
- Exclusions: main-conversation requests, unknown models, models already on the lightest tier.
- Action: test a lighter model on an equivalent task with an experiment. Never switches models.

## Experiment classification

| Result | Meaning |
| --- | --- |
| invalid | Missing runs, missing token categories, or different models between baseline and follow-up |
| inconclusive | Quality degraded, follow-up task not completed, zero difference, or a difference within the spread between runs |
| verified | At least 2 runs on each side, complete data, same models, no comparability warnings (cache-read share within 25 points, request counts within 2x), quality preserved or improved, task completed, and a mean difference larger than the run-to-run spread |
| directional | Comparable data that does not meet the verified bar |

Verified means a consistent measured difference under comparable conditions. It does not prove causation.
