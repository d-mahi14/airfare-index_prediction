"""create_route_watchlist

Revision ID: 004_create_route_watchlist
Revises: 003_create_clean_fares_view
Create Date: 2026-09-21

Creates the route_watchlist table for tracking uncovered route requests.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '004_create_route_watchlist'
down_revision = '003_create_clean_fares_view'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'route_watchlist',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('origin', sa.String(length=3), nullable=False),
        sa.Column('destination', sa.String(length=3), nullable=False),
        sa.Column('route_code', sa.String(length=8), nullable=False),
        sa.Column('client_hash', sa.String(length=64), nullable=False),
        sa.Column('request_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('first_requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('route_code', 'client_hash', name='uq_watchlist_route_client'),
    )
    op.create_index('ix_route_watchlist_route_code', 'route_watchlist', ['route_code'])
    op.create_index('ix_route_watchlist_client_hash', 'route_watchlist', ['client_hash'])


def downgrade() -> None:
    op.drop_index('ix_route_watchlist_client_hash', table_name='route_watchlist')
    op.drop_index('ix_route_watchlist_route_code', table_name='route_watchlist')
    op.drop_table('route_watchlist')
