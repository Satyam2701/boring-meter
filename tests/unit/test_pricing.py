import json
from decimal import Decimal

from tests.helpers import TempEnvTestCase
from tests.fixtures.build import EXPECTED

from boring_meter import aggregate, pricing
from boring_meter.errors import BMError
from boring_meter.timeutil import Period


def rec(model="claude-opus-5-5", inp=0, out=0, cr=0, cc=0, c5=None, c1=None, **extra):
    r = {"model": model, "synthetic": False, "input_tokens": inp, "output_tokens": out, "cache_read_tokens": cr,
         "cache_creation_tokens": cc, "other_token_metrics": {"cache_creation_5m": cc if c5 is None else c5,
                                                             "cache_creation_1h": 0 if c1 is None else c1},
         "speed": "standard", "service_tier": "standard", "inference_geo": "global"}
    r.update(extra)
    return r


class PricingTests(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.p = pricing.load_pricing(self.cfg())

    def price(self, r):
        return pricing.price_record(r, self.p)

    def test_fixture_session_cost_matches_hand_calculation(self):
        ds = self.dataset()
        records = [r for r in ds.records if r["session_id"] == "synthetic-a1"]
        cost = aggregate.cost_summary(records, self.p)
        self.assertEqual(Decimal(cost["amount"]), EXPECTED["a1_cost"].quantize(Decimal("0.0001")))
        exact = sum(self.price(r)[0] for r in records)
        self.assertEqual(exact, EXPECTED["a1_cost"])

    def test_one_hour_cache_write(self):
        self.assertEqual(self.price(rec(inp=1, out=10, cc=2000, c5=0, c1=2000))[0], EXPECTED["b1_1_cost"])

    def test_fast_mode(self):
        self.assertEqual(self.price(rec(inp=1000, out=1000, speed="fast"))[0], EXPECTED["b1_2_cost"])

    def test_fast_mode_unknown_for_model(self):
        cost, reason = self.price(rec(model="claude-sonnet-5-5", inp=1, speed="fast"))
        self.assertIsNone(cost)
        self.assertIn("fast", reason)

    def test_inference_geo_us(self):
        self.assertEqual(self.price(rec(model="claude-sonnet-5-5", inp=1000000, inference_geo="us"))[0], EXPECTED["b1_3_cost"])

    def test_geo_us_not_modeled_for_old_model(self):
        cost, _ = self.price(rec(model="claude-haiku-4-5", inp=10, inference_geo="us"))
        self.assertIsNone(cost)

    def test_unknown_model_never_priced(self):
        cost, reason = self.price(rec(model="claude-imaginary-9", inp=7, out=3))
        self.assertIsNone(cost)
        self.assertIn("no price", reason)

    def test_near_miss_model_name_not_aliased(self):
        cost, _ = self.price(rec(model="claude-opus-5-5-20990101", inp=7))
        self.assertIsNone(cost)

    def test_explicit_alias(self):
        cost, _ = self.price(rec(model="claude-haiku-4-5-20251001", inp=1000000))
        self.assertEqual(cost, Decimal(1))

    def test_missing_category_not_priced(self):
        r = rec(inp=4)
        r["output_tokens"] = None
        cost, reason = self.price(r)
        self.assertIsNone(cost)
        self.assertIn("missing", reason)

    def test_unknown_cache_duration_not_priced(self):
        r = rec(cc=100)
        r["other_token_metrics"] = {"cache_creation_5m": None, "cache_creation_1h": None}
        self.assertIsNone(self.price(r)[0])

    def test_zero_tokens_cost_zero(self):
        self.assertEqual(self.price(rec())[0], Decimal(0))

    def test_haiku_55_long_context_tier(self):
        short = self.price(rec(model="claude-haiku-5-5", inp=100000))[0]
        self.assertEqual(short, Decimal(100000) * Decimal("0.10") / Decimal(1000000))
        long_ = self.price(rec(model="claude-haiku-5-5", inp=60000, cr=50000, out=1000))[0]
        expected = (Decimal(60000) * Decimal("0.50") + Decimal(50000) * Decimal("0.05") + Decimal(1000) * Decimal("2.50")) / Decimal(1000000)
        self.assertEqual(long_, expected)

    def test_priority_tier_not_priced(self):
        self.assertIsNone(self.price(rec(inp=1, service_tier="priority"))[0])

    def test_synthetic_not_priced(self):
        self.assertIsNone(self.price(rec(model="<synthetic>", synthetic=True))[0])

    def test_pricing_disabled(self):
        self.assertIsNone(pricing.load_pricing(self.cfg(pricing__enabled=False)))

    def test_invalid_custom_pricing_file(self):
        bad = self.tmp / "pricing.json"
        bad.write_text(json.dumps({"schema_version": 2}))
        with self.assertRaises(BMError):
            pricing.load_pricing(self.cfg(pricing__file=str(bad)))

    def test_custom_pricing_alias_must_exist(self):
        data = json.loads(pricing.BUNDLED.read_text())
        data["aliases"]["x"] = "missing-model"
        bad = self.tmp / "pricing.json"
        bad.write_text(json.dumps(data))
        with self.assertRaises(BMError):
            pricing.load_pricing(self.cfg(pricing__file=str(bad)))

    def test_cost_summary_reports_unpriced_and_assumptions(self):
        ds = self.dataset()
        summary = aggregate.summarize(ds, Period(None, None, "all", "all", "UTC"), __import__("datetime").timezone.utc, self.p)
        cost = summary["cost"]
        self.assertFalse(cost["complete"])
        self.assertGreaterEqual(cost["records_unpriced"], 2)
        self.assertTrue(cost["assumptions"])
        self.assertIsNone(cost["source_reported_cost"])
