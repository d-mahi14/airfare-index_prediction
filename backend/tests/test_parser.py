"""
backend/tests/test_parser.py
Tests for scraper/parsers/fare_parser.py

Validates:
  - parse_fare: Indian currency strings, numeric types, edge cases
  - normalize_iata: 3-char codes, lowercase, invalid codes
  - normalize_fare_class: canonical mapping
  - normalize_availability: availability string mapping
"""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scraper.parsers.fare_parser import (
    normalize_availability,
    normalize_fare_class,
    normalize_iata,
    parse_fare,
)


class TestParseFare:
    def test_rupee_symbol_with_comma(self):
        assert parse_fare("₹ 4,200") == Decimal("4200")

    def test_rs_prefix(self):
        assert parse_fare("Rs. 4200") == Decimal("4200")

    def test_rs_no_dot(self):
        assert parse_fare("Rs 4200.50") == Decimal("4200.50")

    def test_inr_prefix(self):
        assert parse_fare("INR 4,200.50") == Decimal("4200.50")

    def test_plain_integer_string(self):
        assert parse_fare("4200") == Decimal("4200")

    def test_plain_float_string(self):
        assert parse_fare("4200.00") == Decimal("4200.00")

    def test_integer_type(self):
        assert parse_fare(4200) == Decimal("4200")

    def test_float_type(self):
        result = parse_fare(4200.50)
        assert result is not None
        assert abs(result - Decimal("4200.50")) < Decimal("0.01")

    def test_decimal_type_passthrough(self):
        assert parse_fare(Decimal("4200.00")) == Decimal("4200.00")

    def test_empty_string_returns_none(self):
        assert parse_fare("") is None

    def test_na_returns_none(self):
        assert parse_fare("N/A") is None

    def test_none_returns_none(self):
        assert parse_fare(None) is None

    def test_null_string_returns_none(self):
        assert parse_fare("null") is None

    def test_dash_returns_none(self):
        assert parse_fare("--") is None

    def test_negative_string_returns_none(self):
        assert parse_fare("-100") is None

    def test_negative_int_returns_none(self):
        assert parse_fare(-100) is None

    def test_large_fare(self):
        assert parse_fare("₹75,000") == Decimal("75000")

    def test_comma_in_thousands(self):
        assert parse_fare("12,500") == Decimal("12500")

    def test_lowercase_inr(self):
        assert parse_fare("inr 4200") == Decimal("4200")


class TestNormalizeIata:
    def test_lowercase(self):
        assert normalize_iata("bom") == "BOM"

    def test_uppercase(self):
        assert normalize_iata("DEL") == "DEL"

    def test_with_spaces(self):
        assert normalize_iata("  BLR  ") == "BLR"

    def test_four_chars_invalid(self):
        assert normalize_iata("BOMB") is None

    def test_two_chars_invalid(self):
        assert normalize_iata("BO") is None

    def test_empty_returns_none(self):
        assert normalize_iata("") is None

    def test_with_digit_invalid(self):
        assert normalize_iata("B0M") is None


class TestNormalizeFareClass:
    def test_economy_lowercase(self):
        assert normalize_fare_class("economy") == "Economy"

    def test_eco(self):
        assert normalize_fare_class("eco") == "Economy"

    def test_y_class(self):
        assert normalize_fare_class("y") == "Economy"

    def test_business(self):
        assert normalize_fare_class("business") == "Business"

    def test_business_class(self):
        assert normalize_fare_class("business class") == "Business"

    def test_first_class(self):
        assert normalize_fare_class("first class") == "First"

    def test_premium_economy(self):
        assert normalize_fare_class("premium economy") == "Premium Economy"

    def test_unknown_returns_none(self):
        assert normalize_fare_class("turbo") is None

    def test_empty_returns_none(self):
        assert normalize_fare_class("") is None


class TestNormalizeAvailability:
    def test_available(self):
        assert normalize_availability("Available") == "available"

    def test_open(self):
        assert normalize_availability("open") == "available"

    def test_sold_out(self):
        assert normalize_availability("Sold Out") == "sold_out"

    def test_sold_out_underscore(self):
        assert normalize_availability("sold_out") == "sold_out"

    def test_cancelled(self):
        assert normalize_availability("cancelled") == "cancelled"

    def test_canceled_american_spelling(self):
        assert normalize_availability("canceled") == "cancelled"

    def test_unknown_string(self):
        assert normalize_availability("maybe") == "unknown"

    def test_empty_string(self):
        assert normalize_availability("") == "unknown"
