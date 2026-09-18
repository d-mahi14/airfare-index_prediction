"""initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-18

Creates all tables for the APIx Milestone 1:
  - sources
  - routes
  - airlines
  - collection_runs
  - airfare_observations
  - index_values
  - route_weights
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- sources ---
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('base_url', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # --- routes ---
    op.create_table(
        'routes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('origin', sa.String(length=3), nullable=False),
        sa.Column('destination', sa.String(length=3), nullable=False),
        sa.Column('route_code', sa.String(length=8), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('route_code'),
        sa.UniqueConstraint('origin', 'destination', name='uq_route_origin_destination'),
    )

    # --- airlines ---
    op.create_table(
        'airlines',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('iata_code', sa.String(length=2), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # --- collection_runs ---
    op.create_table(
        'collection_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('route_id', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('records_found', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('records_saved', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('records_rejected', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['route_id'], ['routes.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_collection_runs_source_id', 'collection_runs', ['source_id'])
    op.create_index('ix_collection_runs_route_id', 'collection_runs', ['route_id'])

    # --- airfare_observations ---
    op.create_table(
        'airfare_observations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('collection_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('collection_timestamp', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('route_id', sa.Integer(), nullable=False),
        sa.Column('airline_id', sa.Integer(), nullable=True),
        sa.Column('flight_number', sa.String(length=20), nullable=True),
        sa.Column('travel_date', sa.Date(), nullable=False),
        sa.Column('lead_days', sa.SmallInteger(), nullable=False),
        sa.Column('fare_class', sa.String(length=50), nullable=False, server_default='Economy'),
        sa.Column('base_fare', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('taxes', sa.Numeric(precision=10, scale=2), nullable=True, server_default='0'),
        sa.Column('fees', sa.Numeric(precision=10, scale=2), nullable=True, server_default='0'),
        sa.Column('total_fare', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'),
        sa.Column('availability', sa.String(length=20), nullable=True, server_default='available'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='raw'),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('raw_reference', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.CheckConstraint('total_fare >= 0', name='ck_total_fare_non_negative'),
        sa.CheckConstraint('base_fare IS NULL OR base_fare <= total_fare',
                           name='ck_base_fare_lte_total'),
        sa.CheckConstraint('lead_days >= 0', name='ck_lead_days_non_negative'),
        sa.ForeignKeyConstraint(['collection_run_id'], ['collection_runs.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['route_id'], ['routes.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['airline_id'], ['airlines.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_airfare_observations_collection_timestamp',
                    'airfare_observations', ['collection_timestamp'])
    op.create_index('ix_airfare_observations_source_id', 'airfare_observations', ['source_id'])
    op.create_index('ix_airfare_observations_route_id', 'airfare_observations', ['route_id'])
    op.create_index('ix_airfare_observations_airline_id', 'airfare_observations', ['airline_id'])
    op.create_index('ix_airfare_observations_travel_date', 'airfare_observations', ['travel_date'])
    op.create_index('ix_airfare_observations_status', 'airfare_observations', ['status'])
    op.create_index('ix_airfare_observations_collection_run_id',
                    'airfare_observations', ['collection_run_id'])

    # --- index_values ---
    op.create_table(
        'index_values',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('index_date', sa.Date(), nullable=False),
        sa.Column('apix_value', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('methodology_version', sa.String(length=20), nullable=False,
                  server_default='v1.0'),
        sa.Column('observation_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('index_date', 'methodology_version',
                            name='uq_index_date_version'),
    )
    op.create_index('ix_index_values_index_date', 'index_values', ['index_date'])

    # --- route_weights ---
    op.create_table(
        'route_weights',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('route_id', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['route_id'], ['routes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('route_id', 'effective_date', name='uq_route_weight_date'),
    )
    op.create_index('ix_route_weights_route_id', 'route_weights', ['route_id'])


def downgrade() -> None:
    op.drop_table('route_weights')
    op.drop_table('index_values')
    op.drop_table('airfare_observations')
    op.drop_table('collection_runs')
    op.drop_table('airlines')
    op.drop_table('routes')
    op.drop_table('sources')
