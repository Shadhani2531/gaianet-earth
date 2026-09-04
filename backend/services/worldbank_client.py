"""
GaiaNet Earth — World Bank Open Data client
File: backend/services/worldbank_client.py

Real per-country CO2 emissions, for the Global SHI's "Climate/Emissions"
component. The World Bank Indicators API v2 is fully open — no API key,
no signup, no auth header required at all.

IMPORTANT: the classic EN.ATM.CO2E.PC indicator code was archived by the
World Bank (its underlying data was deleted/discontinued). The current
live replacement, confirmed against data.worldbank.org directly, is
EN.GHG.CO2.PC.CE.AR5 — "CO2 emissions excluding LULUCF per capita
(t CO2e/capita)", sourced from EDGAR/IEA. Using the archived code would
silently return empty results for every country, the same failure shape
as the OpenAQ /latest bug — so this is deliberately NOT the code most
older tutorials reference.
"""

import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_WB_BASE = "https://api.worldbank.org/v2"
_CO2_INDICATOR = "EN.GHG.CO2.PC.CE.AR5"

_co2_cache: Dict = {"data": None, "fetched_at": None}
_country_metadata_cache: Dict = {"data": None, "fetched_at": None}
CACHE_HOURS = 168  # 1 week — this is an annual dataset, not live-updating

_last_worldbank_error: Optional[str] = None


def get_last_worldbank_error() -> Optional[str]:
    """Most recent real World Bank fetch error, or None if the last fetch
    succeeded. Mirrors openaq_client's get_last_openaq_error() so callers
    can surface a specific reason instead of a generic failure message."""
    return _last_worldbank_error


def get_country_metadata() -> Dict[str, Dict]:
    """
    Real country list (name, ISO3, capital), keyed by ISO 3166-1 alpha-2
    code — filtered to actual countries only.

    World Bank's /country/all endpoint mixes real countries in with
    aggregate groups ("World", "OECD members", "Euro area", ...), which
    would otherwise leak into the SHI rankings as fake "countries" once
    coverage isn't gated on OpenAQ anymore. The reliable filter, verified
    against real response examples: every actual country has a non-empty
    capitalCity field; aggregate groups don't have one (an income-level
    grouping has no capital). This is more concrete than relying on an
    undocumented region-code convention.

    Shared by who_gho_client.py for its own ISO3->ISO2 crosswalk, so
    there's one real fetch and one real filtering rule, not two.
    """
    now = datetime.now(timezone.utc)
    if (_country_metadata_cache["data"] is not None and _country_metadata_cache["fetched_at"]
            and (now - _country_metadata_cache["fetched_at"]) < timedelta(hours=CACHE_HOURS)):
        return _country_metadata_cache["data"]

    try:
        resp = requests.get(
            f"{_WB_BASE}/country/all",
            params={"format": "json", "per_page": 400},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            return _country_metadata_cache["data"] if _country_metadata_cache["data"] is not None else {}

        result = {}
        for row in payload[1]:
            if not row.get("capitalCity"):
                continue  # aggregate group (region/income/lending), not a real country
            iso2 = row.get("iso2Code")
            iso3 = row.get("id")
            name = row.get("name")
            if iso2 and iso3 and name:
                result[iso2] = {"name": name, "iso3": iso3, "capital": row.get("capitalCity")}

        _country_metadata_cache["data"] = result
        _country_metadata_cache["fetched_at"] = now
        return result
    except Exception as e:
        logger.warning(f"Failed to fetch World Bank country metadata: {e}")
        return _country_metadata_cache["data"] if _country_metadata_cache["data"] is not None else {}


def get_co2_per_capita_by_country() -> Dict[str, float]:
    """
    Real CO2 emissions per capita (t CO2e/capita), keyed by ISO 3166-1
    alpha-2 country code — the same code system OpenAQ uses, so this
    joins directly against the air-quality data with no crosswalk needed
    (the World Bank API accepts and returns ISO2 codes natively).

    One request fetches ALL countries' latest real value at once
    (mrnev=1 = most recent non-empty value, since mrv=1 can return the
    newest YEAR even when that year's value is null for many countries).
    This avoids an N-requests-per-country pattern the way the old OpenAQ
    per-station loop did.

    Countries with no real reported value are simply absent from the
    returned dict — never backfilled with a guess.
    """
    global _last_worldbank_error
    now = datetime.now(timezone.utc)
    if (_co2_cache["data"] is not None and _co2_cache["fetched_at"]
            and (now - _co2_cache["fetched_at"]) < timedelta(hours=CACHE_HOURS)):
        return _co2_cache["data"]

    try:
        resp = requests.get(
            f"{_WB_BASE}/country/all/indicator/{_CO2_INDICATOR}",
            params={"format": "json", "mrnev": 1, "per_page": 20000},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()

        # World Bank's response is [metadata, results] — a plain error
        # page or an indicator with no data at all can come back as a
        # single-element list, so guard the shape before indexing [1].
        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            _last_worldbank_error = "Unexpected response shape or empty results from World Bank API"
            logger.warning(f"World Bank CO2 fetch: {_last_worldbank_error}")
            return _co2_cache["data"] if _co2_cache["data"] is not None else {}

        real_countries = get_country_metadata()
        result: Dict[str, float] = {}
        for row in payload[1]:
            value = row.get("value")
            iso2 = (row.get("country") or {}).get("id")
            if value is None or not iso2:
                continue
            if iso2 not in real_countries:
                continue  # aggregate group (e.g. "World", "OECD members"), not a real country
            result[iso2] = float(value)

        _co2_cache["data"] = result
        _co2_cache["fetched_at"] = now
        _last_worldbank_error = None
        return result
    except Exception as e:
        logger.error(f"Failed to fetch World Bank CO2 data: {e}")
        _last_worldbank_error = str(e)
        return _co2_cache["data"] if _co2_cache["data"] is not None else {}
