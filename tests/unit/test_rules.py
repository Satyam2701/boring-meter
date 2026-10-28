from pathlib import Path

from tests.helpers import TempEnvTestCase

from boring_meter import instructions, pricing, rules


def session(sid="synthetic-s", **kw):
    base = {"session_id": sid, "is_sidechain": False, "first_ts": 1792000000.0, "last_ts": 1792003600.0, "cwds": ["/synthetic/p"],
            "user_prompts": 5, "requests": 10, "compactions": [], "tool_counts": {}, "reads": {}, "full_writes": {},
            "max_tokens_stops": 0, "idle_gaps": [], "models": [], "versions": []}
    base.update(kw)
    return base


class RuleTests(TempEnvTestCase):
    with_fixtures = False

    def ctx(self, sessions=(), records=(), analysis=None, **cfg):
        return {"cfg": self.cfg(**cfg), "records": list(records), "sessions": list(sessions), "instructions": analysis,
                "pricing": pricing.load_pricing(self.cfg()), "instruction_loads": None, "scope_key": "test"}

    def test_repeated_reads(self):
        s = session(reads={"/synthetic/p/a.py": {"count": 6, "max_unchanged": 5}, "/synthetic/p/b.py": {"count": 3, "max_unchanged": 3}})
        found = rules.run_rules(self.ctx([s]))
        self.assertEqual([f["rule_id"] for f in found], ["R2-repeated-context-loading"])
        f = found[0]
        self.assertIn("a.py was read 5 times", f["evidence"][0])
        self.assertNotIn("b.py", " ".join(f["evidence"]))
        for key in ("evidence", "recommended_action", "confidence", "limitations", "verification_method"):
            self.assertTrue(f[key])
        self.assertIsNone(f["estimated_savings"])

    def test_threshold_is_configurable(self):
        s = session(reads={"/synthetic/p/a.py": {"count": 6, "max_unchanged": 5}})
        self.assertEqual(rules.run_rules(self.ctx([s], thresholds__repeated_read_count=6)), [])

    def test_long_session_unrelated_dirs(self):
        s = session(cwds=["/synthetic/one", "/synthetic/one/sub", "/synthetic/two"])
        f = rules.run_rules(self.ctx([s]))[0]
        self.assertEqual(f["rule_id"], "R3-long-session-unrelated-work")
        self.assertEqual(f["confidence"], "medium")
        self.assertIn("2 unrelated directories", f["evidence"][0])

    def test_subdirectories_are_not_unrelated(self):
        s = session(cwds=["/synthetic/one", "/synthetic/one/sub"])
        self.assertEqual(rules.run_rules(self.ctx([s])), [])

    def test_idle_gap_needs_large_cache_write(self):
        small = session(idle_gaps=[{"ts": 1, "hours": 9.0, "cache_creation_after": 500, "prompt_tokens_after": 600}])
        self.assertEqual(rules.run_rules(self.ctx([small])), [])
        big = session(idle_gaps=[{"ts": 1, "hours": 9.0, "cache_creation_after": 300000, "prompt_tokens_after": 300100}])
        f = rules.run_rules(self.ctx([big]))[0]
        self.assertEqual(f["confidence"], "low")
        self.assertIn("300,000", f["evidence"][0])

    def test_subagent_sessions_excluded_from_long_session_rule(self):
        s = session(is_sidechain=True, cwds=["/synthetic/one", "/synthetic/two"])
        self.assertEqual(rules.run_rules(self.ctx([s])), [])

    def test_output_rule_needs_explicit_evidence(self):
        quiet = session(full_writes={"/synthetic/p/x.md": 2})
        self.assertEqual(rules.run_rules(self.ctx([quiet])), [])
        loud = session(full_writes={"/synthetic/p/x.md": 4}, max_tokens_stops=1)
        f = rules.run_rules(self.ctx([loud]))[0]
        self.assertEqual(f["rule_id"], "R4-excessive-output")
        self.assertEqual(len(f["evidence"]), 2)

    def _subagent_records(self, model, n, out):
        return [{"is_sidechain": True, "synthetic": False, "output_tokens": out, "model": model} for _ in range(n)]

    def test_model_mismatch(self):
        recs = self._subagent_records("claude-opus-5-5", 30, 200)
        f = rules.run_rules(self.ctx(records=recs))[0]
        self.assertEqual(f["rule_id"], "R5-possible-model-mismatch")
        self.assertEqual(f["confidence"], "low")
        self.assertTrue(any("Price fact" in e for e in f["evidence"]))

    def test_model_mismatch_exclusions(self):
        self.assertEqual(rules.run_rules(self.ctx(records=self._subagent_records("claude-opus-5-5", 5, 200))), [])
        self.assertEqual(rules.run_rules(self.ctx(records=self._subagent_records("claude-opus-5-5", 30, 5000))), [])
        self.assertEqual(rules.run_rules(self.ctx(records=self._subagent_records("claude-haiku-5-5", 30, 100))), [])
        self.assertEqual(rules.run_rules(self.ctx(records=self._subagent_records("claude-imaginary-9", 30, 100))), [])

    def test_oversized_instructions(self):
        project = self.tmp / "proj"
        project.mkdir()
        body = ["# Project rules", ""] + ["- Rule number %d says something specific about the code." % i for i in range(260)]
        body += ["- Always run the full test suite before committing changes."] * 2
        (project / "CLAUDE.md").write_text("\n".join(body) + "\n")
        analysis = instructions.analyze(project, include_user=False)
        found = rules.run_rules(self.ctx(analysis=analysis))
        ids = [f["rule_id"] for f in found]
        self.assertEqual(ids.count("R1-oversized-instructions"), 2)
        titles = [f["title"] for f in found]
        self.assertIn("Large always-loaded project instructions", titles)
        self.assertIn("Repeated instruction lines", titles)
        size = next(f for f in found if f["title"].startswith("Large"))
        self.assertTrue(any("estimate" in e for e in size["evidence"]))

    def test_small_instructions_no_finding(self):
        project = self.tmp / "proj"
        project.mkdir()
        (project / "CLAUDE.md").write_text("# Rules\n- Use tabs.\n")
        self.assertEqual(rules.run_rules(self.ctx(analysis=instructions.analyze(project, include_user=False))), [])

    def test_scoring_confidence_dominates(self):
        high_conf_low_benefit = rules.score("low", "high", "low", "low")["priority"]
        low_conf_high_benefit = rules.score("high", "low", "low", "low")["priority"]
        self.assertGreater(high_conf_low_benefit, low_conf_high_benefit)

    def test_ordering_and_stable_ids(self):
        sessions = [session(reads={"/synthetic/p/a.py": {"count": 9, "max_unchanged": 9}}),
                    session("synthetic-t", cwds=["/synthetic/one", "/synthetic/two"])]
        first = rules.run_rules(self.ctx(sessions))
        second = rules.run_rules(self.ctx(sessions))
        self.assertEqual([f["finding_id"] for f in first], [f["finding_id"] for f in second])
        priorities = [f["scores"]["priority"] for f in first]
        self.assertEqual(priorities, sorted(priorities, reverse=True))
        self.assertEqual(len({f["finding_id"] for f in first}), len(first))

    def test_catalog_complete(self):
        for rule in rules.rule_catalog():
            for key in ("rule_id", "version", "name", "description", "sources", "required_evidence", "exclusions",
                        "impact_type", "verification"):
                self.assertTrue(rule[key], (rule["rule_id"], key))


class InstructionDiscoveryTests(TempEnvTestCase):
    with_fixtures = False

    def test_locations_and_load_modes(self):
        project = self.tmp / "repo"
        (project / ".claude" / "rules").mkdir(parents=True)
        (project / "pkg").mkdir()
        (project / "docs").mkdir()
        (project / "CLAUDE.md").write_text("# Main\nSee @docs/extra.md for more.\n")
        (project / "docs" / "extra.md").write_text("extra imported text\n@nested.md\n")
        (project / "docs" / "nested.md").write_text("second hop\n")
        (project / "CLAUDE.local.md").write_text("local prefs\n")
        (project / ".claude" / "rules" / "always.md").write_text("always rule\n")
        (project / ".claude" / "rules" / "scoped.md").write_text("---\npaths:\n  - src/**\n---\nscoped rule\n")
        (project / "pkg" / "CLAUDE.md").write_text("nested\n")
        (self.claude_dir / "CLAUDE.md").write_text("user level\n")
        found = {Path(f.path).name + ":" + f.scope: f.loaded for f in instructions.discover(project)["files"]}
        self.assertEqual(found["CLAUDE.md:project"], "launch")
        self.assertEqual(found["extra.md:import"], "launch")
        self.assertEqual(found["nested.md:import"], "launch")
        self.assertEqual(found["CLAUDE.local.md:local"], "launch")
        self.assertEqual(found["always.md:project-rule"], "launch")
        self.assertEqual(found["scoped.md:path-rule"], "on demand")
        self.assertEqual(found["CLAUDE.md:nested"], "on demand")
        self.assertEqual(found["CLAUDE.md:user"], "launch")

    def test_agents_md_only_without_claude_md(self):
        project = self.tmp / "repo"
        project.mkdir()
        (project / "AGENTS.md").write_text("agents\n")
        scopes = [f.scope for f in instructions.discover(project, include_user=False)["files"]]
        self.assertIn("agents", scopes)
        (project / "CLAUDE.md").write_text("claude\n")
        scopes = [f.scope for f in instructions.discover(project, include_user=False)["files"]]
        self.assertNotIn("agents", scopes)

    def test_import_outside_home_not_read(self):
        project = self.tmp / "repo"
        project.mkdir()
        (project / "CLAUDE.md").write_text("@/etc/hosts.txt\n")
        result = instructions.discover(project, include_user=False)
        self.assertTrue(any("outside" in s for s in result["skipped"]) or len(result["files"]) == 1)


class DuplicateSessionTests(TempEnvTestCase):
    with_fixtures = False
    ctx = RuleTests.ctx

    def test_same_session_in_two_files_reported_once(self):
        a = session(cwds=["/synthetic/one", "/synthetic/two"])
        b = dict(a)
        f = rules.run_rules(self.ctx([a, b]))[0]
        self.assertEqual(len(f["evidence"]), 1)
        reads = {"/synthetic/p/a.py": {"count": 5, "max_unchanged": 5}}
        f = rules.run_rules(self.ctx([session(reads=reads), session(reads=reads)]))[0]
        self.assertEqual(len(f["evidence"]), 1)
