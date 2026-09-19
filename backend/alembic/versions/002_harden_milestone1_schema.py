"""harden_milestone1_schema

Revision ID: 002_harden_milestone1_schema
Revises: 001_initial_schema
Create Date: 2026-09-19

Hardens Milestone 1 schema:
  - Splits airfare_observations fees into taxes, udf_psf, convenience_fee, other_fees
  - Adds departure metadata: dep_time, dep_band, stops, duration_min
  - Adds booking metadata: is_sold_out, seats_left, is_synthetic, target_lead_window, is_outlier, is_imputed
  - Adds collection_date and dedup unique constraint on (source_id, flight_number, travel_date, fare_class, collection_date)
  - Adds CHECK constraints: fares > 0, valid departure bands, valid lead windows
  - Updates index_values: frequency, variant, n_obs, coverage, and 4-tuple unique key
  - Updates route_weights: valid_from, valid_to, and period unique key
  - Creates lead_time_weights table
  - Updates collection_runs: status, blocked_count, captcha_count, nullable route_id
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '002_harden_milestone1_schema'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. collection_runs ─────────────────────────────────────────
    op.add_column('collection_runs', sa.Column('status', sa.String(length=20), nullable=False, server_default='running'))
    op.add_column('collection_runs', sa.Column('blocked_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('collection_runs', sa.Column('captcha_count', sa.Integer(), nullable=False, server_default='0'))
    op.alter_column('collection_runs', 'route_id', nullable=True)

    # ─── 2. airfare_observations ───────────────────────────────────
    # Fee breakdown
    op.add_column('airfare_observations', sa.Column('udf_psf', sa.Numeric(precision=10, scale=2), nullable=True, server_default='0'))
    op.add_column('airfare_observations', sa.Column('convenience_fee', sa.Numeric(precision=10, scale=2), nullable=True, server_default='0'))
    op.add_column('airfare_observations', sa.Column('other_fees', sa.Numeric(precision=10, scale=2), nullable=True, server_default='0'))

    # Migrate existing fees into other_fees before dropping fees column
    op.execute(
        "UPDATE airfare_observations SET other_fees = COALESCE(fees, 0) "
        "WHERE other_fees IS NULL OR other_fees = 0"
    )
    op.drop_column('airfare_observations', 'fees')

    # Collection date in Asia/Kolkata timezone
    op.add_column('airfare_observations', sa.Column('collection_date', sa.Date(), nullable=True))
    op.execute(
        "UPDATE airfare_observations "
        "SET collection_date = CAST(collection_timestamp AT TIME ZONE 'Asia/Kolkata' AS DATE) "
        "WHERE collection_date IS NULL"
    )
    op.alter_column('airfare_observations', 'collection_date', nullable=False)
    op.create_index('ix_airfare_observations_collection_date', 'airfare_observations', ['collection_date'])

    # Flight & market metadata
    op.add_column('airfare_observations', sa.Column('dep_time', sa.Time(), nullable=True))
    op.add_column('airfare_observations', sa.Column('dep_band', sa.String(length=20), nullable=True))
    op.add_column('airfare_observations', sa.Column('stops', sa.SmallInteger(), nullable=False, server_default='0'))
    op.add_column('airfare_observations', sa.Column('duration_min', sa.Integer(), nullable=True))
    op.add_column('airfare_observations', sa.Column('is_sold_out', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('airfare_observations', sa.Column('seats_left', sa.SmallInteger(), nullable=True))
    op.add_column('airfare_observations', sa.Column('is_synthetic', sa.Boolean(), nullable=False, server_default='true'))
    op.execute("UPDATE airfare_observations SET is_synthetic = true WHERE is_synthetic IS NULL")
    op.add_column('airfare_observations', sa.Column('target_lead_window', sa.SmallInteger(), nullable=True))
    op.add_column('airfare_observations', sa.Column('is_outlier', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('airfare_observations', sa.Column('is_imputed', sa.Boolean(), nullable=False, server_default='false'))

    # Dedup unique constraint
    op.create_unique_constraint(
        'uq_airfare_obs_dedup',
        'airfare_observations',
        ['source_id', 'flight_number', 'travel_date', 'fare_class', 'collection_date']
    )

    # Check constraints
    op.drop_constraint('ck_total_fare_non_negative', 'airfare_observations', type_='check')
    op.create_check_constraint('ck_total_fare_positive', 'airfare_observations', 'total_fare > 0')
    op.create_check_constraint('ck_base_fare_positive', 'airfare_observations', 'base_fare IS NULL OR base_fare > 0')
    op.create_check_constraint(
        'ck_dep_band_valid',
        'airfare_observations',
        "dep_band IS NULL OR dep_band IN ('early', 'morning', 'afternoon', 'evening', 'night')"
    )
    op.create_check_constraint(
        'ck_target_lead_window_valid',
        'airfare_observations',
        "target_lead_window IS NULL OR target_lead_window IN (1, 7, 15, 30, 45)"
    )

    # ─── 3. index_values ───────────────────────────────────────────
    op.add_column('index_values', sa.Column('frequency', sa.String(length=20), nullable=False, server_default='daily'))
    op.add_column('index_values', sa.Column('variant', sa.String(length=50), nullable=False, server_default='overall'))
    op.add_column('index_values', sa.Column('n_obs', sa.Integer(), nullable=True))
    op.execute("UPDATE index_values SET n_obs = observation_count WHERE n_obs IS NULL")
    op.add_column('index_values', sa.Column('coverage', sa.Numeric(precision=5, scale=4), nullable=True))

    op.drop_constraint('uq_index_date_version', 'index_values', type_='unique')
    op.create_unique_constraint(
        'uq_index_values_key',
        'index_values',
        ['index_date', 'frequency', 'variant', 'methodology_version']
    )

    # ─── 4. route_weights ──────────────────────────────────────────
    op.add_column('route_weights', sa.Column('valid_from', sa.Date(), nullable=True))
    op.execute("UPDATE route_weights SET valid_from = effective_date WHERE valid_from IS NULL")
    op.alter_column('route_weights', 'valid_from', nullable=False)
    op.add_column('route_weights', sa.Column('valid_to', sa.Date(), nullable=True))

    op.drop_constraint('uq_route_weight_date', 'route_weights', type_='unique')
    op.create_unique_constraint(
        'uq_route_weight_period',
        'route_weights',
        ['route_id', 'valid_from']
    )

    # ─── 5. lead_time_weights ──────────────────────────────────────
    op.create_table(
        'lead_time_weights',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('lead_days', sa.SmallInteger(), nullable=False),
        sa.Column('weight', sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lead_days', 'valid_from', name='uq_lead_time_weight_period'),
    )
    op.create_index('ix_lead_time_weights_lead_days', 'lead_time_weights', ['lead_days'])


def downgrade() -> None:
    # ─── 5. lead_time_weights ──────────────────────────────────────
    op.drop_table('lead_time_weights')

    # ─── 4. route_weights ──────────────────────────────────────────
    op.drop_constraint('uq_route_weight_period', 'route_weights', type_='unique')
    op.create_unique_constraint('uq_route_weight_date', 'route_weights', ['route_id', 'effective_date'])
    op.drop_column('route_weights', 'valid_to')
    op.drop_column('route_weights', 'valid_from')

    # ─── 3. index_values ───────────────────────────────────────────
    op.drop_constraint('uq_index_values_key', 'index_values', type_='unique')
    op.create_unique_constraint('uq_index_date_version', 'index_values', ['index_date', 'methodology_version'])
    op.drop_column('index_values', 'coverage')
    op.drop_column('index_values', 'n_obs')
    op.drop_column('index_values', 'variant')
    op.drop_column('index_values', 'frequency')

    # ─── 2. airfare_observations ───────────────────────────────────
    op.drop_constraint('ck_target_lead_window_valid', 'airfare_observations', type_='check')
    op.drop_constraint('ck_dep_band_valid', 'airfare_observations', type_='check')
    op.drop_constraint('ck_base_fare_positive', 'airfare_observations', type_='check')
    op.drop_constraint('ck_total_fare_positive', 'airfare_observations', type_='check')
    op.create_check_constraint('ck_total_fare_non_negative', 'airfare_observations', 'total_fare >= 0')

    op.drop_constraint('uq_airfare_obs_dedup', 'airfare_observations', type_='unique')
    op.drop_index('ix_airfare_observations_collection_date', 'airfare_observations')

    op.drop_column('airfare_observations', 'is_imputed')
    op.drop_column('airfare_observations', 'is_outlier')
    op.drop_column('airfare_observations', 'target_lead_window')
    op.drop_column('airfare_observations', 'is_synthetic')
    op.drop_column('airfare_observations', 'seats_left')
    op.drop_column('airfare_observations', 'is_sold_out')
    op.drop_column('airfare_observations', 'duration_min')
    op.drop_column('airfare_observations', 'stops')
    op.drop_column('airfare_observations', 'dep_band')
    op.drop_column('airfare_observations', 'dep_time')
    op.drop_column('airfare_observations', 'collection_date')

    op.add_column('airfare_observations', sa.Column('fees', sa.Numeric(precision=10, scale=2), nullable=True, server_default='0'))
    op.execute("UPDATE airfare_observations SET fees = COALESCE(other_fees, 0) + COALESCE(convenience_fee, 0) + COALESCE(udf_psf, 0)")
    op.drop_column('airfare_observations', 'other_fees')
    op.drop_column('airfare_observations', 'convenience_fee')
    op.drop_column('airfare_observations', 'udf_psf')

    # ─── 1. collection_runs ─────────────────────────────────────────
    op.alter_column('collection_runs', 'route_id', nullable=False)
    op.drop_column('collection_runs', 'captcha_count')
    op.drop_column('collection_runs', 'blocked_count')
    op.drop_column('collection_runs', 'status')
