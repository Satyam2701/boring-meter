from tests.helpers import TempEnvTestCase

from boring_meter import experiments
from boring_meter.errors import BMError


def run(total_in, out=100, model="claude-opus-5-5", cr=1000, cc=100, complete=True, session="synthetic-x", cost="0.0100"):
    totals = {"input_tokens": total_in, "output_tokens": out, "cache_read_tokens": cr, "cache_creation_tokens": cc}
    if not complete:
        totals["output_tokens"] = None
    total = sum(totals.values()) if complete else None
    return {"label": "session " + session, "requests": 10, "sessions": [session], "totals": totals, "total_tokens": total,
            "complete": complete, "models": [model], "claude_code_versions": ["2.1.299"],
            "cache_read_share": round(cr / total, 4) if complete else None, "cost_estimate": cost,
            "pricing_version": "v1" if cost else None, "first_ts": None, "last_ts": None}


class ExperimentTests(TempEnvTestCase):
    with_fixtures = False

    def make(self, base_runs, follow_runs, quality="unknown", done="unknown"):
        exp = experiments.start(self.data, "Trim CLAUDE.md", "Moved API notes to a path rule", "refactor")
        for i, r in enumerate(base_runs):
            r["sessions"] = ["synthetic-b%d" % i]
            experiments.add_run(self.data, exp["experiment_id"], "baseline", r)
        for i, r in enumerate(follow_runs):
            r["sessions"] = ["synthetic-f%d" % i]
            experiments.add_run(self.data, exp["experiment_id"], "followup", r)
        experiments.set_outcome(self.data, exp["experiment_id"], quality, "followup", done)
        return experiments.compare(experiments.get(self.data, exp["experiment_id"]))

    def test_missing_followup_is_invalid(self):
        self.assertEqual(self.make([run(500)], [])["classification"], "invalid")

    def test_model_change_is_invalid(self):
        c = self.make([run(500)], [run(400, model="claude-sonnet-5-5")])
        self.assertEqual(c["classification"], "invalid")
        self.assertTrue(any("Different models" in r for r in c["invalid_reasons"]))

    def test_incomplete_data_is_invalid(self):
        self.assertEqual(self.make([run(500)], [run(400, complete=False)])["classification"], "invalid")

    def test_single_runs_are_directional_and_quality_unknown_preserved(self):
        c = self.make([run(500)], [run(300)])
        self.assertEqual(c["classification"], "directional")
        self.assertEqual(c["quality"], "unknown")
        self.assertEqual(c["differences"]["input_tokens"]["difference"], -200)
        self.assertTrue(any("quality" in r.lower() for r in c["classification_reasons"]))

    def test_verified(self):
        c = self.make([run(5000), run(5100)], [run(3000), run(3050)], quality="preserved", done="yes")
        self.assertEqual(c["classification"], "verified")
        d = c["differences"]["total_tokens"]
        self.assertEqual(d["baseline_mean"], 5050 + 1200)
        self.assertEqual(d["followup_mean"], 3025 + 1200)
        self.assertIsNotNone(c["differences"]["cost_estimate"])

    def test_within_noise_is_inconclusive(self):
        c = self.make([run(1000), run(5000)], [run(3000), run(3100)], quality="preserved", done="yes")
        self.assertEqual(c["classification"], "inconclusive")

    def test_degraded_quality_is_inconclusive(self):
        c = self.make([run(5000), run(5100)], [run(3000), run(3050)], quality="degraded", done="yes")
        self.assertEqual(c["classification"], "inconclusive")

    def test_cache_share_difference_warns_and_blocks_verified(self):
        c = self.make([run(5000, cr=100), run(5100, cr=100)], [run(100, cr=4000), run(120, cr=4000)], quality="preserved", done="yes")
        self.assertEqual(c["classification"], "directional")
        self.assertTrue(any("cache" in w.lower() for w in c["warnings"]))

    def test_cost_difference_needs_same_pricing_version(self):
        a = run(500)
        b = run(400, cost=None)
        self.assertIsNone(self.make([a], [b])["differences"]["cost_estimate"])

    def test_empty_run_rejected(self):
        exp = experiments.start(self.data, "x", "y")
        empty = run(1)
        empty["requests"] = 0
        with self.assertRaises(BMError):
            experiments.add_run(self.data, exp["experiment_id"], "baseline", empty)

    def test_same_session_twice_rejected(self):
        exp = experiments.start(self.data, "x", "y")
        experiments.add_run(self.data, exp["experiment_id"], "baseline", run(1))
        with self.assertRaises(BMError):
            experiments.add_run(self.data, exp["experiment_id"], "followup", run(1))

    def test_validation_and_lookup(self):
        with self.assertRaises(BMError):
            experiments.start(self.data, "", "y")
        exp = experiments.start(self.data, "x", "y")
        with self.assertRaises(BMError):
            experiments.set_outcome(self.data, exp["experiment_id"], "great", None, None)
        with self.assertRaises(BMError):
            experiments.get(self.data, "does-not-exist")
        self.assertEqual(experiments.get(self.data, exp["experiment_id"][:6])["experiment_id"], exp["experiment_id"])
        experiments.delete(self.data, exp["experiment_id"])
        self.assertEqual(experiments.list_all(self.data), [])

    def test_measure_from_records(self):
        recs = [{"synthetic": False, "input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3, "cache_creation_tokens": 0,
                 "session_id": "s", "ts_epoch": 1.0, "model": "claude-opus-5-5", "provenance": {"claude_code_version": "2"},
                 "other_token_metrics": {"cache_creation_5m": 0, "cache_creation_1h": 0}, "speed": None,
                 "service_tier": None, "inference_geo": None}]
        m = experiments.measure(recs, "session s", None)
        self.assertTrue(m["complete"])
        self.assertEqual(m["total_tokens"], 6)
        recs[0]["output_tokens"] = None
        m = experiments.measure(recs, "session s", None)
        self.assertFalse(m["complete"])
        self.assertIsNone(m["totals"]["output_tokens"])
