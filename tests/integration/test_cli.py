"""Integration tests: run the real launcher (bin/boring-meter) as a subprocess.

On Windows the main suite calls scripts/run_boring_meter.py with the test interpreter
(the same entry point both launchers use), so each CI job tests its own Python version.
LauncherTests cover bin/boring-meter.cmd and the sh launcher under Git Bash separately.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from tests.helpers import ROOT, TempEnvTestCase
from tests.fixtures.build import EXPECTED

LAUNCHER = ROOT / "bin" / "boring-meter"
CMD_LAUNCHER = ROOT / "bin" / "boring-meter.cmd"
ENTRY = ROOT / "scripts" / "run_boring_meter.py"
HOOK = ROOT / "scripts" / "hook_instructions_loaded.py"
ON_WINDOWS = os.name == "nt"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class CLITestCase(TempEnvTestCase):
    def run_cli(self, *args, env=None, input_text=None, cwd=None):
        full_env = dict(os.environ)
        full_env.update(env or {})
        if ON_WINDOWS:
            command = [sys.executable, str(ENTRY)]
        else:
            command = [str(LAUNCHER)]
        return subprocess.run(command + list(args), capture_output=True, text=True, env=full_env,
                              input=input_text, cwd=str(cwd or self.tmp), timeout=60)

    def json_cli(self, *args, **kw):
        proc = self.run_cli(*args, "--json", **kw)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)


class UsageScenarios(CLITestCase):
    def test_b_valid_usage_totals_and_coverage(self):
        data = self.json_cli("usage", "--all")
        self.assertEqual(data["requests"], EXPECTED["requests"])
        a1 = self.json_cli("usage", "--session", "synthetic-a1")
        for key, value in EXPECTED["a1"].items():
            self.assertEqual(a1["totals"][key]["sum"], value)
        self.assertEqual(data["coverage"], "partial")
        text = self.run_cli("usage", "--all").stdout
        self.assertIn("Coverage:              Partial", text)
        self.assertIn("Period:", text)
        self.assertIn("not your remaining subscription", text)

    def test_c_missing_output_reported_as_unknown(self):
        text = self.run_cli("usage", "--session", "synthetic-a2").stdout
        self.assertIn("(1 request(s) missing this value)", text)
        data = self.json_cli("usage", "--session", "synthetic-a2")
        self.assertEqual(data["totals"]["output_tokens"]["missing"], 1)

    def test_d_cost_matches_independent_calculation(self):
        data = self.json_cli("usage", "--session", "synthetic-a1")
        self.assertEqual(Decimal(data["cost"]["amount"]), EXPECTED["a1_cost"].quantize(Decimal("0.0001")))
        self.assertEqual(data["cost"]["pricing_version"], "anthropic-api-list-2026-10-27")
        self.assertTrue(data["cost"]["assumptions"])
        self.assertTrue(data["cost"]["complete"])

    def test_e_unknown_pricing_not_fabricated(self):
        data = self.json_cli("usage", "--session", "synthetic-a2")
        self.assertFalse(data["cost"]["complete"])
        self.assertIn("no price for model claude-imaginary-9", data["cost"]["unpriced_reasons"])
        self.assertNotIn("claude-imaginary-9", data["cost"]["by_model"])

    def test_h_corrupted_record_keeps_valid_records(self):
        data = self.json_cli("usage", "--all")
        self.assertGreater(data["requests"], 0)
        self.assertTrue(any("malformed" in n for n in data["coverage_notes"]))

    def test_l_no_data_access_empty_state(self):
        empty = self.tmp / "empty-claude"
        empty.mkdir()
        proc = self.run_cli("usage", "--week", env={"CLAUDE_CONFIG_DIR": str(empty)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No readable Claude Code transcripts were found", proc.stdout)
        self.assertNotIn("Input tokens", proc.stdout)
        data = self.json_cli("usage", "--week", env={"CLAUDE_CONFIG_DIR": str(empty)})
        self.assertEqual(data["coverage"], "none")
        self.assertFalse(data["cost"]["available"])

    def test_period_without_records_is_not_zero(self):
        proc = self.run_cli("usage", "--since", "2030-01-01")
        self.assertIn("not a zero-usage result", proc.stdout)

    def test_sessions_and_sources(self):
        self.assertIn("synthetic-a1"[:8], self.run_cli("usage", "--all", "--sessions").stdout)
        src = self.json_cli("sources")
        self.assertEqual(src["sources"][0]["status"], "ok")
        self.assertEqual(src["unsupported_files"], 1)

    def test_session_prefix_and_unknown_session(self):
        self.assertEqual(self.json_cli("usage", "--session", "synthetic-b")["filters"]["session_id"], "synthetic-b1")
        proc = self.run_cli("usage", "--session", "nope")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("NO_DATA", proc.stderr)
        proc = self.run_cli("usage", "--session", "${CLAUDE_SESSION_ID}")
        self.assertEqual(proc.returncode, 2)

    def test_invalid_arguments(self):
        proc = self.run_cli("usage", "--today", "--week")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Choose only one", proc.stderr)


class AnalyzeAndOptimize(CLITestCase):
    def test_f_findings_with_evidence_and_no_modification(self):
        project = self.tmp / "proj"
        project.mkdir()
        lines = ["- Instruction %d is a specific project convention to follow." % i for i in range(300)]
        (project / "CLAUDE.md").write_text("# Rules\n" + "\n".join(lines) + "\n")
        before_project, before_claude = tree_hash(project), tree_hash(self.claude_dir)
        data = self.json_cli("analyze", "--all", "--project", str(project), "--limit", "10")
        ids = {f["rule_id"] for f in data["findings"]}
        self.assertIn("R1-oversized-instructions", ids)
        for f in data["findings"]:
            self.assertTrue(f["evidence"])
            self.assertTrue(f["recommended_action"])
        self.assertEqual(data["files_modified"], [])
        self.assertEqual(tree_hash(project), before_project)
        self.assertEqual(tree_hash(self.claude_dir), before_claude)

    def test_transcript_rules_on_fixtures(self):
        data = self.json_cli("analyze", "--all", "--no-instructions", "--limit", "10")
        ids = {f["rule_id"] for f in data["findings"]}
        self.assertIn("R2-repeated-context-loading", ids)
        self.assertIn("R4-excessive-output", ids)

    def test_no_findings_message(self):
        proc = self.run_cli("analyze", "--since", "2030-01-01", "--no-instructions")
        self.assertIn("No findings", proc.stdout)

    def test_g_safe_optimization_flow(self):
        project = self.tmp / "proj"
        project.mkdir()
        target = project / "CLAUDE.md"
        target.write_text("# Rules\n- Always run the linter before you commit code.\n- Something else entirely here.\n"
                          "- Always run the linter before you commit code.\n")
        original = target.read_bytes()
        data = self.json_cli("optimize", "--project", str(project))
        self.assertEqual(len(data["proposals"]), 1)
        pid = data["proposals"][0]["proposal_id"]
        self.assertEqual(target.read_bytes(), original)
        proc = self.run_cli("optimize", "apply", pid)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("CONFIRMATION_REQUIRED", proc.stderr)
        self.assertEqual(target.read_bytes(), original)
        shown = self.run_cli("optimize", "show", pid).stdout
        self.assertIn("-- Always run the linter", shown)
        proc = self.run_cli("optimize", "apply", pid, "--confirm")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(target.read_text().count("Always run the linter"), 1)
        self.assertIn("Backup", proc.stdout)


class ReportAndSettings(CLITestCase):
    def test_report_markdown_and_json(self):
        md = self.run_cli("report", "--all").stdout
        for section in ("## Period and data completeness", "## Observed usage", "## API cost estimate", "## Top findings",
                        "### Verified", "### Not verified"):
            self.assertIn(section, md)
        data = self.json_cli("report", "--all")
        self.assertIn("summary", data)
        self.assertIn("verified", data["experiments"])

    def test_report_export_never_overwrites(self):
        out = self.tmp / "r.md"
        self.assertEqual(self.run_cli("report", "--all", "--output", str(out)).returncode, 0)
        first = out.read_bytes()
        proc = self.run_cli("report", "--all", "--output", str(out))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("OUTPUT_EXISTS", proc.stderr)
        self.assertEqual(out.read_bytes(), first)
        self.assertEqual(self.run_cli("report", "--all", "--output", str(out), "--force").returncode, 0)
        bad = self.run_cli("report", "--output", str(self.tmp / "no-such-dir" / "r.md"))
        self.assertIn("INVALID_OUTPUT_PATH", bad.stderr)

    def test_report_save_default_location(self):
        proc = self.run_cli("report", "--all", "--save")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(list((self.data / "exports").glob("report-*.md"))), 1)

    def test_settings_persist_and_validate(self):
        self.assertEqual(self.run_cli("settings", "set", "report.default_days", "14").returncode, 0)
        rows = {r["key"]: r["value"] for r in self.json_cli("settings")["settings"]}
        self.assertEqual(rows["report.default_days"], 14)
        bad = self.run_cli("settings", "set", "report.default_days", "zero")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("INVALID_CONFIG", bad.stderr)
        self.assertEqual(self.run_cli("settings", "reset").returncode, 2)
        self.assertEqual(self.run_cli("settings", "reset", "--yes").returncode, 0)

    def test_invalid_config_file_is_actionable(self):
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "config.json").write_text(json.dumps({"config_version": 1, "values": {"report.default_days": "x"}}))
        proc = self.run_cli("usage")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("INVALID_CONFIG", proc.stderr)
        self.assertIn("Hint:", proc.stderr)

    def test_bad_pricing_file_degrades_gracefully(self):
        bad = self.tmp / "p.json"
        bad.write_text("{}")
        self.run_cli("settings", "set", "pricing.file", str(bad))
        data = self.json_cli("usage", "--all")
        self.assertFalse(data["cost"]["available"])
        self.assertTrue(any("Cost estimates unavailable" in w for w in data["warnings"]))

    def test_export_and_delete_own_data_only(self):
        self.json_cli("usage", "--all")
        out = self.tmp / "export.json"
        self.assertEqual(self.run_cli("settings", "export", "--output", str(out)).returncode, 0)
        self.assertIn("settings", json.loads(out.read_text()))
        before = tree_hash(self.claude_dir)
        self.assertEqual(self.run_cli("settings", "delete-data").returncode, 2)
        self.assertTrue(self.data.exists())
        self.assertEqual(self.run_cli("settings", "delete-data", "--yes").returncode, 0)
        self.assertFalse(self.data.exists())
        self.assertEqual(tree_hash(self.claude_dir), before)

    def test_doctor(self):
        checks = self.json_cli("doctor")
        status = {c["check"]: c["status"] for c in checks}
        self.assertEqual(status["Plugin files"], "ok")
        self.assertEqual(status["Python version"], "ok")


class ExperimentFlow(CLITestCase):
    def test_i_experiment_cli_flow(self):
        exp = self.json_cli("experiment", "start", "--name", "Narrow reads", "--change", "Ask for line ranges")
        eid = exp["experiment_id"]
        base = self.json_cli("experiment", "baseline", eid, "--from", "2026-10-20T10:00:00+00:00",
                             "--to", "2026-10-20T10:02:00+00:00")
        self.assertEqual(base["requests"], 2)
        follow = self.json_cli("experiment", "followup", eid, "--from", "2026-10-20T10:02:00+00:00",
                               "--to", "2026-10-20T10:10:00+00:00")
        self.assertEqual(follow["requests"], 3)
        shown = self.json_cli("experiment", "show", eid)
        cmp_ = shown["comparison"]
        self.assertEqual(cmp_["classification"], "directional")
        self.assertEqual(cmp_["quality"], "unknown")
        self.assertEqual(cmp_["differences"]["input_tokens"]["baseline_mean"], 30)
        self.assertEqual(cmp_["differences"]["input_tokens"]["followup_mean"], 15)
        text = self.run_cli("experiment", "show", eid).stdout
        self.assertIn("Quality is unknown", text)
        self.assertEqual(self.run_cli("experiment", "outcome", eid, "--quality", "preserved", "--completed", "yes").returncode, 0)
        self.assertEqual(self.run_cli("experiment", "delete", eid).returncode, 2)
        self.assertEqual(self.run_cli("experiment", "delete", eid, "--yes").returncode, 0)

    def test_invalid_comparison_models_differ(self):
        eid = self.json_cli("experiment", "start", "--name", "x", "--change", "y")["experiment_id"]
        self.json_cli("experiment", "baseline", eid, "--session", "synthetic-a1")
        self.json_cli("experiment", "followup", eid, "--session", "synthetic-b1")
        cmp_ = self.json_cli("experiment", "show", eid)["comparison"]
        self.assertEqual(cmp_["classification"], "invalid")

    def test_concurrent_writers(self):
        def start(i):
            return self.run_cli("experiment", "start", "--name", "c%d" % i, "--change", "z", "--json")

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(start, range(8)))
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        self.assertEqual(len(self.json_cli("experiment", "list")), 8)


class PrivacyOfflineRuntime(CLITestCase):
    def test_j_k_no_network_and_no_raw_content(self):
        guard = self.tmp / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(
            "import socket\n"
            "def _blocked(*a, **k):\n    raise RuntimeError('network access attempted')\n"
            "socket.socket = _blocked\nsocket.create_connection = _blocked\nsocket.getaddrinfo = _blocked\n")
        env = {"PYTHONPATH": str(guard)}
        for args in (["usage", "--all"], ["analyze", "--all"], ["report", "--all"], ["sources"], ["doctor"]):
            proc = self.run_cli(*args, env=env)
            self.assertIn(proc.returncode, (0, 1), proc.stderr)
            self.assertNotIn("network access attempted", proc.stderr)
            self.assertNotIn("internal error", proc.stderr)
        stored = "".join(p.read_text(errors="ignore") for p in self.data.rglob("*") if p.is_file())
        self.assertNotIn("[synthetic prompt]", stored)
        self.assertNotIn("[synthetic]", stored)

    @unittest.skipIf(ON_WINDOWS, "bin/boring-meter is a POSIX sh launcher; Windows has no /bin/sh")
    def test_missing_python_runtime(self):
        bindir = self.tmp / "bin"
        bindir.mkdir()
        for tool in ("dirname", "readlink"):
            src = shutil.which(tool)
            if src:
                os.symlink(src, str(bindir / tool))
        proc = subprocess.run(["/bin/sh", str(LAUNCHER), "usage"], capture_output=True, text=True,
                              env={"PATH": str(bindir), "HOME": str(self.tmp)})
        self.assertEqual(proc.returncode, 3)
        self.assertIn("RUNTIME_MISSING", proc.stderr)
        hook = subprocess.run(["/bin/sh", str(LAUNCHER), "--run-hook", "instructions-loaded"], capture_output=True,
                              text=True, input="{}", env={"PATH": str(bindir), "HOME": str(self.tmp)})
        self.assertEqual(hook.returncode, 0, "a hook must never fail when Python is missing")
        self.assertEqual(hook.stderr, "")


class LauncherTests(CLITestCase):
    with_fixtures = False

    def test_entry_point(self):
        proc = subprocess.run([sys.executable, str(ENTRY), "--version"], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("boring-meter", proc.stdout)

    def test_entry_point_ignores_unknown_hook(self):
        proc = subprocess.run([sys.executable, str(ENTRY), "--run-hook", "no-such-hook"], capture_output=True,
                              text=True, input="{}", timeout=60)
        self.assertEqual(proc.returncode, 0)

    @unittest.skipIf(ON_WINDOWS, "POSIX launcher test")
    def test_sh_launcher_skips_broken_python_stub(self):
        bindir = self.tmp / "bin"
        bindir.mkdir()
        stub = bindir / "python3"
        stub.write_text("#!/bin/sh\necho 'Python was not found; run without arguments to install from the Store' >&2\nexit 9009\n")
        stub.chmod(0o755)
        os.symlink(sys.executable, str(bindir / "python"))
        for tool in ("dirname", "readlink"):
            found = shutil.which(tool)
            if found:
                os.symlink(found, str(bindir / tool))
        proc = subprocess.run(["/bin/sh", str(LAUNCHER), "--version"], capture_output=True, text=True,
                              env={"PATH": str(bindir), "HOME": str(self.tmp)}, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("boring-meter", proc.stdout)

    @unittest.skipUnless(ON_WINDOWS, "Windows launcher test")
    def test_cmd_launcher_runs(self):
        proc = subprocess.run(["cmd", "/c", str(CMD_LAUNCHER), "--version"], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("boring-meter", proc.stdout)

    @unittest.skipUnless(ON_WINDOWS, "Windows launcher test")
    def test_cmd_launcher_without_python(self):
        system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        env = {"PATH": system32, "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows")}
        proc = subprocess.run(["cmd", "/c", str(CMD_LAUNCHER), "usage"], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertIn("RUNTIME_MISSING", proc.stderr)
        hook = subprocess.run(["cmd", "/c", str(CMD_LAUNCHER), "--run-hook", "instructions-loaded"], capture_output=True,
                              text=True, input="{}", env=env, timeout=120)
        self.assertEqual(hook.returncode, 0)

    @unittest.skipUnless(ON_WINDOWS and GIT_BASH.exists(), "needs Git for Windows")
    def test_sh_launcher_under_git_bash(self):
        launcher = str(LAUNCHER).replace("\\", "/")
        proc = subprocess.run([str(GIT_BASH), launcher, "--version"], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("boring-meter", proc.stdout)
        hook = subprocess.run([str(GIT_BASH), launcher, "--run-hook", "instructions-loaded"], capture_output=True,
                              text=True, input="{}", timeout=120)
        self.assertEqual(hook.returncode, 0, hook.stderr)


class HookScript(CLITestCase):
    def test_hook_through_launcher(self):
        self.run_cli("settings", "set", "collection.instruction_events", "true")
        target = self.tmp / "CLAUDE.md"
        target.write_text("one\n")
        payload = json.dumps({"session_id": "s9", "file_path": str(target), "hook_event_name": "InstructionsLoaded"})
        command = (["cmd", "/c", str(CMD_LAUNCHER)] if ON_WINDOWS else [str(LAUNCHER)]) + ["--run-hook", "instructions-loaded"]
        proc = subprocess.run(command, capture_output=True, text=True, input=payload, env=dict(os.environ), timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = (self.data / "events" / "instructions.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 1)

    def run_hook(self, payload: str):
        return subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
                              env=dict(os.environ), timeout=30)

    def test_hook_is_noop_when_disabled(self):
        target = self.tmp / "CLAUDE.md"
        target.write_text("x\n")
        proc = self.run_hook(json.dumps({"session_id": "s", "file_path": str(target), "hook_event_name": "InstructionsLoaded"}))
        self.assertEqual(proc.returncode, 0)
        self.assertFalse((self.data / "events" / "instructions.jsonl").exists())

    def test_hook_records_metadata_when_enabled(self):
        self.run_cli("settings", "set", "collection.instruction_events", "true")
        target = self.tmp / "CLAUDE.md"
        target.write_text("line one\nline two\n")
        payload = {"session_id": "s1", "file_path": str(target), "memory_type": "Project", "load_reason": "session_start",
                   "hook_event_name": "InstructionsLoaded"}
        self.assertEqual(self.run_hook(json.dumps(payload)).returncode, 0)
        self.assertEqual(self.run_hook("not json").returncode, 0)
        self.assertEqual(self.run_hook(json.dumps({"session_id": "s2"})).returncode, 0)  # missing file_path
        rows = [json.loads(l) for l in (self.data / "events" / "instructions.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line_count"], 2)
        self.assertNotIn("line one", json.dumps(rows))


class PerformanceBenchmark(CLITestCase):
    with_fixtures = False

    def test_usage_summary_10k_records(self):
        path = self.claude_dir / "projects" / "-synthetic-perf" / "synthetic-perf.jsonl"
        path.parent.mkdir(parents=True)
        with open(path, "w") as handle:
            for i in range(10000):
                handle.write(json.dumps({
                    "type": "assistant", "sessionId": "synthetic-perf-%d" % (i // 200), "cwd": "/synthetic/perf",
                    "timestamp": "2026-10-%02dT10:%02d:%02dZ" % (1 + i % 28, (i // 60) % 60, i % 60), "requestId": "r%d" % i,
                    "message": {"id": "m%d" % i, "model": "claude-opus-5-5", "content": [], "stop_reason": "end_turn",
                                "usage": {"input_tokens": 3, "output_tokens": 50, "cache_read_input_tokens": 1000,
                                          "cache_creation_input_tokens": 0, "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                          "ephemeral_1h_input_tokens": 0}}}}) + "\n")
        timings = []
        for _ in range(2):
            started = time.monotonic()
            proc = self.run_cli("usage", "--all", "--json")
            timings.append(time.monotonic() - started)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["requests"], 10000)
        sys.stderr.write("\n[benchmark] usage --all on 10,000 records: cold %.2fs, cached %.2fs\n" % tuple(timings))
        self.assertLess(timings[1], 2.0)


@unittest.skipUnless(shutil.which("claude"), "Claude Code CLI not installed")
class PluginValidation(unittest.TestCase):
    def test_plugin_validates_and_skills_discovered(self):
        proc = subprocess.run(["claude", "plugin", "validate", str(ROOT)], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Validation passed", proc.stdout + proc.stderr)
        proc = subprocess.run(["claude", "--plugin-dir", str(ROOT), "plugin", "details", "boring-meter"],
                              capture_output=True, text=True, timeout=120)
        out = proc.stdout + proc.stderr
        for skill in ("usage", "analyze", "optimize", "report", "experiment", "settings"):
            self.assertIn(skill, out)
        self.assertIn("InstructionsLoaded", out)
