"""
GaiaNet Earth — Global SHI composite scoring
File: backend/services/shi_composite.py

Implements the same core methodology the Yale/Columbia Environmental
Performance Index (EPI) uses (epi.yale.edu/2026-methodology), adapted to
GaiaNet's four real data sources:

  40% Air Quality        - OpenAQ v3 real station PM2.5 (openaq_client)
  25% Climate/Emissions  - World Bank real CO2 emissions per capita (worldbank_client)
  20% Health Outcomes    - WHO GHO real life expectancy at birth (who_gho_client)
  15% Environmental      - NASA MODIS real NDVI at a country reference point (modis_ndvi)
      Sustainability

Two methodological pieces, both taken directly from EPI's published
approach rather than invented ad hoc:

1. DISTANCE-TO-TARGET SCORING (0-100 per raw indicator):
       score = (X - W) / (B - W) * 100, clamped to [0, 100]
   where X is a country's real value, B is the "best realistic"
   benchmark, W is "worst realistic". Since none of these four
   indicators has an international treaty target GaiaNet can cite, B/W
   are set from real percentiles (5th/95th) of the actual values fetched
   THIS run — exactly what EPI's methodology falls back to when no
   treaty or expert target exists. This means benchmarks are always
   grounded in real, live data, never a hardcoded assumption.

2. WEIGHT REAPPORTIONMENT for missing components: if a country lacks
   real data for one component, that component's weight is NOT dropped
   silently (which is what the previous "simple average of whatever
   exists" implementation did, causing a single-component country like
   Puerto Rico to directly outscore a three-component country like the
   Netherlands). Instead, its weight is redistributed proportionally
   across the components that DO exist for that country, preserving
   their relative ratio. This is the documented EPI approach (see
   "Materiality" and "Missing Data" in their methodology).
"""

import logging
from typing import Dict, List, Optional, Any

from services import openaq_client, worldbank_client, who_gho_client, modis_ndvi, country_coords, scenario_engine

logger = logging.getLogger(__name__)

BASE_WEIGHTS = {
    "air_quality": 0.40,
    "emissions": 0.25,
    "health": 0.20,
    "vegetation": 0.15,
}

_BEST_PERCENTILE = 0.95
_WORST_PERCENTILE = 0.05


def _percentile(sorted_values: List[float], p: float) -> float:
    """Linear-interpolated percentile of an already-sorted list — no
    numpy dependency needed for this."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = p * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _real_benchmarks(values: List[float], higher_is_better: bool) -> Optional[tuple]:
    """Computes (best, worst) target values from real percentiles of the
    actual fetched data. Returns None if there isn't enough real data to
    form a meaningful spread (fewer than 3 countries)."""
    if len(values) < 3:
        return None
    s = sorted(values)
    p_low = _percentile(s, _WORST_PERCENTILE)
    p_high = _percentile(s, _BEST_PERCENTILE)
    if higher_is_better:
        return (p_high, p_low)  # (best, worst)
    return (p_low, p_high)  # lower raw value is better, so best=low, worst=high


def _distance_to_target_score(value: float, best: float, worst: float) -> float:
    if best == worst:
        return 50.0  # no real spread to compare against — neutral, not a guess at direction
    score = (value - worst) / (best - worst) * 100
    return max(0.0, min(100.0, score))


def compute_global_shi() -> Dict[str, Any]:
    """
    Fetches all four real data sources, computes percentile benchmarks
    from whatever real data actually came back this run, scores EVERY
    country that has real data from at least one source, and returns the
    same response shape the /shi-global endpoint has always returned.

    IMPORTANT: earlier versions of this function only scored countries
    that had real OpenAQ air-quality stations — everything else was
    excluded from the map entirely, even when real emissions/health data
    existed for it. OpenAQ's station network is real but geographically
    uneven (dense in Europe/East Asia/North America, sparse elsewhere);
    World Bank and WHO GHO both have real data for 190+ countries. Gating
    the whole composite on OpenAQ coverage meant most of the globe showed
    as "no data" even where real data existed from the other three
    sources. This now iterates the UNION of countries with real data from
    ANY source — the existing weight-reapportionment logic already
    handles "this country has fewer than 4 components" correctly; it just
    wasn't being given the full set of countries to apply that to.
    """
    aq_aggregate = openaq_client.get_country_aqi_aggregate()
    co2_by_country = worldbank_client.get_co2_per_capita_by_country()
    life_expectancy_by_country = who_gho_client.get_life_expectancy_by_country()
    country_metadata = worldbank_client.get_country_metadata()  # for real country names OpenAQ doesn't provide

    if not aq_aggregate and not co2_by_country and not life_expectancy_by_country:
        # All three primary sources failed — genuinely nothing to show,
        # distinct from "OpenAQ failed but the others worked."
        reason = openaq_client.get_last_openaq_error()
        message = "Could not fetch real data from any source right now. Try again shortly."
        if reason:
            message += f" (OpenAQ reason: {reason})"
        return {"countries": [], "status": "no_data", "message": message, "debug_reason": reason}

    all_codes = set(aq_aggregate.keys()) | set(co2_by_country.keys()) | set(life_expectancy_by_country.keys())

    # Real counts from each source, before any union/threshold logic —
    # surfaced in the response so a live run can show exactly which
    # source is under-covering, rather than guessing from outside.
    source_coverage = {
        "air_quality_countries": len(aq_aggregate),
        "emissions_countries": len(co2_by_country),
        "health_countries": len(life_expectancy_by_country),
        "union_countries": len(all_codes),
        "overlap_aq_emissions": len(set(aq_aggregate.keys()) & set(co2_by_country.keys())),
        "overlap_aq_health": len(set(aq_aggregate.keys()) & set(life_expectancy_by_country.keys())),
        "overlap_emissions_health": len(set(co2_by_country.keys()) & set(life_expectancy_by_country.keys())),
        "sample_air_quality_codes": sorted(aq_aggregate.keys())[:10],
        "sample_emissions_codes": sorted(co2_by_country.keys())[:10],
        "sample_health_codes": sorted(life_expectancy_by_country.keys())[:10],
        "openaq_error": openaq_client.get_last_openaq_error(),
        "worldbank_error": worldbank_client.get_last_worldbank_error(),
        "who_error": who_gho_client.get_last_who_error(),
    }

    # --- Vegetation (NDVI at each country's reference point) ---
    # Extended to the FULL union set, not just countries with air-quality
    # stations — a country can have a real country_coords.py reference
    # point regardless of whether OpenAQ has a station there.
    ndvi_by_country: Dict[str, Dict[str, Any]] = {}
    for code in all_codes:
        ref_point = country_coords.get_country_reference_point(code)
        if not ref_point:
            continue
        try:
            ndvi_info = modis_ndvi.get_ndvi_at_location(ref_point["lat"], ref_point["lon"])
            ndvi_by_country[code] = {
                "value": ndvi_info.get("ndvi", 0),
                "capital": ref_point["capital"],
                "is_real": ndvi_info.get("data_source") == "real_modis",
            }
        except Exception as e:
            logger.warning(f"NDVI lookup failed for {code}: {e}")

    # --- Raw value pools, for computing real percentile benchmarks ---
    aqi_values = {code: scenario_engine._pm25_to_aqi(info["avg_pm25"]) for code, info in aq_aggregate.items()}
    aqi_bench = _real_benchmarks(list(aqi_values.values()), higher_is_better=False)  # lower AQI = better
    co2_bench = _real_benchmarks(list(co2_by_country.values()), higher_is_better=False)  # lower emissions = better
    life_bench = _real_benchmarks(list(life_expectancy_by_country.values()), higher_is_better=True)
    ndvi_bench = _real_benchmarks([v["value"] for v in ndvi_by_country.values()], higher_is_better=True)

    results = []
    for code in all_codes:
        components: Dict[str, Any] = {}
        aq_info = aq_aggregate.get(code)

        if aqi_bench and code in aqi_values:
            aqi = aqi_values[code]
            components["air_quality"] = {
                "value": round(_distance_to_target_score(aqi, *aqi_bench), 1),
                "basis": f"Real OpenAQ v3 data, {aq_info['station_count']} station(s) sampled, "
                         f"avg PM2.5 {aq_info['avg_pm25']} µg/m³ (AQI {round(aqi)}). Scored against the "
                         f"5th/95th percentile of this run's real sampled countries (EPI-style "
                         f"distance-to-target), not a fixed formula.",
                "confidence": "measured",
            }

        if co2_bench and code in co2_by_country:
            co2 = co2_by_country[code]
            components["emissions"] = {
                "value": round(_distance_to_target_score(co2, *co2_bench), 1),
                "basis": f"Real World Bank data: {co2} t CO2e/capita (EN.GHG.CO2.PC.CE.AR5, "
                         f"EDGAR/IEA-sourced). Scored against the 5th/95th percentile of real "
                         f"country values from this run.",
                "confidence": "measured",
            }

        if life_bench and code in life_expectancy_by_country:
            life = life_expectancy_by_country[code]
            components["health"] = {
                "value": round(_distance_to_target_score(life, *life_bench), 1),
                "basis": f"Real WHO Global Health Observatory data: life expectancy at birth "
                         f"{life} years (WHOSIS_000001). Scored against the 5th/95th percentile "
                         f"of real country values from this run.",
                "confidence": "measured",
            }

        if ndvi_bench and code in ndvi_by_country:
            ndvi_info = ndvi_by_country[code]
            components["vegetation"] = {
                "value": round(_distance_to_target_score(ndvi_info["value"], *ndvi_bench), 1),
                "basis": f"{'Real NASA MODIS NDVI' if ndvi_info['is_real'] else 'Estimated NDVI (MODIS unavailable for this point)'} "
                         f"at {ndvi_info['capital']}, value {ndvi_info['value']}. A single capital-city "
                         f"point is a coarse stand-in for a whole country's vegetation — treat as "
                         f"indicative, not precise.",
                "confidence": "measured" if ndvi_info["is_real"] else "estimated",
            }

        if not components:
            continue

        # --- Weight reapportionment: only components this country
        # actually has get a share of the total weight, preserving their
        # relative ratio from BASE_WEIGHTS (the EPI "materiality" rule).
        present_weight_sum = sum(BASE_WEIGHTS[k] for k in components.keys())
        composite_shi = sum(
            components[k]["value"] * (BASE_WEIGHTS[k] / present_weight_sum)
            for k in components.keys()
        )
        for k in components.keys():
            components[k]["weight"] = round(BASE_WEIGHTS[k] / present_weight_sum, 3)

        grade = 'A' if composite_shi >= 80 else ('B' if composite_shi >= 60 else ('C' if composite_shi >= 40 else 'D'))
        risk = 'Healthy' if composite_shi >= 80 else ('Moderate' if composite_shi >= 50 else 'Poor')

        # Country name: prefer OpenAQ's (real, when we have it), then
        # World Bank's real metadata for countries OpenAQ doesn't cover,
        # then the raw code itself as a last resort — never a guess.
        if aq_info:
            country_name = aq_info["country_name"]
        elif code in country_metadata:
            country_name = country_metadata[code]["name"]
        else:
            country_name = code

        results.append({
            "country_code": code,
            "country_name": country_name,
            "shi": int(round(composite_shi)),
            "grade": grade,
            "risk": risk,
            "components": components,
            "components_used": list(components.keys()),
            "component_count": len(components),
            "station_count": aq_info["station_count"] if aq_info else 0,
        })

    results.sort(key=lambda r: r["shi"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    # --- Minimum coverage threshold for the RANKED list (not the map) ---
    # A country with just 1 real component isn't diluted/moderated by any
    # other dimension the way a 4-component country is — so a single lucky
    # (or unlucky) real number can land it at a perfect 100 with nothing
    # to check it, and a cluster of such countries can flood the top of a
    # ranked list. This isn't a data bug — the underlying values are real
    # — it's a statistical instability problem with tiny, thin samples,
    # and it's the same reason the real EPI excludes micro-states below a
    # population threshold from its own headline country rankings rather
    # than mixing them in on equal footing with fully-measured countries.
    # `countries` below keeps EVERY country with real data (so the map
    # heatmap stays fully, honestly colored) — only the ranked list is
    # restricted to countries with a meaningful multi-source comparison.
    MIN_COMPONENTS_FOR_RANKING = 2
    ranking_results = [r for r in results if r["component_count"] >= MIN_COMPONENTS_FOR_RANKING]
    for i, r in enumerate(ranking_results):
        r["ranking_rank"] = i + 1

    return {
        "countries": results,
        "ranking_countries": ranking_results,
        "status": "ok",
        "sampled_country_count": len(results),
        "source_coverage": source_coverage,
        "ranked_country_count": len(ranking_results),
        "min_components_for_ranking": MIN_COMPONENTS_FOR_RANKING,
        "note": "SHI combines four real data sources — air quality (OpenAQ v3, 40% base weight), "
                "climate/emissions (World Bank CO2 per capita, 25%), health outcomes (WHO life "
                "expectancy, 20%), and vegetation (NASA MODIS NDVI at a capital-city reference "
                "point, 15%). Each raw value is scored 0-100 against the 5th/95th percentile of "
                "this run's real country values (EPI methodology, not a fixed formula). "
                "'countries' includes every country with real data from at least one source, for "
                "the map. 'ranking_countries' is restricted to countries with at least "
                f"{MIN_COMPONENTS_FOR_RANKING} of 4 real components, since a single-component "
                "score isn't moderated by any other dimension and can misleadingly dominate a "
                "ranked list — the same reason real indices like EPI exclude micro-states from "
                "their headline country rankings. component_count on each entry shows exactly "
                "how many of the 4 real sources back its score."
    }
