"""
scraper/pipelines/validator.py
Field-level and cross-field validation for airfare observations.

This is a second validation pass that runs AFTER Pydantic schema validation.
Pydantic catches structural/type errors; this validator catches domain-specific
business rule violations.

Validation result:
    status = "valid"    → passes all checks
    status = "rejected" → fails a check; rejection_reason is set
    status = "duplicate"→ detected as duplicate of existing record
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Tuple

from backend.app.schemas.airfare import VALID_DEP_BANDS, VALID_LEAD_WINDOWS, AirfareObservationCreate

logger = logging.getLogger(__name__)

# Plausible maximum one-way domestic fare (INR).
MAX_PLAUSIBLE_FARE_INR = Decimal("75000")
MIN_PLAUSIBLE_FARE_INR = Decimal("500")


@dataclass
class ValidationResult:
    """Outcome of validating one observation."""
    status: str                   # "valid" | "rejected"
    rejection_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"


def _check_total_fare_present(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.total_fare is None:
        return False, "missing_total_fare"
    return True, None


def _check_fare_positive(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.total_fare <= Decimal("0"):
        return False, f"non_positive_total_fare:{obs.total_fare}"
    return True, None


def _check_base_fare_positive(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.base_fare is not None and obs.base_fare <= Decimal("0"):
        return False, f"non_positive_base_fare:{obs.base_fare}"
    return True, None


def _check_fare_minimum(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.total_fare < MIN_PLAUSIBLE_FARE_INR:
        return False, f"fare_below_minimum:{obs.total_fare}<{MIN_PLAUSIBLE_FARE_INR}"
    return True, None


def _check_base_lte_total(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.base_fare is not None and obs.base_fare > obs.total_fare:
        return False, f"base_fare_exceeds_total:{obs.base_fare}>{obs.total_fare}"
    return True, None


def _check_fee_sum_tolerance(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.base_fare is not None:
        expected_total = (
            obs.base_fare +
            (obs.taxes or Decimal("0")) +
            (obs.udf_psf or Decimal("0")) +
            (obs.convenience_fee or Decimal("0")) +
            (obs.other_fees or Decimal("0"))
        )
        if abs(obs.total_fare - expected_total) > Decimal("0.05"):
            return False, f"fee_breakdown_mismatch:total({obs.total_fare})!=expected({expected_total})"
    return True, None


def _check_lead_days_non_negative(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.lead_days is not None and obs.lead_days < 0:
        return False, f"negative_lead_days:{obs.lead_days}"
    return True, None


def _check_dep_band(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.dep_band is not None and obs.dep_band not in VALID_DEP_BANDS:
        return False, f"invalid_dep_band:{obs.dep_band}"
    return True, None


def _check_target_lead_window(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.target_lead_window is not None and obs.target_lead_window not in VALID_LEAD_WINDOWS:
        return False, f"invalid_target_lead_window:{obs.target_lead_window}"
    return True, None


def _check_currency(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.currency != "INR":
        return False, f"unsupported_currency:{obs.currency}"
    return True, None


def _check_availability_not_sold_out(obs: AirfareObservationCreate) -> Tuple[bool, Optional[str]]:
    if obs.availability == "sold_out" or obs.is_sold_out:
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


def _warn_fare_suspicious_high(obs: AirfareObservationCreate) -> Optional[str]:
    if obs.total_fare > MAX_PLAUSIBLE_FARE_INR:
        return f"fare_unusually_high:{obs.total_fare}"
    return None


_HARD_RULES = [
    _check_total_fare_present,
    _check_fare_positive,
    _check_base_fare_positive,
    _check_fare_minimum,
    _check_base_lte_total,
    _check_fee_sum_tolerance,
    _check_lead_days_non_negative,
    _check_dep_band,
    _check_target_lead_window,
    _check_currency,
    _check_availability_not_sold_out,
    _check_availability_not_cancelled,
    _check_route_not_self,
]

_WARNING_RULES = [
    _warn_fare_suspicious_high,
]


def validate_observation(obs: AirfareObservationCreate) -> ValidationResult:
    """Run all validation rules against a single observation."""
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
    """Validate a list of observations."""
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
