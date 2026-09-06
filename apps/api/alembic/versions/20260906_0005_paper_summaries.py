"""Add per-paper briefing summaries for the reading desk.

Revision ID: 20260906_0005
Revises: 20260905_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0005"
down_revision: str | None = "20260905_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_summaries",
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column(
            "status",
            sa.Enum("READY", "FAILED", name="summarystatus", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("content", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_summaries_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_summaries")),
        sa.UniqueConstraint("paper_id", name=op.f("uq_paper_summaries_paper_id")),
    )
    op.create_index(
        "ix_summaries_owner_paper",
        "paper_summaries",
        ["owner_id", "paper_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_summaries_owner_paper", table_name="paper_summaries")
    op.drop_table("paper_summaries")
