from datetime import datetime, timezone, timedelta

from tests.helpers import TempEnvTestCase
from tests.fixtures.build import EXPECTED

from boring_meter import aggregate
from boring_meter.errors import BMError
from boring_meter.timeutil import Period, parse_ts, resolve_period, resolve_timezone

UTC = timezone.utc
ALL = Period(None, None, "All", "all", "UTC")


class AggregateTests(TempEnvTestCase):
    def summary(self, **kw):
        return aggregate.summarize(self.dataset(), kw.pop("period", ALL), UTC, None, **kw)

    def test_session_totals_match_expected(self):
        s = self.summary(session_id="synthetic-a1")
        for key, value in EXPECTED["a1"].items():
            self.assertEqual(s["totals"][key]["sum"], value, key)
            self.assertEqual(s["totals"][key]["missing"], 0)
        self.assertEqual(s["combined_tokens"]["sum"], sum(EXPECTED["a1"].values()))

    def test_missing_output_is_unknown_not_zero(self):
        s = self.summary(session_id="synthetic-a2")
        self.assertEqual(s["totals"]["output_tokens"]["missing"], 1)
        self.assertEqual(s["totals"]["output_tokens"]["known"], 3)
        self.assertEqual(s["combined_tokens"]["records_excluded"], 1)
        self.assertEqual(s["sessions_with_incomplete_data"], 1)

    def test_synthetic_excluded_and_counted(self):
        s = self.summary()
        self.assertEqual(s["requests"], EXPECTED["requests"])
        self.assertEqual(s["synthetic_messages_excluded"], 1)

    def test_coverage_partial_with_bad_lines(self):
        s = self.summary()
        self.assertEqual(s["coverage"], "partial")
        self.assertTrue(any("malformed" in n for n in s["coverage_notes"]))

    def test_period_before_data_marked_incomplete(self):
        start = datetime(2026, 10, 1, tzinfo=UTC)
        s = self.summary(period=Period(start, None, "x", "range", "UTC"))
        self.assertTrue(any("earliest available record" in n for n in s["coverage_notes"]))

    def test_empty_period_is_none_not_zero(self):
        p = Period(datetime(2030, 1, 1, tzinfo=UTC), None, "future", "range", "UTC")
        s = self.summary(period=p)
        self.assertEqual(s["requests"], 0)
        self.assertEqual(s["coverage"], "none")

    def test_by_day_uses_timezone(self):
        ds = self.dataset()
        tz = timezone(timedelta(hours=-12))
        s = aggregate.summarize(ds, ALL, tz, None, session_id="synthetic-a2")
        self.assertEqual(list(s["by_day"].keys()), ["2026-10-20"])

    def test_future_timestamps_flagged(self):
        now = datetime(2026, 10, 1, tzinfo=UTC)
        s = aggregate.summarize(self.dataset(), ALL, UTC, None, now=now)
        self.assertTrue(any("future" in n for n in s["coverage_notes"]))

    def test_project_filter(self):
        s = self.summary(project="/synthetic/beta")
        self.assertEqual(s["requests"], 6)


class TimeTests(TempEnvTestCase):
    with_fixtures = False

    def test_parse_variants(self):
        self.assertEqual(parse_ts("2026-10-20T10:00:00Z"), datetime(2026, 10, 20, 10, tzinfo=UTC))
        self.assertEqual(parse_ts("2026-10-20T15:30:00+05:30"), datetime(2026, 10, 20, 10, tzinfo=UTC))
        self.assertIsNotNone(parse_ts("2026-10-20T10:00:00.123Z"))
        self.assertIsNone(parse_ts("2026-10-20T10:00:00"))  # naive: offset unknown
        self.assertIsNone(parse_ts("yesterday"))
        self.assertIsNone(parse_ts(None))

    def test_week_boundaries(self):
        tz = resolve_timezone("Asia/Kolkata")
        now = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)  # 08:30 local
        p = resolve_period(week=True, tz=tz, now=now)
        self.assertEqual(p.start, datetime(2026, 10, 21, 18, 30, tzinfo=UTC))  # Oct 22 00:00 local
        self.assertIsNone(p.end)
        self.assertTrue(p.contains(datetime(2026, 10, 21, 18, 30, tzinfo=UTC)))
        self.assertFalse(p.contains(datetime(2026, 10, 21, 18, 29, tzinfo=UTC)))

    def test_today(self):
        tz = resolve_timezone("UTC")
        p = resolve_period(today=True, tz=tz, now=datetime(2026, 10, 28, 15, tzinfo=UTC))
        self.assertEqual(p.start, datetime(2026, 10, 28, tzinfo=UTC))

    def test_since_until_inclusive(self):
        tz = resolve_timezone("UTC")
        p = resolve_period(since="2026-10-01", until="2026-10-02", tz=tz)
        self.assertTrue(p.contains(datetime(2026, 10, 2, 23, 59, tzinfo=UTC)))
        self.assertFalse(p.contains(datetime(2026, 10, 3, tzinfo=UTC)))

    def test_dst_aware_days(self):
        tz = resolve_timezone("America/New_York")
        now = datetime(2026, 11, 3, 12, tzinfo=UTC)  # DST ended Nov 1
        p = resolve_period(days=7, tz=tz, now=now)
        self.assertEqual(p.start, datetime(2026, 10, 28, 4, tzinfo=UTC))  # EDT midnight

    def test_conflicting_and_invalid(self):
        tz = resolve_timezone("UTC")
        with self.assertRaises(BMError):
            resolve_period(today=True, week=True, tz=tz)
        with self.assertRaises(BMError):
            resolve_period(since="2026-13-01", tz=tz)
        with self.assertRaises(BMError):
            resolve_period(since="2026-10-05", until="2026-10-01", tz=tz)
        with self.assertRaises(BMError):
            resolve_timezone("Mars/Olympus")
