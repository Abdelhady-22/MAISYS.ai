"""DDIMDL initial schema.

Revision ID: 0001_ddimdl_initial
Revises:
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_ddimdl_initial"
down_revision = None
branch_labels = ("ddimdl",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ddimdl_severity_codes",
        sa.Column("code", sa.String(), primary_key=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
    )

    op.create_table(
        "ddimdl_drugs",
        sa.Column("drugbank_id", sa.String(), primary_key=True),
        sa.Column("drug_name", sa.String(), nullable=False),
        sa.Column("raw_features", sa.JSON(), nullable=True),
    )

    op.create_table(
        "ddimdl_interactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("drug_a", sa.String(), nullable=False, index=True),
        sa.Column("drug_b", sa.String(), nullable=False, index=True),
        sa.Column("interaction_text", sa.String(), nullable=True),
        sa.Column(
            "severity_code", sa.String(), sa.ForeignKey("ddimdl_severity_codes.code"), nullable=True
        ),
        sa.Column("source_file", sa.String(), nullable=False),
        sa.Column("source_sha256", sa.String(), nullable=False),
        sa.UniqueConstraint("drug_a", "drug_b", name="uq_ddimdl_pair"),
    )

    op.create_table(
        "ddimdl_ingestion_markers",
        sa.Column("source_file", sa.String(), primary_key=True),
        sa.Column("source_sha256", sa.String(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("ddimdl_ingestion_markers")
    op.drop_table("ddimdl_interactions")
    op.drop_table("ddimdl_drugs")
    op.drop_table("ddimdl_severity_codes")
