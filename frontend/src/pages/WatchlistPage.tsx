import { Binoculars } from "lucide-react";
import { useMemo, useState } from "react";
import { WatchlistTable } from "../components/WatchlistTable";
import { ErrorPage, LoadingPage, PageHeader, Panel, StatusBadge } from "../components/Primitives";
import { useDashboard } from "../hooks/useDashboard";

export function WatchlistPage() {
  const query = useDashboard();
  const [slate, setSlate] = useState("all");
  const [market, setMarket] = useState("all");
  const dates = useMemo(() => [...new Set(query.data?.watchlist.items.map((item) => item.slate_date) ?? [])], [query.data]);
  if (query.isLoading) return <LoadingPage />;
  if (query.isError || !query.data) return <ErrorPage message={query.error?.message || "Watchlist unavailable"} retry={() => void query.refetch()} />;
  const { watchlist } = query.data;
  const items = watchlist.items.filter((item) => (slate === "all" || item.slate_date === slate) && (market === "all" || item.market === market));
  return <div className="page-stack">
    <PageHeader eyebrow="Research only · not recommendations" title="Watchlist" description="Ranked positive-edge market candidates that survived baseline pricing but have not cleared every production qualification gate." actions={<StatusBadge tone="warning">{watchlist.watchlist_count} near qualification</StatusBadge>} />
    <div className="research-only-banner"><Binoculars /><div><strong>RESEARCH ONLY — NOT RECOMMENDATIONS</strong><span>No stakes, approvals, ledger entries, or parlay eligibility are created from this page.</span></div></div>
    <div className="slate-strip"><strong>{watchlist.upcoming_games_analyzed} upcoming games analyzed</strong><div className="slate-meta"><span>{watchlist.qualified_recommendations} qualified</span><span>{watchlist.actionable_recommendations} actionable</span><span>{watchlist.watchlist_count} watchlist markets</span><span>{watchlist.watchlist_version}</span></div></div>
    <div className="filters" aria-label="Watchlist filters"><select aria-label="Upcoming slate" value={slate} onChange={(event) => setSlate(event.target.value)}><option value="all">All upcoming slates</option>{dates.map((date) => <option key={date} value={date}>{date}</option>)}</select><select aria-label="Watchlist market" value={market} onChange={(event) => setMarket(event.target.value)}><option value="all">All markets</option><option value="moneyline">Moneyline</option><option value="spread">Spread</option><option value="total">Total</option></select></div>
    <Panel title="Near-qualification research" eyebrow="Deterministic gate-distance ranking" action={<StatusBadge tone="neutral">{items.length} shown</StatusBadge>}><WatchlistTable items={items} /></Panel>
  </div>;
}
