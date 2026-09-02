"""Persist immutable decision-run watchlist research state.

Revision ID: 20260901_0005
Revises: 20260901_0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0005"
down_revision: str | None = "20260901_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("recommendation_decision_runs") as batch:
        batch.add_column(
            sa.Column("analysis_summary", JSON_DOCUMENT, nullable=False, server_default=sa.text("'{}'"))
        )
        batch.add_column(
            sa.Column("watchlist_items", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendation_decision_runs") as batch:
        batch.drop_column("watchlist_items")
        batch.drop_column("analysis_summary")
