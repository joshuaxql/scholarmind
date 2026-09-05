"""store chunk embeddings for local database retrieval

Revision ID: 20260821_0002
Revises: 0f1f61f7b6d7
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0002"
down_revision: str | None = "0f1f61f7b6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("paper_chunks", sa.Column("embedding", sa.JSON(), nullable=True))
    op.add_column(
        "paper_chunks",
        sa.Column("embedding_model", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_chunks", "embedding_model")
    op.drop_column("paper_chunks", "embedding")
