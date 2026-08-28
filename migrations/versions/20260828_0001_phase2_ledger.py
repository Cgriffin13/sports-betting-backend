"""Phase 2 relational portfolio and bankroll ledger.

Revision ID: 20260828_0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="owner_status"),
        sa.PrimaryKeyConstraint("id", name="pk_owners"),
        sa.UniqueConstraint("external_id", name="uq_owners_external_id"),
    )
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("starting_capital", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("starting_capital >= 0", name="portfolio_starting_capital_nonnegative"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="portfolio_status"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], name="fk_portfolios_owner_id_owners", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_portfolios"),
        sa.UniqueConstraint("external_id", name="uq_portfolios_external_id"),
    )
    op.create_index("ix_portfolios_owner_id", "portfolios", ["owner_id"])
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("provider_event_id", sa.String(200)),
        sa.Column("league", sa.String(64), nullable=False),
        sa.Column("market_type", sa.String(64), nullable=False),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("selection", sa.String(300), nullable=False),
        sa.Column("point", sa.Numeric(10, 3)),
        sa.Column("sportsbook", sa.String(100), nullable=False),
        sa.Column("offered_american_odds", sa.Integer(), nullable=False),
        sa.Column("model_probability", sa.Numeric(12, 10)),
        sa.Column("consensus_probability", sa.Numeric(12, 10)),
        sa.Column("fair_probability", sa.Numeric(12, 10)),
        sa.Column("probability_edge", sa.Numeric(12, 10)),
        sa.Column("ev_per_unit", sa.Numeric(12, 10)),
        sa.Column("uncertainty_metadata", sa.JSON()),
        sa.Column("recommendation_version", sa.String(100)),
        sa.Column("model_version", sa.String(100)),
        sa.Column("policy_version", sa.String(100)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected', 'expired')",
            name="recommendation_status",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolios.id"], name="fk_recommendations_portfolio_id_portfolios", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendations"),
        sa.UniqueConstraint("external_id", name="uq_recommendations_external_id"),
    )
    op.create_index("ix_recommendations_portfolio_id", "recommendations", ["portfolio_id"])
    op.create_table(
        "bets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("provider_event_id", sa.String(200)),
        sa.Column("bet_date", sa.Date(), nullable=False),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("league", sa.String(64), nullable=False),
        sa.Column("event_name", sa.String(300)),
        sa.Column("home_team", sa.String(200)),
        sa.Column("away_team", sa.String(200)),
        sa.Column("scheduled_start", sa.DateTime(timezone=True)),
        sa.Column("market_type", sa.String(64), nullable=False),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("selection", sa.String(300), nullable=False),
        sa.Column("point", sa.Numeric(10, 3)),
        sa.Column("sportsbook", sa.String(100), nullable=False),
        sa.Column("entry_american_odds", sa.Integer(), nullable=False),
        sa.Column("stake", sa.Numeric(18, 2), nullable=False),
        sa.Column("model_probability", sa.Numeric(12, 10)),
        sa.Column("book_probability", sa.Numeric(12, 10)),
        sa.Column("consensus_probability", sa.Numeric(12, 10)),
        sa.Column("fair_probability", sa.Numeric(12, 10)),
        sa.Column("probability_edge", sa.Numeric(12, 10)),
        sa.Column("ev_per_unit", sa.Numeric(12, 10)),
        sa.Column("recommendation_version", sa.String(100)),
        sa.Column("model_version", sa.String(100)),
        sa.Column("policy_version", sa.String(100)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approval_source", sa.String(64)),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result", sa.String(16)),
        sa.Column("closing_american_odds", sa.Integer()),
        sa.Column("closing_probability", sa.Numeric(12, 10)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("realized_pnl", sa.Numeric(18, 2)),
        sa.CheckConstraint("stake > 0", name="bet_stake_positive"),
        sa.CheckConstraint("status IN ('open', 'settled', 'void')", name="bet_status"),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('win', 'loss', 'push', 'void')", name="bet_result"
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], name="fk_bets_portfolio_id_portfolios", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_bets"),
        sa.UniqueConstraint("external_id", name="uq_bets_external_id"),
    )
    op.create_index("ix_bets_portfolio_id", "bets", ["portfolio_id"])
    op.create_index("ix_bets_status", "bets", ["status"])
    op.create_table(
        "bet_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bet_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid()),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("metadata", sa.JSON()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bet_id"], ["bets.id"], name="fk_bet_approvals_bet_id_bets", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], name="fk_bet_approvals_owner_id_owners", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            name="fk_bet_approvals_recommendation_id_recommendations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bet_approvals"),
        sa.UniqueConstraint("bet_id", name="uq_bet_approvals_bet_id"),
    )
    op.create_index("ix_bet_approvals_owner_id", "bet_approvals", ["owner_id"])
    op.create_index("ix_bet_approvals_recommendation_id", "bet_approvals", ["recommendation_id"])
    op.create_table(
        "bet_state_transitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bet_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("metadata", sa.JSON()),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('open', 'settled', 'void')",
            name="from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('open', 'settled', 'void')",
            name="to_status",
        ),
        sa.ForeignKeyConstraint(
            ["bet_id"], ["bets.id"], name="fk_bet_state_transitions_bet_id_bets", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bet_state_transitions"),
    )
    op.create_index("ix_bet_state_transitions_bet_id", "bet_state_transitions", ["bet_id"])
    op.create_table(
        "settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bet_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("net_payout", sa.Numeric(18, 2), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("closing_american_odds", sa.Integer()),
        sa.Column("closing_probability", sa.Numeric(12, 10)),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("outcome IN ('win', 'loss', 'push', 'void')", name="settlement_outcome"),
        sa.ForeignKeyConstraint(["bet_id"], ["bets.id"], name="fk_settlements_bet_id_bets", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_settlements"),
        sa.UniqueConstraint("bet_id", name="uq_settlements_bet_id"),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("related_bet_id", sa.Uuid()),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(200)),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entry_type IN ('initial_funding', 'bet_stake', 'settlement', 'adjustment', 'refund_void')",
            name="ledger_entry_type",
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], name="fk_ledger_entries_portfolio_id_portfolios", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["related_bet_id"], ["bets.id"], name="fk_ledger_entries_related_bet_id_bets", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_entries"),
        sa.UniqueConstraint("portfolio_id", "reference", name="uq_ledger_portfolio_reference"),
    )
    op.create_index("ix_ledger_entries_portfolio_id", "ledger_entries", ["portfolio_id"])
    op.create_index("ix_ledger_entries_related_bet_id", "ledger_entries", ["related_bet_id"])
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.String(100), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], name="fk_idempotency_records_owner_id_owners", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint("owner_id", "endpoint", "key", name="uq_idempotency_owner_endpoint_key"),
    )
    op.create_index("ix_idempotency_records_owner_id", "idempotency_records", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_owner_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_ledger_entries_related_bet_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_portfolio_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_table("settlements")
    op.drop_index("ix_bet_state_transitions_bet_id", table_name="bet_state_transitions")
    op.drop_table("bet_state_transitions")
    op.drop_index("ix_bet_approvals_recommendation_id", table_name="bet_approvals")
    op.drop_index("ix_bet_approvals_owner_id", table_name="bet_approvals")
    op.drop_table("bet_approvals")
    op.drop_index("ix_bets_status", table_name="bets")
    op.drop_index("ix_bets_portfolio_id", table_name="bets")
    op.drop_table("bets")
    op.drop_index("ix_recommendations_portfolio_id", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_portfolios_owner_id", table_name="portfolios")
    op.drop_table("portfolios")
    op.drop_table("owners")
