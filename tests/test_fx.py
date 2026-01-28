"""Tests for the Pituffik FX (currency conversion) module."""

import pytest

from pipeline.fx import convert_to_gbp, parse_ecb_xml


# Sample ECB XML for testing
SAMPLE_ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
    <gesmes:subject>Reference rates</gesmes:subject>
    <gesmes:Sender>
        <gesmes:name>European Central Bank</gesmes:name>
    </gesmes:Sender>
    <Cube>
        <Cube time="2025-01-28">
            <Cube currency="USD" rate="1.0825"/>
            <Cube currency="GBP" rate="0.8456"/>
            <Cube currency="DKK" rate="7.4602"/>
            <Cube currency="SEK" rate="11.4930"/>
            <Cube currency="NOK" rate="11.7985"/>
        </Cube>
    </Cube>
</gesmes:Envelope>"""


class TestParseEcbXml:
    """Tests for ECB XML parsing."""

    def test_parses_rates(self):
        rates = parse_ecb_xml(SAMPLE_ECB_XML)
        assert "USD" in rates
        assert "GBP" in rates
        assert rates["USD"]["rate_to_eur"] == 1.0825
        assert rates["GBP"]["rate_to_eur"] == 0.8456

    def test_includes_date(self):
        rates = parse_ecb_xml(SAMPLE_ECB_XML)
        assert rates["USD"]["date"] == "2025-01-28"

    def test_empty_xml(self):
        with pytest.raises(ValueError):
            parse_ecb_xml("")


class TestConvertToGbp:
    """Tests for currency conversion to GBP."""

    def test_usd_to_gbp(self):
        rates = {
            "GBP": {"rate_to_eur": 0.8456, "date": "2025-01-28"},
            "USD": {"rate_to_eur": 1.0825, "date": "2025-01-28"},
        }
        result = convert_to_gbp(100000.0, "USD", rates)
        assert result is not None
        # 100000 USD / 1.0825 * 0.8456 = ~78,120 GBP
        assert 70000 < result < 90000

    def test_eur_to_gbp(self):
        rates = {"GBP": {"rate_to_eur": 0.8456, "date": "2025-01-28"}}
        result = convert_to_gbp(100000.0, "EUR", rates)
        assert result is not None
        assert abs(result - 84560.0) < 1.0

    def test_gbp_to_gbp(self):
        rates = {"GBP": {"rate_to_eur": 0.8456, "date": "2025-01-28"}}
        result = convert_to_gbp(100000.0, "GBP", rates)
        assert result == 100000.0

    def test_unknown_currency(self):
        rates = {"GBP": {"rate_to_eur": 0.8456, "date": "2025-01-28"}}
        result = convert_to_gbp(100000.0, "XYZ", rates)
        assert result is None

    def test_none_amount(self):
        rates = {"GBP": {"rate_to_eur": 0.8456, "date": "2025-01-28"}}
        result = convert_to_gbp(None, "USD", rates)
        assert result is None
