import { AlertTriangle, Banknote, CircleCheckBig, Clock3, RefreshCw, ScanSearch, Shield, TrendingUp, WalletCards } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ExposureBars, EquityChart } from "../components/Charts";
import { PicksTable } from "../components/PicksTable";
import { ErrorPage, LoadingPage, Metric, PageHeader, Panel, StatusBadge } from "../components/Primitives";
import { demoData } from "../data/demo";
import { useDashboard } from "../hooks/useDashboard";
import type { Recommendation } from "../types";
import { american, currency, formatAge, formatDateTime, percent, titleCase } from "../utils/format";

export function TodayPage() {
  const query = useDashboard();
  const [market, setMarket] = useState("all");
  const [book, setBook] = useState("all");
  const [status, setStatus] = useState("all");
  const data = query.data;
  const ids = useMemo(() => data?.recommendations.map((item) => item.recommendation_id) ?? [], [data]);
  const deltas = useScanDelta(ids);
  if (query.isLoading) return <LoadingPage />;
  if (query.isError || !data) return <ErrorPage message={query.error?.message || "The backend did not return dashboard data."} retry={() => void query.refetch()} />;
  const filtered = data.recommendations.filter((item) => (market === "all" || item.market === market) && (book === "all" || item.sportsbook === book) && (status === "all" || item.status === status));
  const core = filtered.filter((item) => item.classification === "CORE" && item.kind === "straight");
  const opportunistic = filtered.filter((item) => item.classification === "OPPORTUNISTIC" && item.kind === "straight");
  const parlay = data.recommendations.find((item) => item.kind === "parlay");
  const riskState = data.risk.portfolio_state;
  const dailyLimit = Number(data.system.policies.maximum_daily_fraction ?? 0.08);
  const dailyExposure = data.risk.equity ? data.risk.reserved_exposure / data.risk.equity : 0;
  const equitySeries = "equitySeries" in data ? (data as typeof demoData).equitySeries : [{ timestamp: new Date(Date.now() - 86_400_000).toISOString(), value: data.stats.starting_bankroll }, { timestamp: new Date().toISOString(), value: data.stats.equity }];
  return <div className="page-stack">
    <PageHeader eyebrow="NCAAF · Today" title="Portfolio decision desk" description="Qualified market-consensus opportunities, exposure controls, and approval-ready paper positions." actions={<button className="button secondary" onClick={() => void query.refetch()}><RefreshCw size={15} />Refresh backend</button>} />
    {data.system.stale && <div className="warning-banner"><AlertTriangle size={17} /><div><strong>Stored market data is stale</strong><span>Dashboard refreshes never call the odds provider. Run backend ingestion before approving positions.</span></div></div>}
    <div className="metric-grid five"><Metric label="Portfolio equity" value={currency(data.portfolio.equity)} detail={`${currency(data.portfolio.cash)} available cash`} icon={WalletCards} /><Metric label="Total exposure" value={currency(data.risk.reserved_exposure)} detail={`${percent(dailyExposure)} of equity`} icon={Shield} tone={dailyExposure > dailyLimit * 0.8 ? "warning" : "default"} /><Metric label="Open risk" value={currency(data.portfolio.open_exposure)} detail={`${data.portfolio.bets.filter((bet) => bet.status === "open").length} open positions`} icon={Banknote} /><Metric label="Today's P&L" value={currency(data.stats.net_pnl)} detail={`${percent(Number(data.stats.overall.roi ?? 0))} portfolio ROI`} icon={TrendingUp} tone={data.stats.net_pnl >= 0 ? "positive" : "negative"} /><Metric label="Slate" value={`${data.movement.events.length} games`} detail={`${data.recommendations.length} qualified · ${core.length} core`} icon={ScanSearch} /></div>
    <div className="slate-strip"><div><span className={`risk-pill risk-${riskState.toLowerCase().replace("_", "-")}`}>{riskState}</span><small>{titleCase(data.risk.state_reason)}</small></div><div className="slate-meta"><span><Clock3 size={14} />Last odds {data.system.last_odds_refresh ? formatAge(data.system.last_odds_refresh) : "unavailable"}</span><span>Next refresh {data.system.next_scheduled_refresh ? formatDateTime(data.system.next_scheduled_refresh) : "not scheduled"}</span><span className="positive-value">+{deltas.added} new</span><span>{deltas.removed} disappeared</span></div></div>
    <div className="filters" aria-label="Pick filters"><select aria-label="Market type" value={market} onChange={(event) => setMarket(event.target.value)}><option value="all">All markets</option><option value="moneyline">Moneyline</option><option value="spread">Spread</option><option value="total">Total</option></select><select aria-label="Sportsbook" value={book} onChange={(event) => setBook(event.target.value)}><option value="all">All sportsbooks</option>{[...new Set(data.recommendations.map((item) => item.sportsbook).filter(Boolean))].map((item) => <option key={item} value={item!}>{titleCase(item)}</option>)}</select><select aria-label="Status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All statuses</option><option value="proposed">Recommended</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></div>
    <Panel title="Core picks" eyebrow="Highest risk-adjusted quality" action={<StatusBadge tone="positive">{core.length} qualified</StatusBadge>}><PicksTable recommendations={core} label="CORE" /></Panel>
    <div className="dashboard-split">
      <Panel title="Parlay of the day" eyebrow="Separate risk sleeve"><ParlayCard recommendation={parlay} passReasons={data.passReasons} /></Panel>
      <Panel title="Risk exposure" eyebrow="Current / policy limit"><ExposureBars rows={[{ label: "Daily exposure", value: dailyExposure, limit: dailyLimit }, { label: "Largest game", value: maxFraction(data.risk.by_game, data.risk.equity), limit: Number(data.system.policies.maximum_game_fraction ?? 0.04) }, { label: "Largest team", value: maxFraction(data.risk.by_team, data.risk.equity), limit: Number(data.system.policies.maximum_team_fraction ?? 0.05) }, { label: "Largest market", value: maxFraction(data.risk.by_market, data.risk.equity), limit: Number(data.system.policies.maximum_market_fraction ?? 0.05) }]} /></Panel>
    </div>
    <Panel title="Opportunistic picks" eyebrow="Positive EV · smaller allocation" action={<StatusBadge tone="info">{opportunistic.length} qualified</StatusBadge>}><PicksTable recommendations={opportunistic} label="OPPORTUNISTIC" /></Panel>
    {!data.recommendations.length && <PassPanel data={data} />}
    <Panel title="Portfolio trend" eyebrow="Paper equity" action={<div className="range-tabs"><button className="active">7D</button><button>30D</button><button>YTD</button><button>All</button></div>}><div className="trend-summary"><strong>{currency(data.stats.equity)}</strong><span className={data.stats.net_pnl >= 0 ? "positive-value" : "negative-value"}>{currency(data.stats.net_pnl)} net P&amp;L</span></div><EquityChart data={equitySeries} recommendationAt={data.decisionAsOf} /></Panel>
  </div>;
}

function ParlayCard({ recommendation, passReasons }: { recommendation?: Recommendation; passReasons: string[] }) {
  if (!recommendation) return <div className="pass-card"><div className="pass-icon"><CircleCheckBig /></div><div><StatusBadge tone="neutral">PASS</StatusBadge><h3>No verified parlay quote</h3><p>{passReasons[0]?.replace("parlay_pass:", "").replaceAll("_", " ") || "No independently qualified 2–3 leg combination has a verified executable payout and defensible joint probability."}</p></div></div>;
  return <div className="parlay-qualified"><StatusBadge tone="positive">Qualified</StatusBadge><h3>{recommendation.legs.length}-leg cross-event parlay</h3><div className="parlay-leg-list">{recommendation.legs.map((leg) => <span key={`${leg.event_id}-${leg.selection}`}>{leg.selection} <strong>{american(leg.odds)}</strong></span>)}</div><dl><div><dt>Joint EV</dt><dd>{percent(recommendation.ev_per_unit)}</dd></div><div><dt>Stake</dt><dd>{currency(recommendation.stake)}</dd></div><div><dt>Incremental risk</dt><dd>{percent(recommendation.bankroll_fraction)}</dd></div></dl></div>;
}

function PassPanel({ data }: { data: NonNullable<ReturnType<typeof useDashboard>["data"]> }) {
  const reasons = data.passReasons.length ? data.passReasons : ["No candidate cleared every qualification and portfolio-risk gate."];
  return <Panel title="Why pass?" eyebrow="Intentional decision"><div className="pass-explanation"><CircleCheckBig /><div><h3>Capital preserved</h3><p>Zero recommendations is a valid portfolio outcome.</p><ul>{reasons.map((reason) => <li key={reason}>{titleCase(reason.replace("parlay_pass:", ""))}</li>)}{Object.entries(data.rejectionSummary).map(([reason, count]) => <li key={reason}>{count} · {titleCase(reason)}</li>)}</ul></div></div></Panel>;
}

function maxFraction(values: Record<string, number>, equity: number) { return equity ? Math.max(0, ...Object.values(values)) / equity : 0; }

function useScanDelta(ids: string[]) {
  const [result, setResult] = useState({ added: 0, removed: 0 });
  useEffect(() => {
    const key = "dino:last-recommendation-ids";
    const prior = JSON.parse(sessionStorage.getItem(key) || "[]") as string[];
    setResult({ added: ids.filter((id) => !prior.includes(id)).length, removed: prior.filter((id) => !ids.includes(id)).length });
    sessionStorage.setItem(key, JSON.stringify(ids));
  }, [ids]);
  return result;
}
