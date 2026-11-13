"""Initial Migration

Revision ID: 001
Revises: 
Create Date: 2026-09-11 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'offers',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('company_name', sa.String(length=255), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index(op.f('ix_offers_id'), 'offers', ['id'], unique=False)

    op.create_table(
        'verification_results',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('offer_id', sa.Integer(), sa.ForeignKey('offers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('overall_risk_score', sa.Float(), nullable=False),
        sa.Column('completeness_percentage', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index(op.f('ix_verification_results_id'), 'verification_results', ['id'], unique=False)

    op.create_table(
        'check_results',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('verification_id', sa.Integer(), sa.ForeignKey('verification_results.id', ondelete='CASCADE'), nullable=False),
        sa.Column('check_name', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
    )
    op.create_index(op.f('ix_check_results_id'), 'check_results', ['id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_check_results_id'), table_name='check_results')
    op.drop_table('check_results')
    op.drop_index(op.f('ix_verification_results_id'), table_name='verification_results')
    op.drop_table('verification_results')
    op.drop_index(op.f('ix_offers_id'), table_name='offers')
    op.drop_table('offers')
