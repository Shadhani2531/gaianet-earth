"""
GaiaNet Earth — WHO Global Health Observatory (GHO) client
File: backend/services/who_gho_client.py

Real per-country life expectancy at birth, for the Global SHI's "Health
Outcomes" component. The GHO OData API (ghoapi.azureedge.net) requires no
authentication and no API key.

Indicator used: WHOSIS_000001 ("Life expectancy at birth (years)") —
confirmed against WHO's own official OData API documentation
(who.int/data/gho/info/gho-odata-api, Example 4).

Response fields (confirmed against real sample records, not guessed —
see the OpenAQ /latest bug this project already hit once from an
unverified field-name assumption):
  SpatialDim   -> ISO 3166-1 alpha-3 country code (e.g. "USA", "IND")
  TimeDim      -> year, integer
  Dim1         -> sex breakdown; the "both sexes" aggregate row's exact
                  token has appeared as both "BTSX" and "SEX_BTSX" across
                  different real API responses, so both are checked for
                  rather than assuming one.
  NumericValue -> the actual life-expectancy value, float

GaiaNet's other data sources (OpenAQ) key countries by ISO alpha-2, so
this module also fetches the World Bank's country list (itself keyless)
to build a real ISO3->ISO2 crosswalk, rather than hand-typing a static
mapping table.
"""

import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from services import worldbank_client

logger = logging.getLogger(__name__)

_GHO_BASE = "https://ghoapi.azureedge.net/api"
_LIFE_EXPECTANCY_INDICATOR = "WHOSIS_000001"
_BOTH_SEXES_TOKENS = {"BTSX", "SEX_BTSX"}

_life_expectancy_cache: Dict = {"data": None, "fetched_at": None}
CACHE_HOURS = 168  # 1 week — annual health statistics, not live-updating

_last_who_error: Optional[str] = None


def get_last_who_error() -> Optional[str]:
    """Most recent real WHO GHO fetch error, or None if the last fetch
    succeeded."""
    return _last_who_error


def _get_iso3_to_iso2_map() -> Dict[str, str]:
    """Real ISO3->ISO2 crosswalk, built from worldbank_client's shared
    real-country metadata (itself keyless) rather than a hand-typed
    static table that would silently go stale as country codes change.
    Reusing that module's fetch also means WHO data gets the exact same
    aggregate-group filtering (capitalCity-based) applied to it, instead
    of duplicating and potentially drifting from that logic."""
    metadata = worldbank_client.get_country_metadata()
    return {info["iso3"]: iso2 for iso2, info in metadata.items()}


def get_life_expectancy_by_country() -> Dict[str, float]:
    """
    Real life expectancy at birth (years), keyed by ISO 3166-1 alpha-2
    country code (converted from GHO's native ISO3 so this joins directly
    against OpenAQ-keyed data elsewhere in the SHI composite).

    One request fetches every country/year/sex row for this indicator;
    reduced here to the latest year's "both sexes" value per country.
    Countries with no real reported value are simply absent — never
    backfilled with a guess.
    """
    global _last_who_error
    now = datetime.now(timezone.utc)
    if (_life_expectancy_cache["data"] is not None and _life_expectancy_cache["fetched_at"]
            and (now - _life_expectancy_cache["fetched_at"]) < timedelta(hours=CACHE_HOURS)):
        return _life_expectancy_cache["data"]

    try:
        rows = []
        # WHO's OData API paginates large indicators via @odata.nextLink —
        # WHOSIS_000001 spans ~194 countries x multiple decades x 3 sex
        # breakdowns, which does not fit in a single page. Not following
        # this link would silently return only the first page (a handful
        # of countries) with no error at all — the same failure shape as
        # the earlier OpenAQ bug, just from a different cause (missed
        # pagination instead of a wrong field name).
        url = f"{_GHO_BASE}/{_LIFE_EXPECTANCY_INDICATOR}"
        page_count = 0
        while url:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            rows.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
            page_count += 1
            if page_count > 300:  # generous sane upper bound, not a real expected case
                logger.warning("WHO GHO pagination exceeded 300 pages — stopping early")
                break

        if not rows:
            _last_who_error = "WHO GHO returned zero rows for WHOSIS_000001"
            logger.warning(_last_who_error)
            return _life_expectancy_cache["data"] if _life_expectancy_cache["data"] is not None else {}

        iso3_to_iso2 = _get_iso3_to_iso2_map()

        # Keep only "both sexes" rows for actual countries, then reduce to
        # the single latest year per country — different countries report
        # different latest years, so this is a real per-country "most
        # recent real value," not a synchronized single global year.
        latest_by_iso3: Dict[str, tuple] = {}  # iso3 -> (year, value)
        for row in rows:
            if row.get("SpatialDimType") != "COUNTRY":
                continue
            if row.get("Dim1") not in _BOTH_SEXES_TOKENS:
                continue
            iso3 = row.get("SpatialDim")
            year = row.get("TimeDim")
            value = row.get("NumericValue")
            if not iso3 or year is None or value is None:
                continue
            existing = latest_by_iso3.get(iso3)
            if existing is None or year > existing[0]:
                latest_by_iso3[iso3] = (year, float(value))

        result: Dict[str, float] = {}
        for iso3, (year, value) in latest_by_iso3.items():
            iso2 = iso3_to_iso2.get(iso3)
            if iso2:
                result[iso2] = value

        _life_expectancy_cache["data"] = result
        _life_expectancy_cache["fetched_at"] = now
        _last_who_error = None
        return result
    except Exception as e:
        logger.error(f"Failed to fetch WHO GHO life expectancy data: {e}")
        _last_who_error = str(e)
        return _life_expectancy_cache["data"] if _life_expectancy_cache["data"] is not None else {}
