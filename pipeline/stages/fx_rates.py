"""
F09a — FX rates from ECB reference data (weekly refresh, fail-soft).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import httpx
from sqlalchemy.orm import Session

from db.models import FxRate

log = logging.getLogger(__name__)

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
STALE_DAYS = 45

# Hard-coded USD anchor for when ECB fetch fails and table is empty.
_FALLBACK_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "INR": 0.012, "SEK": 0.095, "CAD": 0.74, "AUD": 0.66, "SGD": 0.74}


def refresh_fx_rates(session: Session) -> int:
    """Fetch ECB daily rates and upsert fx_rates. Returns rows updated."""
    try:
        response = httpx.get(ECB_DAILY_URL, timeout=15.0)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        ns = {"gesmes": "http://www.gesmes.org/en/namespace-1982", "": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
        cube = root.find(".//gesmes:Cube[@time]", ns) or root.find(".//{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube[@time]")
        if cube is None:
            for elem in root.iter():
                if elem.attrib.get("time"):
                    cube = elem
                    break
        as_of = date.today()
        if cube is not None and cube.attrib.get("time"):
            as_of = date.fromisoformat(cube.attrib["time"])

        eur_to: dict[str, float] = {"EUR": 1.0}
        for child in cube:
            currency = child.attrib.get("currency")
            rate = child.attrib.get("rate")
            if currency and rate:
                eur_to[currency] = float(rate)

        # Convert to rate_to_usd (USD per 1 unit of currency).
        usd_per_eur = eur_to.get("USD", 1.08)
        updated = 0
        session.merge(FxRate(currency="USD", rate_to_usd=1.0, as_of=as_of))
        updated += 1
        for currency, eur_rate in eur_to.items():
            if currency == "USD":
                continue
            # 1 EUR = usd_per_eur USD; 1 CUR = (1/eur_rate) EUR
            rate_to_usd = usd_per_eur / eur_rate
            session.merge(FxRate(currency=currency, rate_to_usd=rate_to_usd, as_of=as_of))
            updated += 1
        session.flush()
        return updated
    except Exception as exc:
        log.warning("FX refresh failed (keeping stale rates): %s", exc)
        if session.query(FxRate).count() == 0:
            as_of = date.today()
            for currency, rate in _FALLBACK_USD.items():
                session.merge(FxRate(currency=currency, rate_to_usd=rate, as_of=as_of))
            session.flush()
        return 0


def get_rate_to_usd(session: Session, currency: str | None) -> float | None:
    """Return USD conversion rate or None when FX data is stale."""
    if not currency:
        return None
    cur = currency.upper()
    if cur == "USD":
        return 1.0
    row = session.get(FxRate, cur)
    if row is None:
        return _FALLBACK_USD.get(cur)
    if (date.today() - row.as_of).days > STALE_DAYS:
        return None
    return row.rate_to_usd


def normalise_salary_usd(
    session: Session,
    *,
    amount: int | None,
    currency: str | None,
) -> int | None:
    if amount is None:
        return None
    rate = get_rate_to_usd(session, currency)
    if rate is None:
        return None
    return int(round(amount * rate))
