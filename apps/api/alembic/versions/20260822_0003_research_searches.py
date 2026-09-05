"""store arXiv topic searches and research reports

Revision ID: 20260822_0003
Revises: 20260821_0002
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0003"
down_revision: str | None = "20260821_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_searches",
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("query_expression", sa.Text(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "SEARCHED",
                "ANALYZING",
                "COMPLETE",
                "FAILED",
                name="researchstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_searches")),
    )
    op.create_index(
        op.f("ix_research_searches_owner_id"),
        "research_searches",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_research_searches_status"),
        "research_searches",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_research_owner_created",
        "research_searches",
        ["owner_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_research_owner_request",
        "research_searches",
        ["owner_id", "request_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_owner_request", table_name="research_searches")
    op.drop_index("ix_research_owner_created", table_name="research_searches")
    op.drop_index(op.f("ix_research_searches_status"), table_name="research_searches")
    op.drop_index(op.f("ix_research_searches_owner_id"), table_name="research_searches")
    op.drop_table("research_searches")
