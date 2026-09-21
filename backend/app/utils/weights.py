"""
backend/app/utils/weights.py
Route and Lead-Time Weight loaders, normalizers, and database synchronizers.
"""
import csv
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from sqlalchemy.orm import Session

from backend.app.models.index import LeadTimeWeight, RouteWeight
from backend.app.models.airfare import Route

DEFAULT_DGCA_CSV = Path(__file__).parent.parent.parent.parent / "data" / "reference" / "dgca_city_pair_traffic.csv"
DEFAULT_LEAD_WEIGHTS_YAML = Path(__file__).parent.parent.parent.parent / "config" / "lead_time_weights.yaml"


def load_dgca_route_weights(csv_path: Optional[Path | str] = None) -> List[Dict]:
    """
    Load city-pair passenger traffic from DGCA CSV, normalize weights so they sum to 1.000000.
    """
    path = Path(csv_path) if csv_path else DEFAULT_DGCA_CSV
    if not path.exists():
        raise FileNotFoundError(f"DGCA city-pair traffic CSV not found at: {path}")

    records = []
    total_passengers = Decimal("0")

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            passengers = Decimal(row["annual_passengers"].strip())
            total_passengers += passengers
            records.append({
                "origin": row["origin"].strip().upper(),
                "destination": row["destination"].strip().upper(),
                "route_code": row["route_code"].strip().upper(),
                "annual_passengers": int(passengers),
                "placeholder": row.get("placeholder", "true").strip().lower() == "true",
            })

    if total_passengers == Decimal("0"):
        raise ValueError("Total passenger volume in DGCA traffic file is zero.")

    # Calculate normalized weights with 6 decimal places
    weight_sum = Decimal("0")
    for r in records:
        w = (Decimal(r["annual_passengers"]) / total_passengers).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        r["weight"] = w
        weight_sum += w

    # Ensure exact sum to 1.000000 by adjusting residual on highest weight
    diff = Decimal("1.000000") - weight_sum
    if diff != Decimal("0") and records:
        max_rec = max(records, key=lambda x: x["weight"])
        max_rec["weight"] = max_rec["weight"] + diff

    return records


def load_lead_time_weights(yaml_path: Optional[Path | str] = None) -> List[Dict]:
    """
    Load lead-time weights from YAML, ensuring they normalize and sum to 1.000000.
    """
    path = Path(yaml_path) if yaml_path else DEFAULT_LEAD_WEIGHTS_YAML
    if not path.exists():
        raise FileNotFoundError(f"Lead time weights YAML not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    raw_items = data.get("lead_time_weights", [])
    if not raw_items:
        raise ValueError("No lead_time_weights found in configuration.")

    total_weight = sum(Decimal(str(item["weight"])) for item in raw_items)
    if total_weight == Decimal("0"):
        raise ValueError("Total lead time weight in configuration is zero.")

    records = []
    weight_sum = Decimal("0")
    for item in raw_items:
        w = (Decimal(str(item["weight"])) / total_weight).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        records.append({
            "lead_days": int(item["lead_days"]),
            "weight": w,
            "name": item.get("name", f"T+{item['lead_days']}"),
            "description": item.get("description", ""),
        })
        weight_sum += w

    diff = Decimal("1.000000") - weight_sum
    if diff != Decimal("0") and records:
        records[0]["weight"] = records[0]["weight"] + diff

    return records


def sync_route_weights_to_db(
    session: Session,
    valid_from: Optional[date] = None,
    csv_path: Optional[Path | str] = None,
) -> int:
    """
    Synchronize normalized DGCA route weights to the route_weights database table.
    """
    effective_date = valid_from or date(2024, 1, 1)
    records = load_dgca_route_weights(csv_path=csv_path)
    count = 0

    for r in records:
        # Find or create route
        route = session.query(Route).filter(Route.route_code == r["route_code"]).first()
        if not route:
            route = Route(
                origin=r["origin"],
                destination=r["destination"],
                route_code=r["route_code"],
                is_active=True,
            )
            session.add(route)
            session.flush()

        # Update or insert route weight
        rw = (
            session.query(RouteWeight)
            .filter(
                RouteWeight.route_id == route.id,
                RouteWeight.valid_from == effective_date,
            )
            .first()
        )
        if not rw:
            rw = RouteWeight(
                route_id=route.id,
                weight=r["weight"],
                valid_from=effective_date,
                valid_to=None,
                is_active=True,
                source="DGCA_City_Pair_Traffic",
            )
            session.add(rw)
        else:
            rw.weight = r["weight"]
            rw.is_active = True

        count += 1

    session.commit()
    return count


def sync_lead_time_weights_to_db(
    session: Session,
    valid_from: Optional[date] = None,
    yaml_path: Optional[Path | str] = None,
) -> int:
    """
    Synchronize normalized lead-time weights to the lead_time_weights database table.
    """
    effective_date = valid_from or date(2024, 1, 1)
    records = load_lead_time_weights(yaml_path=yaml_path)
    count = 0

    for r in records:
        ltw = (
            session.query(LeadTimeWeight)
            .filter(
                LeadTimeWeight.lead_days == r["lead_days"],
                LeadTimeWeight.valid_from == effective_date,
            )
            .first()
        )
        if not ltw:
            ltw = LeadTimeWeight(
                lead_days=r["lead_days"],
                weight=r["weight"],
                valid_from=effective_date,
                valid_to=None,
                is_active=True,
                source="DGCA_Booking_Curve_Model",
            )
            session.add(ltw)
        else:
            ltw.weight = r["weight"]
            ltw.is_active = True

        count += 1

    session.commit()
    return count
