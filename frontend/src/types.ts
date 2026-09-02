export type RiskState = "NORMAL" | "REDUCED_RISK" | "PAUSED";
export type RecommendationStatus = "proposed" | "approved" | "rejected" | "open" | "settled";

export interface Recommendation {
  recommendation_id: string;
  kind: "straight" | "parlay";
  status: RecommendationStatus;
  event_id: string | null;
  home_team: string | null;
  away_team: string | null;
  scheduled_start: string | null;
  market: string;
  side: string | null;
  selection: string | null;
  sportsbook: string | null;
  point: number | null;
  odds: number | null;
  fair_probability: number | null;
  implied_probability: number | null;
  push_probability: number | null;
  edge: number | null;
  ev_per_unit: number | null;
  confidence_quality: Record<string, unknown>;
  stake: number;
  bankroll_fraction: number | null;
  units: number | null;
  classification: "CORE" | "OPPORTUNISTIC" | null;
  risk_adjustments: string[];
  executable_alternatives: Array<Record<string, unknown>>;
  provenance: Record<string, unknown>;
  explanation: string | null;
  model_version: string;
  policy_version: string;
  recommendation_hash: string;
  slate_date?: string | null;
  decision_as_of?: string | null;
  timing_classification?: "EARLY_LOOKAHEAD" | "OFFICIAL_PRIMARY_HORIZON" | "POST_HORIZON";
  primary_horizon_at?: string;
  horizon_delta_seconds?: number;
  horizon_version?: string;
  legs: RecommendationLeg[];
}

export interface RecommendationLeg {
  event_id: string;
  market: string;
  side: string;
  selection: string;
  point: number | null;
  sportsbook: string;
  odds: number;
  fair_probability: number;
  implied_probability: number;
  edge: number;
  ev_per_unit: number;
  model_version: string;
  provenance: Record<string, unknown>;
}

export interface WatchlistItem {
  watchlist_id: string;
  event_id: string;
  slate_date: string;
  scheduled_start: string;
  home_team: string;
  away_team: string;
  market: string;
  side: string;
  selection: string;
  sportsbook: string;
  point: number | null;
  odds: number;
  fair_probability: number;
  implied_probability: number;
  edge: number;
  ev_per_unit: number;
  books_count: number;
  dispersion: number;
  freshness_age_seconds: number;
  fresh: boolean;
  timing_classification: "EARLY_LOOKAHEAD" | "OFFICIAL_PRIMARY_HORIZON" | "POST_HORIZON";
  primary_horizon_at: string;
  rejection_reasons: string[];
  primary_blocker: string;
  failed_gate_count: number;
  distance_to_qualification: number;
  ranking_score: number;
  source_observation_ids: string[];
  snapshot_ids: string[];
  best_executable_observation_id: string;
  watchlist_version: string;
  actionable: false;
}

export interface WatchlistState {
  as_of: string;
  upcoming_games_analyzed: number;
  qualified_recommendations: number;
  watchlist_count: number;
  watchlist_version: string;
  pricing_funnel: Record<string, number>;
  rejection_counts: Record<string, number>;
  pricing_pipeline_status: "HEALTHY" | "DEGRADED";
  pricing_pipeline_status_reason: string | null;
  slates: Array<{
    slate_date: string;
    weekday: string;
    as_of: string;
    games_analyzed: number;
    qualified_recommendations: number;
    watchlist_count: number;
    pricing_funnel: Record<string, number>;
    rejection_counts: Record<string, number>;
    pricing_pipeline_status: "HEALTHY" | "DEGRADED";
    pricing_pipeline_status_reason: string | null;
  }>;
  items: WatchlistItem[];
}

export interface Portfolio {
  portfolio_id: string;
  bankroll: number;
  cash: number;
  reserved_stake: number;
  open_exposure: number;
  equity: number;
  realized_pnl: number;
  currency: string;
  bets: Bet[];
}

export interface Bet {
  bet_id: string;
  date: string;
  sport: string;
  league: string;
  market_type: string;
  selection: string;
  book: string;
  odds: number;
  stake: number;
  status: "open" | "settled";
  result: "win" | "loss" | "push" | null;
  payout: number;
  created_at: string;
  home_team?: string | null;
  away_team?: string | null;
  model_version?: string | null;
  recommendation_version?: string | null;
  edge?: number | null;
  ev_per_1?: number | null;
  closing_odds?: number | null;
}

export interface PortfolioStats {
  portfolio_id: string;
  starting_bankroll: number;
  current_bankroll: number;
  cash: number;
  reserved_stake: number;
  open_exposure: number;
  equity: number;
  realized_pnl: number;
  net_pnl: number;
  overall: Record<string, number>;
  by_bucket: Array<Record<string, string | number>>;
  attribution: Record<string, Record<string, Record<string, number>>>;
  risk_metrics: Record<string, number>;
}

export interface RiskExposure {
  portfolio_id: string;
  slate_date: string;
  portfolio_state: RiskState;
  state_reason: string;
  cash: number;
  reserved_exposure: number;
  equity: number;
  peak_equity: number;
  drawdown_fraction: number;
  by_game: Record<string, number>;
  by_team: Record<string, number>;
  by_market: Record<string, number>;
  by_kind: Record<string, number>;
}

export interface ModelEntry {
  model_id: string;
  market_type: string;
  version: string;
  status: "retained_benchmark" | "shadow_candidate" | "diagnostic" | "rejected" | "retired";
  model_family: string;
  feature_set_hash: string | null;
  holdout_result: string | null;
  promotion_decision: string;
  consensus_version: string | null;
  vig_removal_version: string | null;
  registry_entry_hash: string;
  created_at: string;
}

export interface SystemStatus {
  paper_trading: true;
  league: "NCAAF";
  system_status: string;
  model_status: string;
  market_status: "FRESH" | "STALE" | "UNAVAILABLE" | "ERROR";
  market_status_reason: string;
  last_odds_refresh: string | null;
  last_market_attempt: string | null;
  last_market_attempt_status: string | null;
  last_provider_error: string | null;
  snapshot_age_seconds: number | null;
  stale: boolean;
  next_scheduled_refresh: string | null;
  supported_sportsbooks: string[];
  policies: Record<string, number | boolean>;
  models: ModelEntry[];
}

export interface MarketRefreshResult {
  status: "completed";
  snapshot_id: string;
  requested_at: string;
  provider: string;
  provider_metadata: Record<string, number | string>;
  from_cache: boolean;
  events_received: number;
  upcoming_events: number;
  observations_created: number;
  warnings: Array<Record<string, unknown>>;
  decisions: Array<{
    slate_date: string;
    first_kickoff: string;
    timing_classification: "EARLY_LOOKAHEAD" | "OFFICIAL_PRIMARY_HORIZON" | "POST_HORIZON";
    primary_horizon_at: string;
    horizon_delta_seconds: number;
    horizon_version: string;
    decision_run_id: string;
    qualified_straights: number;
    games_analyzed: number;
    watchlist_count: number;
    parlay_status: string;
    pass_reasons: string[];
  }>;
}

export interface MarketHistory {
  event_id: string;
  market: string;
  side: string;
  as_of: string;
  home_team: string | null;
  away_team: string | null;
  scheduled_start: string | null;
  points: MovementPoint[];
}

export interface MovementPoint {
  snapshot_id: string;
  requested_at: string;
  observed_at: string;
  sportsbook: string;
  market: string;
  side: string;
  point: number | null;
  american_odds: number;
  is_stale: boolean;
}

export interface MovementEvent {
  event_id: string;
  home_team: string;
  away_team: string;
  scheduled_start: string;
  opening_available: boolean;
  points: MovementPoint[];
}

export interface MarketMovement {
  slate_date: string;
  as_of: string;
  source_snapshot_count: number;
  events: MovementEvent[];
}

export interface DashboardData {
  system: SystemStatus;
  portfolio: Portfolio;
  stats: PortfolioStats;
  risk: RiskExposure;
  recommendations: Recommendation[];
  watchlist: WatchlistState;
  movement: MarketMovement;
  passReasons: string[];
  rejectionSummary: Record<string, number>;
  decisionAsOf: string | null;
}
