"""
Historical Extremes tests (no network).
Run from backend/:   python -m unittest tests.test_historical -v
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import historical as h                     # noqa: E402
from tests.fixtures import historical_fixtures as fx      # noqa: E402

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


def _items(data=None):
    data = data or fx.ALL
    baseline = h.load_baseline()
    return h.assemble_items(h.build_ncei_disasters(data), baseline, True), baseline


class TestBaselineIntegrity(unittest.TestCase):
    def test_every_entry_is_sourced_and_consistent(self):
        b = h.load_baseline()
        ids = set()
        for e in b["entries"]:
            self.assertNotIn(e["id"], ids); ids.add(e["id"])
            self.assertTrue(e.get("figures"), e["id"])
            for f in e["figures"]:
                self.assertTrue(f.get("source") and f.get("url", "").startswith("https://"), (e["id"], f))
            loc = e["location"]
            self.assertTrue(-90 <= loc["lat"] <= 90 and -180 <= loc["lon"] <= 180, e["id"])
            d = e.get("deaths")
            if d:
                vals = [v for v in (d.get("low"), d.get("best"), d.get("high")) if v is not None]
                self.assertEqual(vals, sorted(vals), e["id"])
            self.assertIn(e["kind"], ("event", "overlay", "record_only", "heatwave"))
            if e["kind"] == "heatwave":
                self.assertIn(e["metric_type"], h.METRIC_LABELS, e["id"])
            if e["kind"] == "overlay":
                self.assertIn("match", e)

    def test_verified_dates_present_and_fresh(self):
        for e in h.load_baseline()["entries"]:
            age = (date.today() - date.fromisoformat(e["verified_on"])).days
            if age > 365:
                print(f"WARNING: baseline entry {e['id']} last verified {age} days ago — re-verify")
            self.assertGreaterEqual(age, 0)

    def test_records_point_to_existing_entries(self):
        b = h.load_baseline()
        ids = {e["id"] for e in b["entries"]}
        for r in b["records"]:
            self.assertIn(r["baseline_id"], ids)


class TestNormalisationAndLinking(unittest.TestCase):
    def test_place_formatting(self):
        self.assertEqual(h.format_place("CHINA:  HEBEI PROVINCE:  TANGSHAN"), "Tangshan, Hebei Province, China")

    def test_unpublished_records_dropped(self):
        ids = {d["id"] for d in h.build_ncei_disasters(fx.ALL)}
        self.assertNotIn("ncei-earthquakes-9007", ids)

    def test_linked_earthquake_and_tsunami_are_one_disaster_not_summed(self):
        d = next(x for x in h.build_ncei_disasters(fx.ALL) if any(m["ncei_id"] == 9500 for m in x["members"]))
        self.assertEqual(d["hazard"], "earthquake_tsunami")
        self.assertEqual(d["ncei_deaths"], 227899)          # max, not 227,899 + 1,000

    def test_three_way_volcano_tsunami_link(self):
        d = next(x for x in h.build_ncei_disasters(fx.ALL) if any(m["ncei_id"] == 9802 for m in x["members"]))
        self.assertEqual({m["kind"] for m in d["members"]}, {"volcanoes", "tsunamis"})


class TestOverlaysAndCasualties(unittest.TestCase):
    def setUp(self):
        self.items, _ = _items()
        self.by_base = {(i.get("baseline") or {}).get("id"): i for i in self.items if i.get("baseline")}

    def test_overlay_attaches_range_to_ncei_record(self):
        haiti = self.by_base["haiti-2010"]
        self.assertEqual(haiti["source"], "NCEI")
        cas = h.casualty_view(haiti)
        self.assertEqual((cas["low"], cas["high"]), (46190, 316000))
        self.assertEqual(cas["confidence"], "disputed")
        self.assertTrue(any("NCEI" in f["source"] for f in cas["figures"]))
        self.assertTrue(any("Daniell" in f["source"] for f in cas["figures"]))

    def test_tambora_best_is_oppenheimer_not_ncei_direct(self):
        cas = h.casualty_view(self.by_base["tambora-1815"])
        self.assertEqual(cas["rank_value"], 71000)
        self.assertEqual(cas["display"], "71,000–92,000")
        self.assertEqual(cas["best_note"], "Best estimate: at least 71,000")
        # NCEI's figure (a different measure) is listed separately, never merged into the range
        self.assertEqual(cas["low"], 71000)
        self.assertTrue(any(f["value"] == 11000 and "NCEI" in f["label"] for f in cas["figures"]))

    def test_standalone_baseline_events_present(self):
        for bid in ("china-floods-1931", "yellow-river-1887", "bhola-cyclone-1970", "nargis-2008"):
            self.assertEqual(self.by_base[bid]["source"], "Baseline")

    def test_overlay_survives_when_ncei_unavailable(self):
        items, _ = _items({"earthquakes": [], "tsunamis": [], "volcanoes": []})
        by = {(i.get("baseline") or {}).get("id"): i for i in items if i.get("baseline")}
        self.assertEqual(by["haiti-2010"]["source"], "Baseline")
        self.assertIsNone(h.casualty_view(by["haiti-2010"])["ncei"])

    def test_ncei_only_pre1900_is_marked_chronicle(self):
        antioch = next(i for i in self.items if i["id"] == "ncei-earthquakes-64")
        self.assertEqual(h.casualty_view(antioch)["confidence"], "chronicle")


class TestDeadliest(unittest.TestCase):
    def setUp(self):
        self.items, _ = _items()

    def test_since_1900_default_excludes_older_events(self):
        res = h.deadliest(self.items, "since1900", now=NOW)
        years = [p["year"] for p in res["items"]]
        self.assertTrue(all(y >= 1900 for y in years))
        titles = [p["title"] for p in res["items"]]
        self.assertIn("1931 China floods (Yangtze–Huai)", titles)

    def test_all_history_includes_1887_1556_tambora(self):
        titles = [p["title"] for p in h.deadliest(self.items, "all", now=NOW)["items"]]
        for t in ("1887 Yellow River flood", "1556 Shaanxi earthquake", "1815 eruption of Mount Tambora"):
            self.assertIn(t, titles)

    def test_preliminary_event_never_ranked(self):
        res = h.deadliest(self.items, "all", now=NOW)
        self.assertNotIn("ncei-earthquakes-9005", [p["id"] for p in res["items"]])
        self.assertEqual(res["pending_review"][0]["id"], "ncei-earthquakes-9005")

    def test_overlapping_ranges_flagged(self):
        res = {p["title"]: p for p in h.deadliest(self.items, "all", now=NOW)["items"]}
        flood87, flood31 = res["1887 Yellow River flood"], res["1931 China floods (Yangtze–Huai)"]
        # Not neighbours (Shaanxi ranks between them) but their ranges overlap.
        self.assertNotEqual(abs(flood87["rank"] - flood31["rank"]), 1)
        self.assertIn(flood31["rank"], flood87["overlaps_with"])
        self.assertTrue(flood87["rank_overlaps"] and flood31["rank_overlaps"])

    def test_rank_rule_best_then_ncei_then_low(self):
        res = {p["title"]: p for p in h.deadliest(self.items, "all", now=NOW)["items"]}
        self.assertEqual(res["1976 Tangshan earthquake"]["deaths"]["rank_value"], 242419)   # baseline best
        self.assertEqual(res["2010 Haiti earthquake"]["deaths"]["rank_value"], 136933)      # peer-reviewed median
        self.assertEqual(res["Earthquake — Haiyuan, Ningxia, China"]["deaths"]["rank_value"], 200000)  # NCEI only
        self.assertEqual(res["2008 Cyclone Nargis"]["deaths"]["rank_value"], 84537)         # lower bound


class TestListReview(unittest.TestCase):
    """Issues found reviewing the live lists on 3 Oct 2026."""
    def setUp(self):
        self.items, _ = _items()

    def test_tsunami_record_of_an_eruption_is_labelled_volcanic(self):
        pelee = next(d for d in h.build_ncei_disasters(fx.ALL) if d["year"] == 1902)
        self.assertEqual(pelee["hazard"], "volcano")
        self.assertEqual(pelee["ncei_deaths"], 28000)
        self.assertEqual(pelee["tsunami_deaths"], 0)

    def test_single_figure_events_not_flagged_by_others_ranges(self):
        res = {p["title"]: p for p in h.deadliest(self.items, "all", now=NOW)["items"]}
        self.assertFalse(res["Earthquake — Haiyuan, Ningxia, China"]["rank_overlaps"])
        self.assertTrue(res["2010 Haiti earthquake"]["rank_overlaps"])

    def test_tambora_reachable_in_all_history(self):
        titles = [p["title"] for p in h.deadliest(self.items, "all", now=NOW)["items"]]
        self.assertIn("1815 eruption of Mount Tambora", titles)
        self.assertEqual(h.DEADLIEST_LIMIT, 50)

    def test_new_baseline_entries_ranked_since_1900(self):
        titles = [p["title"] for p in h.deadliest(self.items, "since1900", now=NOW)["items"]]
        self.assertIn("1991 Bangladesh cyclone", titles)
        self.assertIn("1935 Yangtze flood", titles)

    def test_coverage_note_present(self):
        self.assertIn("may be incomplete", h.deadliest(self.items, "since1900", now=NOW)["coverage"])


class TestVolcanoAndCleanup(unittest.TestCase):
    """From the live volcano API check (4 Oct 2026) and the list review."""
    def setUp(self):
        self.items, _ = _items()
        self.dis = {d["id"]: d for d in h.build_ncei_disasters(fx.ALL)}

    def test_volcano_records_with_publish_false_are_kept(self):
        self.assertIn("ncei-volcanoes-64", self.dis)                      # real Merapi 1672
        self.assertEqual(self.dis["ncei-volcanoes-64"]["ncei_deaths"], 3000)

    def test_real_etna_1169_links_to_earthquake(self):
        etna = next(d for d in self.dis.values() if any(m["kind"] == "volcanoes" and m["ncei_id"] == 1 for m in d["members"]))
        self.assertEqual(etna["year"], 1169)

    def test_krakatau_is_eruption_and_tsunami(self):
        k = next(d for d in self.dis.values() if d["year"] == 1883)
        self.assertEqual(k["hazard"], "volcano_tsunami")

    def test_non_eruptive_event_excluded_from_eruption_records(self):
        gas = next(d for d in self.dis.values() if d["year"] == 1986)
        self.assertEqual(gas["hazard"], "volcanic_event")
        self.assertIsNone(gas["vei"])
        recs = {r["category"]: r for r in h.record_holders(self.items, fx.SYN_USGS_LARGEST, h.load_baseline(), NOW)}
        self.assertEqual(recs["deadliest_eruption"]["holder"]["title"], "1815 eruption of Mount Tambora")
        self.assertNotIn("Test gas", recs["largest_eruption"]["holder"]["title"])

    def test_possible_duplicates_flagged_not_merged(self):
        res = {p["title"]: p for p in h.deadliest(self.items, "all", now=NOW)["items"]}
        a = res["Earthquake — Sicily, Italy"]
        b = res["Earthquake — Sicily, Calabria, Italy"]
        self.assertIn(b["rank"], a["possible_duplicate_of"])
        self.assertIn(a["rank"], b["possible_duplicate_of"])

    def test_place_name_cleanup(self):
        f = h.format_place
        self.assertEqual(f("CHINA:  YUNNAN AND SICHUAN PROVINCES, CHAO-T'UNG"), "Yunnan and Sichuan Provinces, Chao-T'ung, China")
        self.assertEqual(f("JAPAN:  SW HONSHU:  KOBE"), "Kobe, Southwestern Honshu, Japan")
        self.assertEqual(f("CHINA:  N, XINJIANG"), "Northern Xinjiang, China")
        self.assertEqual(f("TURKEY:  ANTAKYA (ANTIOCH)"), "Antakya (Antioch), Turkey")
        # Regression from live list: spelled-out direction words keep NCEI's comma
        self.assertEqual(f("PERU:  NORTHERN, PISCO, CHICLAYO"), "Northern, Pisco, Chiclayo, Peru")
        # Direction-only segments qualify the broader segment after them
        self.assertEqual(f("CHINA:  XINJIANG WEIWUER ZIZHIQU PROVINCE:  N"), "Northern Xinjiang Weiwuer Zizhiqu Province, China")
        self.assertEqual(f("IRAN:  SOUTHEASTERN:  BAM, BARAVAT"), "Bam, Baravat, Southeastern Iran")

    def test_volcano_names_uninverted(self):
        self.assertEqual(h.volcano_display_name("Ruiz, Nevado del"), "Nevado del Ruiz")
        self.assertEqual(h.volcano_display_name("Fournaise, Piton de la"), "Piton de la Fournaise")
        self.assertEqual(h.volcano_display_name("Pelee"), "Pelee")

    def test_five_new_baseline_events(self):
        since = [p["title"] for p in h.deadliest(self.items, "since1900", now=NOW)["items"]]
        for t in ("1922 Swatow (Shantou) typhoon", "1954 Yangtze floods", "1998 Hurricane Mitch", "1999 Vargas debris flows"):
            self.assertIn(t, since)
        alltime = [p["title"] for p in h.deadliest(self.items, "all", now=NOW)["items"]]
        self.assertIn("1876 Great Backerganj cyclone", alltime)


class TestHeatwaves(unittest.TestCase):
    def setUp(self):
        self.items, self.baseline = _items()
        self.hw = h.heatwaves(self.baseline, NOW)
        self.by = {p["title"]: p for p in self.hw["items"]}

    def test_never_mixed_into_deadliest(self):
        for era in ("since1900", "all"):
            titles = [p["title"] for p in h.deadliest(self.items, era, now=NOW)["items"]]
            self.assertFalse(any("heat" in t.lower() for t in titles), era)

    def test_ordered_and_labelled_with_method(self):
        self.assertEqual([p["title"] for p in self.hw["items"]][:2],
                         ["2003 European heatwave summer", "2024 European summer heat"])
        for p in self.hw["items"]:
            self.assertTrue(p["metric_label"].startswith("Estimated"))
        self.assertEqual(self.by["2003 European heatwave summer"]["metric_type"], "excess_deaths")
        self.assertEqual(self.by["2022 European summer heat"]["metric_type"], "heat_attributable")

    def test_estimate_shown_with_uncertainty(self):
        self.assertEqual(self.by["2003 European heatwave summer"]["deaths"]["display"], "more than 70,000")
        self.assertEqual(self.by["2022 European summer heat"]["deaths"]["display"], "61,672 (95% CI 37,643–86,807)")
        self.assertEqual(self.by["2010 Russian heatwave"]["deaths"]["display"], "55,000 (estimates 54,000–56,000)")
        self.assertTrue(self.by["2022 European summer heat"]["rank_overlaps"])

    def test_every_heatwave_figure_has_a_study(self):
        for p in self.hw["items"]:
            self.assertTrue(p["deaths"]["figures"])
            for f in p["deaths"]["figures"]:
                self.assertTrue(f["url"].startswith("https://") and f["source"])

    def test_heatwave_record_is_an_estimate(self):
        recs = {r["category"]: r for r in h.record_holders(self.items, fx.SYN_USGS_LARGEST, self.baseline, NOW)}
        r = recs["deadliest_heatwave"]
        self.assertEqual(r["holder"]["title"], "2003 European heatwave summer")
        self.assertEqual(r["value_display"], "more than 70,000")
        self.assertEqual(r["status"], "estimated")
        self.assertIn("overlap", r["basis"])

    def test_no_drought_famine_or_epidemic_categories(self):
        b = h.load_baseline()
        hazards = {e["hazard"] for e in b["entries"]}
        self.assertFalse(hazards & {"drought", "famine", "epidemic"})


class TestRecords(unittest.TestCase):
    def setUp(self):
        items, baseline = _items()
        self.recs = {r["category"]: r for r in h.record_holders(items, fx.SYN_USGS_LARGEST, baseline, NOW)}

    def test_strongest_quake_reviewed_only_and_candidate_held(self):
        # 1960/1964 catalogue entries aren't 'reviewed' (as observed live) but are decades old.
        r = self.recs["strongest_earthquake"]
        self.assertEqual(r["holder"]["magnitude"], 9.5)
        self.assertEqual(len(r["pending_candidates"]), 1)
        self.assertEqual(r["pending_candidates"][0]["magnitude"], 9.6)

    def test_casualty_record_not_taken_by_preliminary_event(self):
        r = self.recs["deadliest_earthquake"]
        self.assertEqual(r["holder"]["title"], "1556 Shaanxi earthquake")
        self.assertEqual(r["pending_candidates"][0]["id"], "ncei-earthquakes-9005")

    def test_since_1900_secondary_holder(self):
        r = self.recs["deadliest_earthquake"]
        self.assertEqual(r["since1900"]["title"], "1976 Tangshan earthquake")

    def test_deadliest_tsunami_ranked_by_tsunami_deaths_not_total(self):
        # Haiti's linked local tsunami (7 deaths) must not win on the 316,000 shaking total.
        r = self.recs["deadliest_tsunami"]
        self.assertEqual(r["holder"]["year"], 2004)
        self.assertEqual(r["value_display"], "227,899 (tsunami deaths)")

    def test_minor_linked_tsunami_does_not_relabel_earthquake(self):
        items, _ = _items()
        haiti = next(i for i in items if (i.get("baseline") or {}).get("id") == "haiti-2010")
        self.assertEqual(haiti["hazard"], "earthquake")
        self.assertTrue(haiti["has_tsunami"])
        sumatra = next(i for i in items if i["year"] == 2004)
        self.assertEqual(sumatra["hazard"], "earthquake_tsunami")

    def test_vei_ties_are_shared_and_bce_excluded(self):
        r = self.recs["largest_eruption"]
        self.assertEqual(r["value_display"], "VEI 7")
        self.assertEqual(r["holder"]["title"], "1815 eruption of Mount Tambora")
        shared = [s["title"] for s in r["shared_with"]]
        self.assertTrue(any("Samalas" in t for t in shared))
        self.assertFalse(any("Kikai" in t for t in shared))

    def test_wmo_and_baseline_records(self):
        self.assertEqual(self.recs["deadliest_tropical_cyclone"]["holder"]["title"], "1970 Bhola cyclone")
        self.assertEqual(self.recs["deadliest_tropical_cyclone"]["authority"], "WMO")
        self.assertEqual(self.recs["deadliest_tornado"]["value_display"], "1,300")
        self.assertEqual(self.recs["deadliest_flood"]["status"], "contested")
        self.assertEqual(self.recs["highest_tsunami_runup"]["value_display"], "524 m")

    def test_no_costliest_category(self):
        self.assertFalse(any("cost" in c for c in self.recs))


class _WinDatetime(datetime):
    """Mimics Windows: fromtimestamp() rejects negative (pre-1970) values."""
    @classmethod
    def fromtimestamp(cls, t, tz=None):
        if t < 0:
            raise OSError(22, "Invalid argument")
        return datetime.fromtimestamp(t, tz)


class TestWindowsAndResilience(unittest.TestCase):
    def test_pre_1970_usgs_dates_work_on_windows(self):
        items, baseline = _items()
        with patch.object(h, "datetime", _WinDatetime):
            recs = {r["category"]: r for r in h.record_holders(items, fx.SYN_USGS_LARGEST, baseline, NOW)}
        self.assertEqual(recs["strongest_earthquake"]["holder"]["magnitude"], 9.5)
        self.assertRegex(recs["strongest_earthquake"]["holder"]["date_label"], r"^\d{1,2} \w{3} 1960$")

    def test_one_failing_category_does_not_break_the_rest(self):
        items, baseline = _items()
        with patch.object(h, "_rec_strongest_quake", side_effect=RuntimeError("boom")):
            recs = h.record_holders(items, fx.SYN_USGS_LARGEST, baseline, NOW)
        cats = {r["category"]: r for r in recs}
        self.assertEqual(cats["strongest_earthquake"]["status"], "unavailable")
        self.assertEqual(cats["deadliest_tropical_cyclone"]["holder"]["title"], "1970 Bhola cyclone")
        self.assertEqual(len(recs), 10)


class TestCaching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(h, "CACHE_DIR", Path(self.tmp.name))
        self.p.start()
        h._mem.clear()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()
        h._mem.clear()

    def test_live_then_cached_then_never_invented(self):
        items, st = h.get_dataset("earthquakes", lambda: [{"id": 1}], "u")
        self.assertEqual(st["status"], "live")
        self.assertTrue((Path(self.tmp.name) / "earthquakes.json").exists())
        h._mem.clear()
        def boom():
            raise ConnectionError("NCEI down")
        items, st = h.get_dataset("earthquakes", boom, "u", force=True)
        self.assertEqual(st["status"], "cached")
        self.assertEqual(items, [{"id": 1}])
        items, st = h.get_dataset("volcanoes", boom, "u")
        self.assertEqual((items, st["status"]), ([], "unavailable"))

    def test_fresh_cache_not_refetched(self):
        calls = []
        h.get_dataset("tsunamis", lambda: calls.append(1) or [{"id": 2}], "u")
        h.get_dataset("tsunamis", lambda: calls.append(1) or [{"id": 3}], "u")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
