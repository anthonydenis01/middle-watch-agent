"""Initial watchlist storage."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('watchlist', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('source', sa.String(10), nullable=False))
    op.create_index('ix_watchlist_expires_at', 'watchlist', ['expires_at'])
    op.create_table('container', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('watchlist_id', sa.String(36), sa.ForeignKey('watchlist.id', ondelete='CASCADE'), nullable=False),
        sa.Column('number', sa.String(40), nullable=False), sa.Column('valid', sa.Boolean(), nullable=False),
        sa.Column('invalid_reason', sa.String(250)), sa.Column('carrier_label', sa.String(20), nullable=False),
        sa.Column('status', sa.String(40), nullable=False), sa.Column('eta', sa.String(30)),
        sa.Column('next_milestone', sa.String(100)), sa.Column('journey', sa.JSON(), nullable=False))
    op.create_index('ix_container_watchlist_id', 'container', ['watchlist_id'])
    op.create_table('event', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('container_id', sa.String(36), sa.ForeignKey('container.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ts', sa.String(30), nullable=False), sa.Column('code', sa.String(40), nullable=False),
        sa.Column('location_unlocode', sa.String(5), nullable=False), sa.Column('vessel', sa.String(100), nullable=False),
        sa.Column('voyage', sa.String(30), nullable=False), sa.Column('raw', sa.JSON(), nullable=False))
    op.create_index('ix_event_container_id', 'event', ['container_id'])
    op.create_table('exception', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('container_id', sa.String(36), sa.ForeignKey('container.id', ondelete='CASCADE'), nullable=False),
        sa.Column('family', sa.String(30), nullable=False), sa.Column('severity', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(300), nullable=False), sa.Column('evidence_json', sa.JSON(), nullable=False),
        sa.Column('rule_id', sa.String(100), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_exception_container_id', 'exception', ['container_id'])


def downgrade():
    for name in ('exception', 'event', 'container', 'watchlist'):
        op.drop_table(name)
