"""
backend/app/schemas/airfare.py
Pydantic v2 schemas for airfare domain objects.

These are used for:
  1. Validating observations produced by collectors before DB write.
  2. Validating API request/response bodies.
  3. Data transfer between pipeline layers.

Key design decisions:
  - Decimal is used for monetary fields (not float) to avoid precision errors.
  - Fee breakdown: taxes, udf_psf, convenience_fee, other_fees.
  - Total fare must match base_fare + sum(fees) within 0.05 tolerance.
  - lead_days is computed in Asia/Kolkata timezone: travel_date - collection_date.
  - dep_band is validated or auto-derived from dep_time.
"""
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_AVAILABILITIES = {"available", "sold_out", "cancelled", "unknown"}
VALID_FARE_CLASSES = {"Economy", "Business", "First", "Premium Economy"}
VALID_CURRENCIES = {"INR"}
VALID_DEP_BANDS = {"early", "morning", "afternoon", "evening", "night"}
VALID_LEAD_WINDOWS = {1, 7, 15, 30, 45}
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def _get_kolkata_date(ts: datetime) -> date:
    """Return calendar date in Asia/Kolkata timezone."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(KOLKATA_TZ).date()


def _compute_lead_days(collection_timestamp: datetime, travel_date: date) -> int:
    """Calculate lead_days = travel_date - collection_date (Asia/Kolkata)."""
    collection_date = _get_kolkata_date(collection_timestamp)
    delta = travel_date - collection_date
    return delta.days


def _derive_dep_band(dep_t: time) -> str:
    """Derive departure band from local departure time."""
    h = dep_t.hour
    if 0 <= h < 6:
        return "early"
    elif 6 <= h < 12:
        return "morning"
    elif 12 <= h < 17:
        return "afternoon"
    elif 17 <= h < 21:
        return "evening"
    else:
        return "night"


# ---------------------------------------------------------------------------
# AirfareObservation
# ---------------------------------------------------------------------------

class AirfareObservationCreate(BaseModel):
    """
    Schema for creating a new airfare observation.
    Validated before database persistence.
    """

    # Identity & timestamps
    collection_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when quote was collected",
    )
    collection_date: Optional[date] = Field(
        None,
        description="Calendar date in Asia/Kolkata (auto-computed from collection_timestamp)",
    )
    source_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Data source name (e.g. MockCollector, IndiGo)",
    )

    # Route
    origin: str = Field(..., min_length=3, max_length=3, description="IATA origin airport code")
    destination: str = Field(..., min_length=3, max_length=3, description="IATA destination airport code")

    # Flight details
    airline_name: str = Field(..., min_length=1, max_length=100)
    airline_iata: Optional[str] = Field(None, max_length=2)
    flight_number: Optional[str] = Field(None, max_length=20)
    travel_date: date = Field(..., description="Date of travel (departure date)")
    lead_days: Optional[int] = Field(
        None,
        ge=0,
        description="Days between collection (Asia/Kolkata) and travel. Computed if omitted.",
    )
    fare_class: str = Field(default="Economy", description="Economy | Business | First | Premium Economy")

    # Fares & Fee Breakdown (INR)
    base_fare: Optional[Decimal] = Field(
        None,
        gt=Decimal("0"),
        description="Base fare before taxes/fees (INR)",
    )
    taxes: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), description="GST / airline taxes")
    udf_psf: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), description="User Development & Passenger Service Fee")
    convenience_fee: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), description="Booking convenience fee")
    other_fees: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), description="Miscellaneous fees")
    fees: Optional[Decimal] = Field(None, description="Legacy fee total for backward compatibility")
    total_fare: Decimal = Field(..., gt=Decimal("0"), description="Total payable fare (INR)")

    currency: str = Field(default="INR", max_length=3)
    availability: str = Field(default="available")

    # Schedule and flight features
    dep_time: Optional[time] = Field(None, description="Departure time")
    dep_band: Optional[str] = Field(None, description="early | morning | afternoon | evening | night")
    stops: int = Field(default=0, ge=0, description="0 for non-stop")
    duration_min: Optional[int] = Field(None, ge=0, description="Duration in minutes")
    is_sold_out: bool = Field(default=False)
    seats_left: Optional[int] = Field(None, ge=0)

    # Pipeline flags
    is_synthetic: bool = Field(default=True)
    target_lead_window: Optional[int] = Field(None, description="1 | 7 | 15 | 30 | 45")
    is_outlier: bool = Field(default=False)
    is_imputed: bool = Field(default=False)
    raw_reference: Optional[str] = Field(None, description="Path to raw JSON file")

    # --- Validators ---

    @field_validator("origin", "destination")
    @classmethod
    def uppercase_iata(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in VALID_CURRENCIES:
            raise ValueError(f"Unsupported currency '{v}'. Supported: {VALID_CURRENCIES}")
        return upper

    @field_validator("availability")
    @classmethod
    def validate_availability(cls, v: str) -> str:
        lower = v.strip().lower()
        if lower not in VALID_AVAILABILITIES:
            raise ValueError(f"Invalid availability '{v}'. Must be one of {VALID_AVAILABILITIES}")
        return lower

    @field_validator("fare_class")
    @classmethod
    def validate_fare_class(cls, v: str) -> str:
        normalized = v.strip().title()
        if normalized not in VALID_FARE_CLASSES:
            raise ValueError(f"Invalid fare_class '{v}'. Must be one of {VALID_FARE_CLASSES}")
        return normalized

    @field_validator("dep_band")
    @classmethod
    def validate_dep_band(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        lower = v.strip().lower()
        if lower not in VALID_DEP_BANDS:
            raise ValueError(f"Invalid dep_band '{v}'. Must be one of {VALID_DEP_BANDS}")
        return lower

    @field_validator("target_lead_window")
    @classmethod
    def validate_target_lead_window(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in VALID_LEAD_WINDOWS:
            raise ValueError(f"Invalid target_lead_window {v}. Must be one of {VALID_LEAD_WINDOWS}")
        return v

    @model_validator(mode="after")
    def check_route_not_self(self) -> "AirfareObservationCreate":
        if self.origin == self.destination:
            raise ValueError(f"origin and destination must differ, got '{self.origin}'")
        return self

    @model_validator(mode="after")
    def compute_collection_date_and_lead_days(self) -> "AirfareObservationCreate":
        kolkata_date = _get_kolkata_date(self.collection_timestamp)
        if self.collection_date is None:
            self.collection_date = kolkata_date

        if self.travel_date < self.collection_date:
            raise ValueError(
                f"travel_date ({self.travel_date}) is before collection_date "
                f"({self.collection_date} Asia/Kolkata). lead_days would be negative."
            )

        computed_lead = (self.travel_date - self.collection_date).days
        if self.lead_days is None:
            self.lead_days = computed_lead
        elif self.lead_days != computed_lead:
            raise ValueError(
                f"Provided lead_days={self.lead_days} does not match computed "
                f"value {computed_lead} from travel_date={self.travel_date} "
                f"and collection_date={self.collection_date}"
            )
        return self

    @model_validator(mode="after")
    def handle_legacy_fees_and_verify_sum(self) -> "AirfareObservationCreate":
        # Handle legacy fees field
        if self.fees is not None and self.other_fees == Decimal("0") and self.udf_psf == Decimal("0") and self.convenience_fee == Decimal("0"):
            self.other_fees = self.fees

        # If base_fare is provided, total must equal sum of base + taxes + fees within tolerance
        if self.base_fare is not None:
            if self.total_fare < self.base_fare:
                raise ValueError(
                    f"total_fare ({self.total_fare}) must be >= base_fare ({self.base_fare})"
                )
            computed_total = self.base_fare + self.taxes + self.udf_psf + self.convenience_fee + self.other_fees
            if abs(self.total_fare - computed_total) > Decimal("0.05"):
                raise ValueError(
                    f"total_fare ({self.total_fare}) must equal base_fare ({self.base_fare}) + "
                    f"taxes ({self.taxes}) + udf_psf ({self.udf_psf}) + "
                    f"convenience_fee ({self.convenience_fee}) + other_fees ({self.other_fees}) = {computed_total}"
                )
        return self

    @model_validator(mode="after")
    def auto_derive_dep_band(self) -> "AirfareObservationCreate":
        if self.dep_band is None and self.dep_time is not None:
            self.dep_band = _derive_dep_band(self.dep_time)
        return self

    @property
    def route_code(self) -> str:
        return f"{self.origin}-{self.destination}"


class AirfareObservationRead(BaseModel):
    """Schema for reading an airfare observation from the DB (API response)."""

    id: uuid.UUID
    collection_timestamp: datetime
    collection_date: date
    source_name: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    airline_name: Optional[str] = None
    flight_number: Optional[str] = None
    travel_date: date
    lead_days: int
    fare_class: str
    base_fare: Optional[Decimal] = None
    taxes: Optional[Decimal] = None
    udf_psf: Optional[Decimal] = None
    convenience_fee: Optional[Decimal] = None
    other_fees: Optional[Decimal] = None
    total_fare: Decimal
    currency: str
    dep_time: Optional[time] = None
    dep_band: Optional[str] = None
    stops: int = 0
    duration_min: Optional[int] = None
    is_sold_out: bool = False
    seats_left: Optional[int] = None
    is_synthetic: bool = True
    target_lead_window: Optional[int] = None
    is_outlier: bool = False
    is_imputed: bool = False
    availability: Optional[str] = None
    status: str
    rejection_reason: Optional[str] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CollectionRun
# ---------------------------------------------------------------------------

class CollectionRunCreate(BaseModel):
    source_name: str
    route_code: Optional[str] = None
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = Field(default="running")


class CollectionRunRead(BaseModel):
    id: uuid.UUID
    source_id: int
    route_id: Optional[int] = None
    status: str = "running"
    start_time: datetime
    end_time: Optional[datetime] = None
    records_found: int = 0
    records_saved: int = 0
    records_rejected: int = 0
    blocked_count: int = 0
    captcha_count: int = 0
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}
