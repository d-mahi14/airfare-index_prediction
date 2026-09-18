"""
backend/app/schemas/airfare.py
Pydantic v2 schemas for airfare domain objects.

These are used for:
  1. Validating observations produced by collectors before DB write.
  2. Validating API request/response bodies.
  3. Data transfer between pipeline layers.

Key design decisions:
  - Decimal is used for monetary fields (not float) for the same reason
    the DB uses NUMERIC.
  - lead_days is computed from travel_date and collection_date if not provided.
  - total_fare >= base_fare is enforced at the schema level as well as DB level.
  - status is constrained to known values via Literal.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

VALID_AVAILABILITIES = {"available", "sold_out", "cancelled", "unknown"}
VALID_FARE_CLASSES = {"Economy", "Business", "First", "Premium Economy"}
VALID_CURRENCIES = {"INR"}  # extend when multi-currency is supported


def _compute_lead_days(collection_timestamp: datetime, travel_date: date) -> int:
    """Calculate lead_days = travel_date - collection_date (in days)."""
    collection_date = collection_timestamp.date()
    delta = travel_date - collection_date
    return delta.days


# ---------------------------------------------------------------------------
# AirfareObservation
# ---------------------------------------------------------------------------

class AirfareObservationCreate(BaseModel):
    """
    Schema for creating a new airfare observation.

    This is what a Collector produces and what the StoragePipeline consumes.
    All validation happens here before any DB write.
    """

    # Identity
    collection_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this quote was collected",
    )
    source_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name of the data source (e.g. MockCollector, IndiGo)",
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
        description="Days between collection and travel. Computed if not provided.",
    )
    fare_class: str = Field(default="Economy", description="Economy | Business | First | Premium Economy")

    # Fares — Decimal to avoid floating-point issues
    base_fare: Optional[Decimal] = Field(
        None,
        ge=Decimal("0"),
        description="Base fare before taxes/fees (INR)",
    )
    taxes: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    fees: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    total_fare: Decimal = Field(..., ge=Decimal("0"), description="Total payable fare (INR)")

    currency: str = Field(default="INR", max_length=3)
    availability: str = Field(default="available")

    # Optional metadata
    raw_reference: Optional[str] = Field(
        None, description="Filesystem path to raw collected file"
    )

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
            raise ValueError(
                f"Invalid availability '{v}'. Must be one of {VALID_AVAILABILITIES}"
            )
        return lower

    @field_validator("fare_class")
    @classmethod
    def validate_fare_class(cls, v: str) -> str:
        # Normalize: title-case the value for consistent storage
        normalized = v.strip().title()
        if normalized not in VALID_FARE_CLASSES:
            raise ValueError(
                f"Invalid fare_class '{v}'. Must be one of {VALID_FARE_CLASSES}"
            )
        return normalized

    @model_validator(mode="after")
    def check_route_not_self(self) -> "AirfareObservationCreate":
        if self.origin == self.destination:
            raise ValueError(
                f"origin and destination must differ, got '{self.origin}'"
            )
        return self

    @model_validator(mode="after")
    def check_total_gte_base(self) -> "AirfareObservationCreate":
        if self.base_fare is not None and self.total_fare < self.base_fare:
            raise ValueError(
                f"total_fare ({self.total_fare}) must be >= base_fare ({self.base_fare})"
            )
        return self

    @model_validator(mode="after")
    def check_travel_date_not_past(self) -> "AirfareObservationCreate":
        collection_date = self.collection_timestamp.date()
        if self.travel_date < collection_date:
            raise ValueError(
                f"travel_date ({self.travel_date}) is before "
                f"collection_date ({collection_date}). lead_days would be negative."
            )
        return self

    @model_validator(mode="after")
    def compute_lead_days(self) -> "AirfareObservationCreate":
        """Auto-compute lead_days if not provided; validate if provided."""
        computed = _compute_lead_days(self.collection_timestamp, self.travel_date)
        if self.lead_days is None:
            self.lead_days = computed
        elif self.lead_days != computed:
            raise ValueError(
                f"Provided lead_days={self.lead_days} does not match computed "
                f"value {computed} from travel_date={self.travel_date} "
                f"and collection_date={self.collection_timestamp.date()}"
            )
        return self

    @property
    def route_code(self) -> str:
        return f"{self.origin}-{self.destination}"


class AirfareObservationRead(BaseModel):
    """Schema for reading an airfare observation from the DB (API response)."""

    id: uuid.UUID
    collection_timestamp: datetime
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
    fees: Optional[Decimal] = None
    total_fare: Decimal
    currency: str
    availability: Optional[str] = None
    status: str
    rejection_reason: Optional[str] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CollectionRun
# ---------------------------------------------------------------------------

class CollectionRunCreate(BaseModel):
    source_name: str
    route_code: str
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CollectionRunRead(BaseModel):
    id: uuid.UUID
    source_id: int
    route_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    records_found: int = 0
    records_saved: int = 0
    records_rejected: int = 0
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}
