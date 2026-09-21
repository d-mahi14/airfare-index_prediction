"""create_clean_fares_view

Revision ID: 003_create_clean_fares_view
Revises: 002_harden_milestone1_schema
Create Date: 2026-09-21

Creates the clean_fares SQL view for active, non-outlier, non-sold-out airfare observations.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '003_create_clean_fares_view'
down_revision = '002_harden_milestone1_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE VIEW clean_fares AS
    SELECT 
        obs.id,
        obs.collection_run_id,
        obs.collection_timestamp,
        obs.collection_date,
        obs.source_id,
        obs.route_id,
        obs.airline_id,
        obs.flight_number,
        obs.travel_date,
        obs.lead_days,
        obs.fare_class,
        obs.base_fare,
        obs.taxes,
        obs.udf_psf,
        obs.convenience_fee,
        obs.other_fees,
        obs.total_fare,
        obs.currency,
        obs.dep_time,
        obs.dep_band,
        obs.stops,
        obs.duration_min,
        obs.is_sold_out,
        obs.seats_left,
        obs.availability,
        obs.status,
        obs.is_synthetic,
        obs.target_lead_window,
        obs.is_outlier,
        obs.is_imputed,
        obs.created_at,
        r.route_code,
        r.origin,
        r.destination,
        a.name AS airline_name_resolved,
        a.iata_code AS airline_iata_resolved,
        s.name AS source_name_resolved
    FROM airfare_observations obs
    JOIN routes r ON obs.route_id = r.id
    LEFT JOIN airlines a ON obs.airline_id = a.id
    JOIN sources s ON obs.source_id = s.id
    WHERE obs.status = 'valid'
      AND obs.is_outlier = FALSE
      AND obs.is_sold_out = FALSE
      AND (obs.availability IS NULL OR obs.availability = 'available');
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS clean_fares CASCADE;")
