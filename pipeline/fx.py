"""ECB currency conversion module for Pituffik.

Fetches daily exchange rates from the European Central Bank (ECB) and
converts grant amounts to USD via EUR cross-rates. Rates are cached in
the database to minimise external requests.

Conversion path:
- USD amounts: passthrough (no conversion needed)
- EUR amounts: convert directly using the EUR/USD rate
- All other currencies: convert to EUR first, then to USD
"""

from __future__ import annotations

import logging
import sqlite3
import xml.etree.ElementTree as ET
from typing import Optional

from pipeline import db
from pipeline.models import FxRate

logger = logging.getLogger(__name__)

# ECB daily exchange rate feed URL
_ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# XML namespaces used in the ECB feed
_ECB_NS = {
    "gesmes": "http://www.gesmes.org/xml/2002-08-01",
    "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref",
}


def parse_ecb_xml(xml_text: str) -> dict:
    """Parse ECB daily exchange rate XML into a rates dictionary.

    The ECB publishes rates as EUR-based (i.e. 1 EUR = X units of foreign
    currency). This function extracts all currency rates and the reference
    date.

    Args:
        xml_text: The raw XML string from the ECB daily feed.

    Returns:
        A dict of {currency_code: {"rate_to_eur": float, "date": str}}.
        The rate_to_eur value is the number of currency units per 1 EUR.
        For example, {"USD": {"rate_to_eur": 1.0876, "date": "2025-01-28"}}
        means 1 EUR = 1.0876 USD.

    Raises:
        ValueError: If the XML cannot be parsed or contains no rate data.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Failed to parse ECB XML: {exc}") from exc

    # Navigate to the Cube element containing rates
    # Structure: Envelope > Cube > Cube[@time] > Cube[@currency, @rate]
    envelope_cube = root.find("ecb:Cube", _ECB_NS)
    if envelope_cube is None:
        raise ValueError("No Cube element found in ECB XML")

    time_cube = envelope_cube.find("ecb:Cube[@time]", _ECB_NS)
    if time_cube is None:
        raise ValueError("No time-stamped Cube element found in ECB XML")

    reference_date = time_cube.get("time")
    if not reference_date:
        raise ValueError("No time attribute on Cube element")

    rates: dict = {}
    for cube in time_cube.findall("ecb:Cube", _ECB_NS):
        currency = cube.get("currency")
        rate_str = cube.get("rate")
        if currency and rate_str:
            try:
                rates[currency] = {
                    "rate_to_eur": float(rate_str),
                    "date": reference_date,
                }
            except ValueError:
                logger.warning(
                    "Could not parse rate for %s: %s", currency, rate_str
                )

    if not rates:
        raise ValueError("No currency rates found in ECB XML")

    # Add EUR itself (1 EUR = 1 EUR)
    rates["EUR"] = {"rate_to_eur": 1.0, "date": reference_date}

    logger.info(
        "Parsed %d ECB exchange rates for %s", len(rates), reference_date
    )
    return rates


def fetch_ecb_rates(http_client) -> dict:
    """Fetch current exchange rates from the ECB daily feed.

    Args:
        http_client: An HTTP client with a get(url) method that returns a
            response object with a .text attribute (e.g. httpx.Client or
            requests.Session).

    Returns:
        A dict of {currency_code: {"rate_to_eur": float, "date": str}}
        as returned by parse_ecb_xml.

    Raises:
        RuntimeError: If the HTTP request fails.
        ValueError: If the response cannot be parsed.
    """
    logger.info("Fetching ECB exchange rates from %s", _ECB_URL)
    response = http_client.get(_ECB_URL)

    # Handle both httpx and requests response status checking
    status_code = getattr(response, "status_code", None)
    if status_code and status_code != 200:
        raise RuntimeError(
            f"ECB rate fetch failed with HTTP {status_code}"
        )

    return parse_ecb_xml(response.text)


def convert_to_usd(
    amount: Optional[float],
    currency: str,
    rates: dict,
) -> Optional[float]:
    """Convert an amount in any currency to USD via EUR cross-rate.

    Conversion logic:
    - If amount is None, return None.
    - If currency is USD, return the amount unchanged (passthrough).
    - If currency is EUR, convert directly: amount * EUR/USD rate.
    - For all other currencies, convert to EUR first (amount / rate_to_eur),
      then from EUR to USD.

    Args:
        amount: The monetary amount to convert, or None.
        currency: The ISO 4217 three-letter currency code (e.g. "GBP", "DKK").
        rates: The rates dictionary from parse_ecb_xml or fetch_ecb_rates.

    Returns:
        The amount in USD (rounded to 2 decimal places), or None if the
        currency is not found in the rates dictionary or the amount is None.
    """
    if amount is None:
        return None

    currency_upper = currency.upper()

    # USD passthrough
    if currency_upper == "USD":
        return round(amount, 2)

    # We need the EUR/USD rate for any conversion
    usd_entry = rates.get("USD")
    if not usd_entry:
        logger.warning("USD rate not found in rates dictionary")
        return None

    eur_to_usd = usd_entry["rate_to_eur"]  # This is 1 EUR = X USD

    # EUR direct conversion
    if currency_upper == "EUR":
        return round(amount * eur_to_usd, 2)

    # Other currencies: convert to EUR first, then to USD
    source_entry = rates.get(currency_upper)
    if not source_entry:
        logger.warning("Currency %s not found in ECB rates", currency_upper)
        return None

    source_to_eur = source_entry["rate_to_eur"]  # 1 EUR = X source_currency
    amount_in_eur = amount / source_to_eur
    amount_in_usd = amount_in_eur * eur_to_usd
    return round(amount_in_usd, 2)


def update_fx_rates(conn: sqlite3.Connection, http_client) -> dict:
    """Fetch ECB rates and store them in the database.

    Fetches the latest daily rates from the ECB, computes the USD cross-rate
    for each currency, and upserts them into the fx_rates table.

    Args:
        conn: Database connection.
        http_client: An HTTP client with a get(url) method.

    Returns:
        The rates dictionary from the ECB feed.
    """
    rates = fetch_ecb_rates(http_client)

    # Compute USD cross-rates and store each currency
    usd_rate = rates.get("USD", {}).get("rate_to_eur")

    for currency_code, rate_info in rates.items():
        rate_to_eur = rate_info["rate_to_eur"]
        rate_date = rate_info["date"]

        # Compute rate_to_usd: how many USD per 1 unit of this currency
        # 1 unit of currency = (1 / rate_to_eur) EUR
        # 1 EUR = usd_rate USD
        # So 1 unit of currency = (usd_rate / rate_to_eur) USD
        rate_to_usd = None
        if usd_rate is not None and rate_to_eur > 0:
            if currency_code == "USD":
                rate_to_usd = 1.0
            elif currency_code == "EUR":
                rate_to_usd = usd_rate
            else:
                rate_to_usd = round(usd_rate / rate_to_eur, 6)

        fx_rate = FxRate(
            rate_date=rate_date,
            currency=currency_code,
            rate_to_eur=rate_to_eur,
            rate_to_usd=rate_to_usd,
        )
        db.upsert_fx_rate(conn, fx_rate)

    logger.info("Updated %d FX rates in database", len(rates))
    return rates


def convert_opportunity_amounts(
    conn: sqlite3.Connection,
    opp_id: str,
    rates: dict,
) -> dict:
    """Convert an opportunity's amount_min and amount_max to USD.

    Reads the opportunity record from the database, converts its amounts
    using the provided rates, and returns a dict of field updates (but does
    not write them -- the caller is responsible for applying updates).

    Args:
        conn: Database connection.
        opp_id: The opportunity ID to look up.
        rates: The rates dictionary from the ECB feed.

    Returns:
        A dict of field updates. May contain "amount_usd_min" and/or
        "amount_usd_max" keys. Returns an empty dict if no conversion
        is possible (e.g. missing currency or amount data).
    """
    opp = db.get_opportunity(conn, opp_id)
    if not opp:
        logger.warning("Opportunity %s not found for FX conversion", opp_id)
        return {}

    if not opp.amount_currency:
        logger.debug("No currency set for opportunity %s, skipping FX", opp_id)
        return {}

    updates: dict = {}

    usd_min = convert_to_usd(opp.amount_min, opp.amount_currency, rates)
    if usd_min is not None:
        updates["amount_usd_min"] = usd_min

    usd_max = convert_to_usd(opp.amount_max, opp.amount_currency, rates)
    if usd_max is not None:
        updates["amount_usd_max"] = usd_max

    if updates:
        logger.debug(
            "FX conversion for %s (%s): min=%s, max=%s",
            opp_id, opp.amount_currency,
            updates.get("amount_usd_min"), updates.get("amount_usd_max"),
        )

    return updates
