"""drug-service initial schema.

Revision ID: 0001_drug_initial
Revises:
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_drug_initial"
down_revision = None
branch_labels = ("drug_service",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rxnorm_cache",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("input_name_normalised", sa.String(256), nullable=False),
        sa.Column("input_name_original", sa.String(256), nullable=False),
        sa.Column("rxcui", sa.String(32), nullable=False),
        sa.Column("generic_name", sa.String(256), nullable=False),
        sa.Column("brand_names", sa.JSON(), nullable=False),
        sa.Column("drug_class", sa.String(128), nullable=True),
        sa.Column("resolution_path", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("input_name_normalised", name="uq_rxnorm_input"),
    )
    op.create_index("ix_rxnorm_rxcui", "rxnorm_cache", ["rxcui"])

    op.create_table(
        "drug_query_log",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("request_summary", sa.JSON(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_drug_query_user_created", "drug_query_log", ["user_id", "created_at"])
    op.create_index("ix_drug_query_correlation", "drug_query_log", ["correlation_id"])

    op.create_table(
        "rxnorm_sync_marker",
        sa.Column("source_file", sa.String(512), primary_key=True),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("rows_loaded", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("rxnorm_sync_marker")
    op.drop_index("ix_drug_query_correlation", table_name="drug_query_log")
    op.drop_index("ix_drug_query_user_created", table_name="drug_query_log")
    op.drop_table("drug_query_log")
    op.drop_index("ix_rxnorm_rxcui", table_name="rxnorm_cache")
    op.drop_table("rxnorm_cache")
