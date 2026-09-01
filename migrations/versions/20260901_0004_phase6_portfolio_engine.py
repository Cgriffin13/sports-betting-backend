"""Phase 6 recommendation, risk, and parlay decision records.

Revision ID: 20260901_0004
Revises: 20260831_0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0004"
down_revision: str | None = "20260831_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "recommendation_decision_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("league", sa.String(32), nullable=False),
        sa.Column("slate_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("portfolio_state", sa.String(32), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=False),
        sa.Column("starting_bankroll", sa.Numeric(18, 2), nullable=False),
        sa.Column("cash", sa.Numeric(18, 2), nullable=False),
        sa.Column("reserved_exposure", sa.Numeric(18, 2), nullable=False),
        sa.Column("equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("peak_equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("drawdown_fraction", sa.Numeric(16, 12), nullable=False),
        sa.Column("qualification_policy_version", sa.String(100), nullable=False),
        sa.Column("risk_policy_version", sa.String(100), nullable=False),
        sa.Column("parlay_policy_version", sa.String(100), nullable=False),
        sa.Column("pass_reasons", JSON_DOCUMENT, nullable=False),
        sa.Column("rejection_summary", JSON_DOCUMENT, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("league = 'NCAAF'", name="decision_run_ncaaf"),
        sa.CheckConstraint("status IN ('completed', 'failed')", name="decision_run_status"),
        sa.CheckConstraint("portfolio_state IN ('NORMAL', 'REDUCED_RISK', 'PAUSED')", name="decision_run_state"),
        sa.CheckConstraint("top_n >= 1 AND top_n <= 10", name="decision_run_top_n"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
        sa.UniqueConstraint("output_hash"),
    )
    op.create_index("ix_recommendation_decision_runs_portfolio_id", "recommendation_decision_runs", ["portfolio_id"])

    with op.batch_alter_table("recommendations") as batch:
        batch.add_column(sa.Column("decision_run_id", sa.Uuid()))
        batch.add_column(sa.Column("canonical_event_id", sa.Uuid()))
        batch.add_column(sa.Column("recommendation_kind", sa.String(32), nullable=False, server_default="straight"))
        batch.add_column(sa.Column("selection_side", sa.String(32)))
        batch.add_column(sa.Column("home_team", sa.String(200)))
        batch.add_column(sa.Column("away_team", sa.String(200)))
        batch.add_column(sa.Column("scheduled_start", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("best_executable_observation_id", sa.Uuid()))
        batch.add_column(sa.Column("implied_probability", sa.Numeric(12, 10)))
        batch.add_column(sa.Column("push_probability", sa.Numeric(12, 10)))
        batch.add_column(sa.Column("executable_alternatives", JSON_DOCUMENT))
        batch.add_column(sa.Column("risk_adjustments", JSON_DOCUMENT))
        batch.add_column(sa.Column("provenance", JSON_DOCUMENT))
        batch.add_column(sa.Column("classification", sa.String(32)))
        batch.add_column(sa.Column("recommended_stake", sa.Numeric(18, 2)))
        batch.add_column(sa.Column("bankroll_fraction", sa.Numeric(16, 12)))
        batch.add_column(sa.Column("units", sa.Numeric(16, 8)))
        batch.add_column(sa.Column("raw_kelly_fraction", sa.Numeric(16, 12)))
        batch.add_column(sa.Column("adjusted_kelly_fraction", sa.Numeric(16, 12)))
        batch.add_column(sa.Column("recommendation_hash", sa.String(64)))
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("rejected_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key("fk_recommendations_decision_run_id_recommendation_decision_runs", "recommendation_decision_runs", ["decision_run_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_recommendations_canonical_event_id_canonical_events", "canonical_events", ["canonical_event_id"], ["id"], ondelete="RESTRICT")
        batch.create_check_constraint("recommendation_kind", "recommendation_kind IN ('straight', 'parlay')")
        batch.create_check_constraint("recommendation_classification", "classification IS NULL OR classification IN ('CORE', 'OPPORTUNISTIC')")
        batch.create_unique_constraint("uq_recommendations_recommendation_hash", ["recommendation_hash"])
        batch.create_index("ix_recommendations_decision_run_id", ["decision_run_id"])
        batch.create_index("ix_recommendations_canonical_event_id", ["canonical_event_id"])

    op.create_table(
        "recommendation_legs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("leg_index", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("canonical_event_id", sa.Uuid(), nullable=False),
        sa.Column("market_type", sa.String(32), nullable=False),
        sa.Column("selection_side", sa.String(32), nullable=False),
        sa.Column("selection", sa.String(300), nullable=False),
        sa.Column("point", sa.Numeric(10, 3)),
        sa.Column("sportsbook", sa.String(100), nullable=False),
        sa.Column("american_odds", sa.Integer(), nullable=False),
        sa.Column("fair_probability", sa.Numeric(12, 10), nullable=False),
        sa.Column("implied_probability", sa.Numeric(12, 10), nullable=False),
        sa.Column("probability_edge", sa.Numeric(12, 10), nullable=False),
        sa.Column("ev_per_unit", sa.Numeric(16, 12), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("leg_index >= 0 AND leg_index < 3", name="recommendation_leg_index"),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_id", "leg_index", name="uq_recommendation_leg_index"),
    )
    op.create_index("ix_recommendation_legs_recommendation_id", "recommendation_legs", ["recommendation_id"])
    op.create_index("ix_recommendation_legs_canonical_event_id", "recommendation_legs", ["canonical_event_id"])

    with op.batch_alter_table("bets") as batch:
        batch.add_column(sa.Column("bet_kind", sa.String(32), nullable=False, server_default="straight"))
        batch.add_column(sa.Column("classification", sa.String(32)))
        batch.add_column(sa.Column("recommendation_hash", sa.String(64)))
        batch.add_column(sa.Column("decision_metadata", JSON_DOCUMENT))
        batch.add_column(sa.Column("canonical_event_id", sa.Uuid()))
        batch.add_column(sa.Column("selection_side", sa.String(32)))
        batch.create_foreign_key("fk_bets_canonical_event_id_canonical_events", "canonical_events", ["canonical_event_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_bets_canonical_event_id", ["canonical_event_id"])
        batch.create_check_constraint("bet_kind", "bet_kind IN ('straight', 'parlay')")
        batch.create_check_constraint("bet_classification", "classification IS NULL OR classification IN ('CORE', 'OPPORTUNISTIC')")


def downgrade() -> None:
    with op.batch_alter_table("bets") as batch:
        batch.drop_index("ix_bets_canonical_event_id")
        batch.drop_constraint("fk_bets_canonical_event_id_canonical_events", type_="foreignkey")
        batch.drop_constraint(op.f("ck_bets_bet_classification"), type_="check")
        batch.drop_constraint(op.f("ck_bets_bet_kind"), type_="check")
        batch.drop_column("decision_metadata")
        batch.drop_column("selection_side")
        batch.drop_column("canonical_event_id")
        batch.drop_column("recommendation_hash")
        batch.drop_column("classification")
        batch.drop_column("bet_kind")
    op.drop_index("ix_recommendation_legs_canonical_event_id", table_name="recommendation_legs")
    op.drop_index("ix_recommendation_legs_recommendation_id", table_name="recommendation_legs")
    op.drop_table("recommendation_legs")
    with op.batch_alter_table("recommendations") as batch:
        batch.drop_index("ix_recommendations_canonical_event_id")
        batch.drop_index("ix_recommendations_decision_run_id")
        batch.drop_constraint("uq_recommendations_recommendation_hash", type_="unique")
        batch.drop_constraint(op.f("ck_recommendations_recommendation_classification"), type_="check")
        batch.drop_constraint(op.f("ck_recommendations_recommendation_kind"), type_="check")
        batch.drop_constraint("fk_recommendations_canonical_event_id_canonical_events", type_="foreignkey")
        batch.drop_constraint("fk_recommendations_decision_run_id_recommendation_decision_runs", type_="foreignkey")
        for name in (
            "rejected_at", "approved_at", "recommendation_hash", "adjusted_kelly_fraction",
            "raw_kelly_fraction", "units", "bankroll_fraction", "recommended_stake", "classification",
            "provenance", "risk_adjustments", "executable_alternatives", "push_probability",
            "implied_probability", "best_executable_observation_id", "scheduled_start", "away_team",
            "home_team", "selection_side",
            "recommendation_kind", "canonical_event_id", "decision_run_id",
        ):
            batch.drop_column(name)
    op.drop_index("ix_recommendation_decision_runs_portfolio_id", table_name="recommendation_decision_runs")
    op.drop_table("recommendation_decision_runs")
