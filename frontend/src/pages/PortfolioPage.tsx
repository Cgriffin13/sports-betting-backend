import { Activity, Banknote, Landmark, Percent, TrendingDown, TrendingUp, WalletCards } from "lucide-react";
import { EquityChart, PerformanceBars } from "../components/Charts";
import { ErrorPage, LoadingPage, Metric, PageHeader, Panel } from "../components/Primitives";
import { demoData } from "../data/demo";
import { useDashboard } from "../hooks/useDashboard";
import { currency, percent, titleCase } from "../utils/format";

export function PortfolioPage() {
  const query = useDashboard();
  if (query.isLoading) return <LoadingPage />;
  if (query.isError || !query.data) return <ErrorPage message={query.error?.message || "Portfolio unavailable"} retry={() => void query.refetch()} />;
  const { stats, portfolio } = query.data;
  const series = "equitySeries" in query.data ? (query.data as typeof demoData).equitySeries : [{ timestamp: new Date(Date.now() - 86_400_000).toISOString(), value: stats.starting_bankroll }, { timestamp: new Date().toISOString(), value: stats.equity }];
  const overall = stats.overall;
  const performance = stats.by_bucket.map((row) => ({ name: titleCase(String(row.market_type)), pnl: Number(row.total_profit ?? 0) }));
  return <div className="page-stack"><PageHeader eyebrow="Portfolio" title="Equity and performance" description="Paper bankroll, realized outcomes, reserved risk, and attribution from the authoritative ledger." />
    <div className="metric-grid four"><Metric label="Equity" value={currency(stats.equity)} detail={`Started at ${currency(stats.starting_bankroll)}`} icon={WalletCards} /><Metric label="Available cash" value={currency(stats.cash)} detail={`${currency(stats.reserved_stake)} reserved`} icon={Landmark} /><Metric label="Net P&L" value={currency(stats.net_pnl)} detail={`${percent(Number(overall.roi ?? 0))} ROI`} icon={TrendingUp} tone={stats.net_pnl >= 0 ? "positive" : "negative"} /><Metric label="Max drawdown" value={percent(Number(stats.risk_metrics.max_drawdown ?? 0))} detail={`Peak ${currency(Number(stats.risk_metrics.peak_equity ?? stats.equity))}`} icon={TrendingDown} tone="warning" /></div>
    <div className="dashboard-wide-split"><Panel title="Equity curve" eyebrow="Immutable ledger"><div className="portfolio-chart-head"><div><strong>{currency(stats.equity)}</strong><small>Current equity</small></div><div className="range-tabs"><button>7D</button><button className="active">30D</button><button>YTD</button><button>All</button></div></div><EquityChart data={series} /></Panel><Panel title="Portfolio statistics" eyebrow="Settled paper bets"><div className="stat-grid"><Stat label="Turnover" value={`${Number(overall.turnover ?? 0).toFixed(2)}×`} icon={Activity} /><Stat label="Hit rate" value={percent(Number(overall.hit_rate ?? 0))} icon={Percent} /><Stat label="Settled" value={String(overall.bets_settled ?? 0)} icon={Banknote} /><Stat label="Open" value={String(portfolio.bets.filter((bet) => bet.status === "open").length)} icon={TrendingUp} /></div></Panel></div>
    <div className="dashboard-split"><Panel title="Performance by market" eyebrow="Realized P&L"><PerformanceBars data={performance} /></Panel><Panel title="Attribution" eyebrow="Decision class and structure"><Attribution groups={stats.attribution} /></Panel></div>
    <Panel title="Market breakdown" eyebrow="Ledger-derived"><div className="table-shell"><table><thead><tr><th>Market</th><th>Settled</th><th>Wins</th><th>Losses</th><th>Pushes</th><th>Staked</th><th>P&L</th><th>ROI</th></tr></thead><tbody>{stats.by_bucket.map((row) => <tr key={String(row.market_type)}><td>{titleCase(String(row.market_type))}</td><td>{row.bets_settled ?? 0}</td><td>{row.wins ?? 0}</td><td>{row.losses ?? 0}</td><td>{row.pushes ?? 0}</td><td>{currency(Number(row.total_staked ?? 0))}</td><td className={Number(row.total_profit ?? 0) >= 0 ? "positive-value" : "negative-value"}>{currency(Number(row.total_profit ?? 0))}</td><td>{percent(Number(row.roi ?? 0))}</td></tr>)}</tbody></table></div></Panel>
  </div>;
}

function Stat({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Activity }) { return <div className="stat-tile"><Icon size={16} /><span>{label}</span><strong>{value}</strong></div>; }
function Attribution({ groups }: { groups: Record<string, Record<string, Record<string, number>>> }) { return <div className="attribution-list">{Object.entries(groups).flatMap(([group, values]) => Object.entries(values).map(([name, metrics]) => <div key={`${group}-${name}`}><div><span>{titleCase(name)}</span><small>{titleCase(group)}</small></div><strong className={Number(metrics.pnl ?? 0) >= 0 ? "positive-value" : "negative-value"}>{currency(Number(metrics.pnl ?? 0))}</strong></div>))}</div>; }
