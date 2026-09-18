"""
scraper/pipelines/validator.py
Field-level and cross-field validation for airfare observations.

This is a second validation pass that runs AFTER Pydantic schema validation.
Pydantic catches structural/type errors; this validator catches domain-specific
business rule violations that need richer context (e.g., route plausibility).

Validation result:
    status = "valid"    → passes all checks
    status = "rejected" → fails a check; rejection_reason is set
    status = "duplicate"→ detected as duplicate of existing record

Every rejected observation is recorded with a reason — never silently discarded.
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Tuple

from backend.app.schemas.airfare import AirfareObservationCreate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Plausible maximum one-way domestic fare (INR).
# ₹75,000 is extremely high but possible for last-minute business class.
# We flag above this for review, not auto-reject.
MAX_PLAUSIBLE_FARE_INR = Decimal("75000")

# Absolute minimum fare — below this, something is clearly wrong
MIN_PLAUSIBLE_FARE_INR = Decimal("500")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Outcome of validating one observation."""
    status: str                   # "valid" | "rejected"
    rejection_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"


# ---------------------------------------------------------------------------
# Individual rule functions (each returns (passed: bool, reason: str | None))
# ---------------------------------------------------------------------------

def _check_total_fare_present(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.total_fare is None:
        return False, "missing_total_fare"
    return True, None


def _check_fare_positive(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.total_fare <= Decimal("0"):
        return False, f"non_positive_total_fare:{obs.total_fare}"
    return True, None


def _check_fare_minimum(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.total_fare < MIN_PLAUSIBLE_FARE_INR:
        return False, f"fare_below_minimum:{obs.total_fare}<{MIN_PLAUSIBLE_FARE_INR}"
    return True, None


def _check_base_lte_total(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.base_fare is not None and obs.base_fare > obs.total_fare:
        return False, f"base_fare_exceeds_total:{obs.base_fare}>{obs.total_fare}"
    return True, None


def _check_lead_days_non_negative(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.lead_days is not None and obs.lead_days < 0:
        return False, f"negative_lead_days:{obs.lead_days}"
    return True, None


def _check_currency(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.currency != "INR":
        return False, f"unsupported_currency:{obs.currency}"
    return True, None


def _check_availability_not_sold_out(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    """
    Sold-out flights are rejected for index purposes.
    They don't represent an actionable market price.
    """
    if obs.availability == "sold_out":
        return False, "sold_out_flight"
    return True, None


def _check_availability_not_cancelled(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.availability == "cancelled":
        return False, "cancelled_flight"
    return True, None


def _check_route_not_self(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.origin == obs.destination:
        return False, f"origin_equals_destination:{obs.origin}"
    return True, None


# ---------------------------------------------------------------------------
# Warning rules (don't reject, but flag for review)
# ---------------------------------------------------------------------------

def _warn_fare_suspicious_high(obs: AirfareObservationCreate) -> Optional[str]:
    if obs.total_fare > MAX_PLAUSIBLE_FARE_INR:
        return f"fare_unusually_high:{obs.total_fare}"
    return None


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

# Ordered list of hard validation rules (any failure → rejected)
_HARD_RULES = [
    _check_total_fare_present,
    _check_fare_positive,
    _check_fare_minimum,
    _check_base_lte_total,
    _check_lead_days_non_negative,
    _check_currency,
    _check_availability_not_sold_out,
    _check_availability_not_cancelled,
    _check_route_not_self,
]

_WARNING_RULES = [
    _warn_fare_suspicious_high,
]


def validate_observation(obs: AirfareObservationCreate) -> ValidationResult:
    """
    Run all validation rules against a single observation.

    Hard failures → status="rejected" with reason.
    Warnings → status remains "valid" but warnings list is populated.
    """
    warnings: List[str] = []

    for rule in _HARD_RULES:
        passed, reason = rule(obs)
        if not passed:
            logger.debug(
                f"Observation rejected: {reason} "
                f"[{obs.origin}-{obs.destination} {obs.airline_name}]"
            )
            return ValidationResult(status="rejected", rejection_reason=reason)

    for warn_rule in _WARNING_RULES:
        warning = warn_rule(obs)
        if warning:
            logger.warning(f"Observation warning: {warning}")
            warnings.append(warning)

    return ValidationResult(status="valid", warnings=warnings)


def validate_observations(
    observations: List[AirfareObservationCreate],
) -> Tuple[List[AirfareObservationCreate], List[Tuple[AirfareObservationCreate, str]]]:
    """
    Validate a list of observations.

    Returns:
        valid_obs   -- list of observations that passed validation
        rejected    -- list of (observation, rejection_reason) tuples
    """
    valid_obs: List[AirfareObservationCreate] = []
    rejected: List[Tuple[AirfareObservationCreate, str]] = []

    for obs in observations:
        result = validate_observation(obs)
        if result.is_valid:
            valid_obs.append(obs)
        else:
            rejected.append((obs, result.rejection_reason or "unknown"))

    logger.info(
        f"Validation: {len(valid_obs)} valid, {len(rejected)} rejected "
        f"from {len(observations)} total"
    )
    return valid_obs, rejected
