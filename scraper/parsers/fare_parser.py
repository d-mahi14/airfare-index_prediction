"""
scraper/parsers/fare_parser.py
Fare string parser and normalizer.

Handles messy fare strings from real websites:
  "₹ 4,200"     → Decimal("4200.00")
  "Rs. 4200"    → Decimal("4200.00")
  "INR 4,200.50" → Decimal("4200.50")
  "4200"        → Decimal("4200.00")
  "4,200.00"    → Decimal("4200.00")

Also normalizes IATA codes and fare class labels.

This module is intentionally pure-function (no side effects, no DB access)
so it can be tested in isolation with simple assertions.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Optional


# Patterns for known Indian currency prefixes
_CURRENCY_PREFIXES = re.compile(
    r"^[\s]*(?:₹|Rs\.?|INR|inr)\s*",
    re.IGNORECASE,
)

# Strip commas and whitespace after removing prefix
_WHITESPACE_COMMA = re.compile(r"[\s,]+")


def parse_fare(raw: str | int | float | Decimal) -> Optional[Decimal]:
    """
    Parse a raw fare value into a Decimal.

    Returns None if the value is empty, null-like, or unparseable.

    >>> parse_fare("₹ 4,200")
    Decimal('4200')
    >>> parse_fare("Rs. 4200.50")
    Decimal('4200.50')
    >>> parse_fare(4200)
    Decimal('4200')
    >>> parse_fare("") is None
    True
    >>> parse_fare("N/A") is None
    True
    """
    if raw is None:
        return None

    # Already Decimal
    if isinstance(raw, Decimal):
        return raw if raw >= 0 else None

    # Numeric types
    if isinstance(raw, (int, float)):
        try:
            d = Decimal(str(raw))
            return d if d >= 0 else None
        except InvalidOperation:
            return None

    # String processing
    raw_str = str(raw).strip()
    if not raw_str or raw_str.lower() in {"n/a", "na", "null", "none", "-", "--"}:
        return None

    # Remove currency prefix
    cleaned = _CURRENCY_PREFIXES.sub("", raw_str)
    # Remove commas and extra whitespace
    cleaned = _WHITESPACE_COMMA.sub("", cleaned)

    if not cleaned:
        return None

    try:
        d = Decimal(cleaned)
        return d if d >= 0 else None
    except InvalidOperation:
        return None


def normalize_iata(code: str) -> Optional[str]:
    """
    Normalize an IATA airport code to uppercase, 3 characters.

    Returns None if the code is invalid.

    >>> normalize_iata("bom")
    'BOM'
    >>> normalize_iata("  DEL  ")
    'DEL'
    >>> normalize_iata("BOMB")  # 4 chars — invalid
    None
    """
    if not code:
        return None
    cleaned = code.strip().upper()
    # IATA airport codes are exactly 3 alphabetic characters
    if re.fullmatch(r"[A-Z]{3}", cleaned):
        return cleaned
    return None


def normalize_fare_class(raw: str) -> Optional[str]:
    """
    Normalize a fare class label to a canonical value.

    Canonical values: Economy, Business, First, Premium Economy

    >>> normalize_fare_class("economy")
    'Economy'
    >>> normalize_fare_class("Business Class")
    'Business'
    >>> normalize_fare_class("Y")
    'Economy'
    """
    if not raw:
        return None
    lower = raw.strip().lower()

    _MAPPINGS = {
        "economy": "Economy",
        "eco": "Economy",
        "y": "Economy",
        "e": "Economy",
        "business": "Business",
        "biz": "Business",
        "business class": "Business",
        "j": "Business",
        "c": "Business",
        "first": "First",
        "first class": "First",
        "f": "First",
        "premium economy": "Premium Economy",
        "premium eco": "Premium Economy",
        "prem economy": "Premium Economy",
        "w": "Premium Economy",
    }
    return _MAPPINGS.get(lower)


def normalize_availability(raw: str) -> str:
    """
    Map raw availability strings to canonical values.

    Canonical: available | sold_out | cancelled | unknown

    >>> normalize_availability("Available")
    'available'
    >>> normalize_availability("Sold Out")
    'sold_out'
    """
    if not raw:
        return "unknown"
    lower = raw.strip().lower()
    _MAP = {
        "available": "available",
        "open": "available",
        "yes": "available",
        "sold out": "sold_out",
        "sold_out": "sold_out",
        "soldout": "sold_out",
        "no seats": "sold_out",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "cancel": "cancelled",
    }
    return _MAP.get(lower, "unknown")
