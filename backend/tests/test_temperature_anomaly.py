"""
Shared temperature-anomaly method (Insight card + heatmap). No network:
a fake archive returns controlled values so results are exact.
Run from backend/:   python -m unittest tests.test_temperature_anomaly -v
"""
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import current_conditions as cc   # noqa: E402


class FakeArchive:
    """Baseline years: `base` °C every day. Recent period: `recent` °C.
    Records every call so cost can be asserted."""
    def __init__(self, base=20.0, recent=23.0, missing_years=(), drop_recent_tail=0):
        self.base, self.recent, self.missing, self.drop = base, recent, set(missing_years), drop_recent_tail
        self.calls = []

    def __call__(self, points, start, end):
        self.calls.append((len(points), start, end))
        if end.year in self.missing:
            raise ConnectionError("year unavailable")
        is_recent = end.year >= 2026
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        if is_recent and self.drop:
            days = days[:-self.drop]
        val = self.recent if is_recent else self.base
        # value depends on the LOCATION (like a real archive), not the request position
        return [{d.isoformat(): val + 0.01 * lat for d in days} for lat, _ in points]


class TestSharedAnomaly(unittest.TestCase):
    TODAY = date(2026, 10, 3)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(cc, "_BASELINE_DIR", Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_exact_value_and_window(self):
        fake = FakeArchive(base=20.0, recent=23.0)
        r = cc.compute_anomalies([(21.1, 79.1)], today=self.TODAY, fetch=fake)[0]
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["anomaly_c"], 3.0)
        self.assertEqual(r["baseline_years_used"], 30)
        end = self.TODAY - timedelta(days=cc.ARCHIVE_LAG_DAYS)
        self.assertEqual(r["window_end"], end.isoformat())
        self.assertEqual(r["window_start"], (end - timedelta(days=6)).isoformat())

    def test_cost_is_31_requests_not_30_years_of_days(self):
        fake = FakeArchive()
        cc.compute_anomalies([(21.1, 79.1)], today=self.TODAY, fetch=fake)
        self.assertEqual(len(fake.calls), 31)                    # 1 recent + 30 baseline years
        for _, s, e in fake.calls:
            self.assertLessEqual((e - s).days + 1, 14)          # each <= 2 weeks per location

    def test_baseline_cached_on_disk(self):
        cc.compute_anomalies([(21.1, 79.1)], today=self.TODAY, fetch=FakeArchive())
        fake2 = FakeArchive()
        r = cc.compute_anomalies([(21.1, 79.1)], today=self.TODAY, fetch=fake2)[0]
        self.assertEqual(len(fake2.calls), 1)                    # only the recent window
        self.assertEqual(r["anomaly_c"], 3.0)

    def test_grid_uses_same_method_in_shared_requests(self):
        pts = [(0.0, 0.0), (20.0, 40.0), (40.0, -100.0)]
        fake = FakeArchive()
        res = cc.compute_anomalies(pts, today=self.TODAY, fetch=fake)
        self.assertEqual(len(fake.calls), 31)                    # not 3 x 31
        self.assertTrue(all(c[0] == 3 for c in fake.calls))
        single = cc.compute_anomalies([pts[1]], today=self.TODAY, fetch=FakeArchive())[0]
        self.assertEqual(res[1]["anomaly_c"], single["anomaly_c"])   # heatmap cell == Insight value

    def test_too_few_baseline_years_is_unavailable(self):
        fake = FakeArchive(missing_years=range(1991, 1997))      # 6 missing -> 24 left
        r = cc.compute_anomalies([(1.0, 1.0)], today=self.TODAY, fetch=fake)[0]
        self.assertEqual(r["status"], "unavailable")
        self.assertIsNone(r["anomaly_c"])
        self.assertIn("24 of 30", r["reason"])

    def test_window_across_new_year_and_leap_day(self):
        for today in (date(2026, 1, 8), date(2028, 3, 4)):      # Dec->Jan window; window containing 29 Feb 2028
            fake = FakeArchive()
            fake.__call__.__func__  # noqa
            # recent years are >= 2026 in the fake; 2028 also counts as recent
            r = cc.compute_anomalies([(5.0, 5.0)], today=today, fetch=fake)[0]
            self.assertEqual(r["status"], "ok", (today, r.get("reason")))

    def test_tail_nulls_shift_window(self):
        fake = FakeArchive(drop_recent_tail=2)
        r = cc.compute_anomalies([(2.0, 2.0)], today=self.TODAY, fetch=fake)[0]
        end = self.TODAY - timedelta(days=cc.ARCHIVE_LAG_DAYS + 2)
        self.assertEqual(r["window_end"], end.isoformat())

    def test_recent_failure_reports_reason(self):
        def boom(*a):
            raise ConnectionError("down")
        r = cc.compute_anomalies([(1.0, 1.0)], today=self.TODAY, fetch=boom)[0]
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("not available", r["reason"])


if __name__ == "__main__":
    unittest.main()


class TestRateLimitsAndGrid(unittest.TestCase):
    """Live failure on 4 Oct 2026: the 126-point heatmap sent ~750 calls in
    one burst (6 parallel x 126 locations) and hit Open-Meteo's 600/min limit."""
    TODAY = date(2026, 10, 3)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(cc, "_BASELINE_DIR", Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_429_is_recognised(self):
        from unittest.mock import MagicMock
        resp = MagicMock(status_code=429, text='{"reason":"Minutely API request limit exceeded"}')
        with patch.object(cc.requests, "get", return_value=resp):
            with self.assertRaises(cc.RateLimited):
                cc._archive_daily_mean([(0.0, 0.0)], date(2026, 9, 1), date(2026, 9, 7))

    def test_rate_limited_years_are_retried(self):
        base = FakeArchive()
        failed = set()
        def flaky(points, s, e):
            if e.year < 2026 and e.year % 3 == 0 and e.year not in failed:
                failed.add(e.year)
                raise cc.RateLimited("minutely limit")
            return base(points, s, e)
        sleeps = []
        r = cc.compute_anomalies([(1.0, 1.0)], today=self.TODAY, fetch=flaky, sleep=sleeps.append)[0]
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["baseline_years_used"], 30)
        self.assertTrue(failed)
        self.assertTrue(all(sv >= 60 for sv in sleeps))        # waited for the minute window to reset

    def test_paced_mode_is_sequential_with_gap_and_reports_progress(self):
        sleeps, prog = [], []
        cc.compute_anomalies([(0.0, 0.0), (20.0, 20.0)], today=self.TODAY, fetch=FakeArchive(),
                             pace_s=20, sleep=sleeps.append, progress=lambda d, t: prog.append((d, t)))
        self.assertEqual(sleeps.count(20), 29)                  # gaps between the 30 baseline requests
        self.assertEqual(prog[-1], (31, 31))

    def test_grid_builds_in_background_and_is_served_from_disk(self):
        from services import climate
        gridfile = Path(self.tmp.name) / "heatmap_grid.json"
        def fake_compute(points, pace_s, progress, window_end):
            self.assertEqual(pace_s, climate.GRID_PACE_S)
            self.assertEqual(window_end.weekday(), 6)            # heatmap uses a fixed week ending Sunday
            return cc.compute_anomalies(points, today=self.TODAY, fetch=FakeArchive(), pace_s=0, window_end=window_end)
        with patch.object(climate, "_GRID_FILE", gridfile):
            first = climate.get_climate_geojson(start_build=False)
            self.assertEqual(first["metadata"]["status"], "building")
            self.assertEqual(first["features"], [])
            climate._grid_state["running"] = True
            climate._build_grid(compute=fake_compute)
            self.assertFalse(climate._grid_state["running"])
            served = climate.get_climate_geojson(start_build=False)
            self.assertEqual(served["metadata"]["status"], "ok")
            self.assertEqual(served["metadata"]["points_ok"], served["metadata"]["points_total"])
            self.assertEqual(served["metadata"]["baseline_period"], "1991-2020")
            # heatmap cell value == Insight value for the same point (same method)
            f0 = served["features"][0]
            lon, lat = f0["geometry"]["coordinates"]
            week_end = date.fromisoformat(served["metadata"]["requested_end"])
            single = cc.compute_anomalies([(lat, lon)], today=self.TODAY, fetch=FakeArchive(), window_end=week_end)[0]
            self.assertEqual(f0["properties"]["value"], single["anomaly_c"])     # same method, same week
            self.assertIn("weekly", served["metadata"]["window_type"])

    def test_failed_build_reports_error_not_fake_map(self):
        from services import climate
        def failing(points, pace_s, progress, window_end):
            return [{"status": "unavailable", "reason": "rate limited"} for _ in points]
        with patch.object(climate, "_GRID_FILE", Path(self.tmp.name) / "g.json"):
            climate._grid_state["running"] = True
            climate._build_grid(compute=failing)
            res = climate.get_climate_geojson(start_build=False)
            self.assertEqual(res["metadata"]["status"], "error")
            self.assertIn("rate limited", res["metadata"]["build"]["error"])
            self.assertEqual(res["features"], [])
        climate._grid_state["error"] = None


class TestWeeklyHeatmapRollingInsight(unittest.TestCase):
    """Heatmap = fixed Mon-Sun week, rebuilt weekly; Insight = latest rolling 7 days."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(cc, "_BASELINE_DIR", Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_last_complete_week_end_is_a_sunday_within_the_archive(self):
        for d in range(14):
            today = date(2026, 10, 1) + timedelta(days=d)
            end = cc.last_complete_week_end(today)
            latest = today - timedelta(days=cc.ARCHIVE_LAG_DAYS)
            self.assertEqual(end.weekday(), 6)
            self.assertTrue(latest - timedelta(days=6) <= end <= latest, (today, end))

    def test_week_end_changes_only_once_a_week(self):
        ends = {cc.last_complete_week_end(date(2026, 10, 1) + timedelta(days=d)) for d in range(7)}
        self.assertLessEqual(len(ends), 2)

    def test_fixed_week_window(self):
        we = date(2026, 9, 27)
        r = cc.compute_anomalies([(1.0, 1.0)], today=date(2026, 10, 3), fetch=FakeArchive(), window_end=we)[0]
        self.assertEqual((r["window_start"], r["window_end"]), ("2026-09-21", "2026-09-27"))
        self.assertEqual(r["status"], "ok")

    def test_incomplete_week_is_unavailable_not_shifted(self):
        we = date(2026, 9, 27)
        fake = FakeArchive(drop_recent_tail=1)
        r = cc.compute_anomalies([(1.0, 1.0)], today=date(2026, 10, 3), fetch=fake, window_end=we)[0]
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("whole week", r["reason"])

    def test_insight_still_uses_latest_rolling_days(self):
        today = date(2026, 10, 3)
        r = cc.compute_anomalies([(1.0, 1.0)], today=today, fetch=FakeArchive())[0]
        self.assertEqual(r["window_end"], (today - timedelta(days=cc.ARCHIVE_LAG_DAYS)).isoformat())

    def test_grid_not_rebuilt_within_the_same_week(self):
        from services import climate
        gf = Path(self.tmp.name) / "grid.json"
        with patch.object(climate, "_GRID_FILE", gf):
            climate._save_grid({"type": "FeatureCollection", "features": [{"x": 1}],
                                "metadata": {"requested_end": cc.last_complete_week_end().isoformat()}})
            started = []
            with patch.object(climate.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: started.append(1)})()):
                res = climate.get_climate_geojson()
            self.assertEqual(started, [])
            self.assertEqual(res["metadata"]["status"], "ok")


class TestHeatmapDropped(unittest.TestCase):
    def test_no_background_build_is_ever_started(self):
        from services import climate
        self.assertFalse(climate.HEATMAP_ENABLED)
        with tempfile.TemporaryDirectory() as d, patch.object(climate, "_GRID_FILE", Path(d) / "none.json"):
            started = []
            with patch.object(climate.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: started.append(1)})()):
                climate.get_climate_geojson()
            self.assertEqual(started, [])

    def test_insight_anomaly_unaffected(self):
        r = cc.compute_anomalies([(61.4, 99.7)], today=date(2026, 10, 5), fetch=FakeArchive())[0]
        self.assertEqual(r["status"], "ok")
