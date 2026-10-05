"""
Regression tests: the 26 Aug 2026 Rasuwa / Bhote Koshi disaster must be
shown correctly. Uses fixtures trimmed from the REAL GDACS/USGS responses
(see tests/fixtures/rasuwa_2026.py). No network access.

Run from backend/:   python -m unittest tests.test_disasters_rasuwa -v
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import disasters as d                  # noqa: E402
from tests.fixtures import rasuwa_2026 as fx          # noqa: E402

USGS_ORIGIN = (28.271, 85.515)
RASUWAGADHI = (28.2774, 85.3777)
GDACS_CENTROID = (27.2953, 85.3649)


def _resp(payload, status=200):
    m = MagicMock()
    m.status_code = status
    m.content = b"x"
    m.json.return_value = payload
    m.raise_for_status = lambda: None
    return m


class TestNormalization(unittest.TestCase):
    def test_gdacs_flood_point_is_marked_approximate(self):
        ev = d.normalize_gdacs_feature(fx.GDACS_SEARCH["features"][1])
        self.assertEqual(ev["id"], "gdacs:FL:1104124")
        self.assertEqual(ev["alert"], "red")
        self.assertEqual(ev["point_kind"], "area_centre")
        self.assertIn("not where the event happened", ev["point_note"])

    def test_magnitude_zero_severity_is_dropped(self):
        ev = d.normalize_gdacs_feature(fx.GDACS_SEARCH["features"][1])
        self.assertIsNone(ev["severity_text"])

    def test_gdacs_dates_are_utc(self):
        ev = d.normalize_gdacs_feature(fx.GDACS_SEARCH["features"][1])
        self.assertEqual(ev["start"], "2026-08-26T01:00:00Z")
        self.assertEqual(ev["end"], "2026-09-01T14:00:00Z")

    def test_usgs_is_a_landslide_not_an_earthquake(self):
        ev = d.normalize_usgs_feature(fx.USGS_LIST_FEATURE)
        self.assertEqual(ev["hazard"], "landslide")
        self.assertEqual(ev["hazard_label"], "Landslide (seismic signal)")
        self.assertEqual(ev["magnitude"], 5.2)
        self.assertEqual(ev["start"], "2026-08-26T02:52:10Z")


class TestGeometry(unittest.TestCase):
    def setUp(self):
        self.poly = d.select_affected_polygon(fx.GDACS_GEOMETRY)

    def test_affected_polygon_chosen_global_dropped(self):
        self.assertEqual(self.poly["label"], "Affected area")
        self.assertIn("NOT the flooded extent", self.poly["caveat"])

    def test_gdacs_centroid_lies_in_southern_patch(self):
        self.assertTrue(d.point_in_geometry(*GDACS_CENTROID, self.poly["geometry"]))

    def test_centroid_is_about_110km_from_the_disaster(self):
        km = d.haversine_km(*GDACS_CENTROID, *RASUWAGADHI)
        self.assertTrue(100 < km < 120, km)

    def test_usgs_origin_is_outside_polygon_but_within_buffer(self):
        self.assertFalse(d.point_in_geometry(*USGS_ORIGIN, self.poly["geometry"]))
        dist = d.distance_to_geometry_km(*USGS_ORIGIN, self.poly["geometry"])
        self.assertTrue(5.5 < dist < 8.0, dist)          # ~6.6 km
        self.assertLessEqual(dist, d.LINK_POLY_BUFFER_KM)


class TestImpacts(unittest.TestCase):
    def setUp(self):
        self.detail = d.parse_gdacs_detail(fx.GDACS_EVENTDATA)
        self.rows = {(r["label"], r["country"]): r for r in self.detail["impacts"]}

    def test_deaths_per_country_not_summed(self):
        self.assertEqual(self.rows[("Deaths", "Nepal")]["value"], 939)
        self.assertEqual(self.rows[("Deaths", "China")]["value"], 16)

    def test_affected_relabelled_as_missing_latest_only(self):
        nepal = self.rows[("Missing / out of contact", "Nepal")]
        self.assertEqual(nepal["value"], 4247)            # latest period (31 Aug), tie with 3925 -> highest
        self.assertIsNotNone(nepal["note"])
        self.assertEqual(self.rows[("Missing / out of contact", "China")]["value"], 564)
        self.assertNotIn(("Affected", "Nepal"), self.rows)

    def test_cumulative_rescued_uses_latest_not_sum(self):
        self.assertEqual(self.rows[("Rescued", "Nepal")]["value"], 10451)

    def test_other_rows(self):
        self.assertEqual(self.rows[("Evacuated", "Nepal")]["value"], 3458)
        self.assertEqual(self.rows[("Injured", "Nepal")]["value"], 279)
        self.assertEqual(self.rows[("Bridges destroyed", "Nepal")]["value"], 77)

    def test_alert_explained_and_as_of_present(self):
        self.assertIn("not an official warning", self.detail["alert_explanation"])
        self.assertEqual(self.detail["impacts_as_of"], "2026-09-01")


class TestUsgsDetail(unittest.TestCase):
    def test_reclassification_and_impact_text(self):
        det = d.parse_usgs_detail(fx.USGS_FEATURE)
        self.assertIn("M4.4 earthquake", det["reclassification"])
        self.assertEqual(det["event"]["horizontal_error_km"], 13.39)
        self.assertEqual(det["impact_as_of"], "September 20, 2026")
        self.assertIn("1,451 people killed", det["impact_text"])

    def test_feature_collection_wrapper_also_accepted(self):
        det = d.parse_usgs_detail({"type": "FeatureCollection", "features": [fx.USGS_FEATURE]})
        self.assertEqual(det["status"], "ok")


class TestLinkingAndList(unittest.TestCase):
    """The headline acceptance test: one linked Red event at the USGS origin."""

    def _fake_get(self, url, params=None, timeout=None):
        if "geteventlist/SEARCH" in url:
            return _resp(fx.GDACS_SEARCH) if params.get("pagenumber") == 1 else _resp({"features": []})
        if "getgeometry" in url:
            return _resp(fx.GDACS_GEOMETRY)
        if "earthquake.usgs.gov" in url:
            if params.get("eventtype") == "landslide":
                return _resp({"features": [fx.USGS_LIST_FEATURE]})
            return _resp({"features": []})
        raise AssertionError(f"unexpected URL {url}")

    def setUp(self):
        d._cache.clear()

    def test_rasuwa_is_one_linked_red_event_at_usgs_origin(self):
        with patch.object(d.requests, "get", side_effect=self._fake_get):
            res = d.list_disasters(datetime(2026, 8, 20, tzinfo=timezone.utc),
                                   datetime(2026, 9, 10, tzinfo=timezone.utc),
                                   list(d.HAZARD_LABELS), "all", 5.0)
        first = res["groups"][0]
        self.assertEqual(first["primary"]["id"], "gdacs:FL:1104124")   # Red sorts first
        self.assertEqual(len(first["related"]), 1)
        rel = first["related"][0]
        self.assertEqual(rel["event"]["id"], "usgs:us7000tbwb")
        self.assertEqual(rel["relation"], "linked")
        self.assertEqual((first["marker"]["lat"], first["marker"]["lon"]), USGS_ORIGIN)
        self.assertEqual(first["marker"]["kind"], "usgs_origin")
        # USGS event is not duplicated as its own group
        self.assertFalse(any(g["primary"]["id"] == "usgs:us7000tbwb" for g in res["groups"]))
        self.assertEqual(res["sources"]["GDACS"]["status"], "ok")
        self.assertEqual(res["sources"]["USGS"]["status"], "ok")
        # Nepal is historical: GDACS iscurrent=false -> Previous, never Active
        self.assertEqual(first["status"], "ended")
        self.assertEqual(first["severity"], "red")

    def test_out_of_window_events_filtered(self):
        with patch.object(d.requests, "get", side_effect=self._fake_get):
            res = d.list_disasters(datetime(2026, 10, 1, tzinfo=timezone.utc),
                                   datetime(2026, 10, 2, tzinfo=timezone.utc),
                                   ["flood"], "all", 5.0)
        self.assertEqual(res["count"], 0)

    def test_without_polygon_it_is_only_possibly_related_and_not_merged(self):
        # Audit fix B: an unconfirmed match must not swallow the USGS event.
        g = d.normalize_gdacs_feature(fx.GDACS_SEARCH["features"][1])
        u = d.normalize_usgs_feature(fx.USGS_LIST_FEATURE)
        groups = d.link_events([g], [u], geometry_lookup=None)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["related"], [])
        self.assertEqual(groups[0]["possible_links"][0]["id"], "usgs:us7000tbwb")
        self.assertEqual(groups[1]["possible_links"][0]["id"], "gdacs:FL:1104124")
        self.assertEqual(groups[0]["marker"]["kind"], "area_centre")

    def test_gdacs_down_is_reported_and_usgs_still_shown(self):
        def fake(url, params=None, timeout=None):
            if "gdacs" in url:
                raise ConnectionError("down")
            return self._fake_get(url, params, timeout)
        with patch.object(d.requests, "get", side_effect=fake):
            res = d.list_disasters(datetime(2026, 8, 20, tzinfo=timezone.utc),
                                   datetime(2026, 9, 10, tzinfo=timezone.utc),
                                   list(d.HAZARD_LABELS), "all", 5.0)
        self.assertEqual(res["sources"]["GDACS"]["status"], "error")
        self.assertIn("down", res["sources"]["GDACS"]["message"])
        self.assertEqual(res["groups"][0]["primary"]["id"], "usgs:us7000tbwb")


def _g(etype, eid, lat, lon, start, end, alert, sev="", current="false"):
    return d.normalize_gdacs_feature({"geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {
        "eventtype": etype, "eventid": eid, "alertlevel": alert, "country": "X", "fromdate": start,
        "todate": end, "iscurrent": current, "severitydata": {"severity": 0, "severitytext": sev}}})


def _u(uid, lat, lon, iso, mag, typ="earthquake", alert=None):
    ms = int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    return d.normalize_usgs_feature({"id": uid, "geometry": {"type": "Point", "coordinates": [lon, lat, 10]},
                                     "properties": {"mag": mag, "place": "p", "time": ms, "type": typ,
                                                    "alert": alert, "magType": "mww"}})


class TestDeduplicationAudit(unittest.TestCase):
    """Synthetic records (not real events) reproducing the 4 audit bugs."""

    def test_A_earthquake_dedup_runs_before_area_links(self):
        tc = _g("TC", 1, 35.0, 140.0, "2026-09-01T00:00:00", "2026-09-03T00:00:00", "Red")
        eq = _g("EQ", 2, 35.3, 140.4, "2026-09-02T00:00:00", "2026-09-02T00:00:00", "Orange", "Magnitude 6.1M")
        uq = _u("us1", 35.31, 140.41, "2026-09-02T00:01:00", 6.0, alert="yellow")
        groups = {g["primary"]["id"]: g for g in d.link_events([tc, eq], [uq])}
        self.assertEqual(groups["gdacs:TC:1"]["related"], [])
        self.assertEqual(groups["gdacs:EQ:2"]["related"][0]["relation"], "same_event")
        self.assertEqual(len(groups), 2)

    def test_B_unrelated_quake_near_flood_stays_listed(self):
        fl = _g("FL", 3, 20.0, 80.0, "2026-09-01T00:00:00", "2026-09-04T00:00:00", "Orange")
        uq = _u("us2", 21.2, 80.5, "2026-09-01T01:00:00", 5.2)
        ids = [g["primary"]["id"] for g in d.link_events([fl], [uq])]
        self.assertIn("usgs:us2", ids)

    def test_C_group_severity_is_max_of_same_event_records(self):
        eq = _g("EQ", 4, 0, 100, "2026-09-01T00:00:00", "2026-09-01T00:00:00", "Green", "Magnitude 6.5M")
        uq = _u("us3", 0.05, 100.05, "2026-09-01T00:00:00", 6.5, alert="orange")
        g = d.link_events([eq], [uq])
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["severity"], "orange")

    def test_D_gdacs_earthquake_magnitude_parsed(self):
        eq = _g("EQ", 5, 0, 0, "2026-09-01T00:00:00", "2026-09-01T00:00:00", "Orange", "Magnitude 6.1M, Depth:10km")
        self.assertEqual(eq["magnitude"], 6.1)

    def test_magnitude_mismatch_is_not_merged(self):
        eq = _g("EQ", 6, 0, 0, "2026-09-01T00:00:00", "2026-09-01T00:00:00", "Orange", "Magnitude 7.0M")
        uq = _u("us4", 0.01, 0.01, "2026-09-01T00:00:00", 5.5)
        self.assertEqual(len(d.link_events([eq], [uq])), 2)

    def test_duplicate_gdacs_records_across_pages_dropped(self):
        page = {"features": [fx.GDACS_SEARCH["features"][1]] * 100}
        def fake(url, params=None, timeout=None):
            return _resp(page) if params["pagenumber"] <= 2 else _resp({"features": []})
        with patch.object(d.requests, "get", side_effect=fake):
            events, _ = d.fetch_gdacs(datetime(2026, 8, 1, tzinfo=timezone.utc),
                                      datetime(2026, 9, 1, tzinfo=timezone.utc), ["FL"], ["red"])
        self.assertEqual(len(events), 1)


class TestActiveStatus(unittest.TestCase):
    NOW = datetime.fromisoformat(fx.SEARCH_RETRIEVED_AT.replace("Z", "+00:00"))

    def _status(self, ev):
        return d.group_status({"primary": ev}, self.NOW)

    def test_real_thailand_current_flood_is_active(self):
        st, basis = self._status(d.normalize_gdacs_feature(fx.GDACS_THAILAND_CURRENT))
        self.assertEqual(st, "active", basis)

    def test_real_india_flood_not_current_is_previous(self):
        st, _ = self._status(d.normalize_gdacs_feature(fx.GDACS_INDIA_NOT_CURRENT))
        self.assertEqual(st, "ended")

    def test_nepal_is_previous(self):
        st, _ = self._status(d.normalize_gdacs_feature(fx.GDACS_SEARCH["features"][1]))
        self.assertEqual(st, "ended")

    def test_usgs_is_never_active_even_if_minutes_old(self):
        u = _u("us9", 0, 0, "2026-10-02T09:20:00", 6.8, alert="orange")
        st, basis = self._status(u)
        self.assertEqual(st, "ended")
        self.assertIn("instantaneous", basis)

    def test_current_flag_on_instantaneous_earthquake_is_not_active(self):
        eq = _g("EQ", 7, 0, 0, "2026-10-01T00:00:00", "2026-10-01T00:00:00", "Red", "Magnitude 7M", current="true")
        self.assertEqual(self._status(eq)[0], "ended")

    def test_stale_current_flag_is_not_active(self):
        tc = _g("TC", 8, 0, 0, "2026-09-20T00:00:00", "2026-09-28T00:00:00", "Red", current="true")
        st, basis = self._status(tc)
        self.assertEqual(st, "ended")
        self.assertIn("treated as ended", basis)

    def test_current_cyclone_with_recent_advisory_is_active(self):
        tc = _g("TC", 9, 0, 0, "2026-09-28T00:00:00", "2026-10-02T06:00:00", "Orange", current="true")
        self.assertEqual(self._status(tc)[0], "active")


if __name__ == "__main__":
    unittest.main()
