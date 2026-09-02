import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { demoMode, useMarketHistory } from "../hooks/useDashboard";
import { american, formatDateTime, line as formatLine, titleCase } from "../utils/format";
import { buildMarketHistorySeries } from "../utils/marketHistory";

const colors = ["#48d597", "#61a9ff", "#e0ad50", "#ba8cff", "#ec6a6a"];

type MarketHistoryPanelProps = {
  eventId: string | null;
  market: string;
  side: string | null;
  bestSportsbook?: string | null;
  bestOdds?: number | null;
  bestPoint?: number | null;
};

export function MarketHistoryPanel({ eventId, market, side, bestSportsbook, bestOdds, bestPoint }: MarketHistoryPanelProps) {
  const query = useMarketHistory(eventId, market, side, Boolean(eventId && side));
  if (demoMode) return <div className="market-history-empty">Stored market history appears here when connected to the backend.</div>;
  if (query.isLoading) return <div className="market-history-empty">Loading stored market history…</div>;
  if (query.isError) return <div className="market-history-empty negative-value">Market history is unavailable: {query.error.message}</div>;
  const points = query.data?.points ?? [];
  if (!points.length) return <div className="market-history-empty">No stored price history exists for this exact event, market, and side.</div>;
  const series = buildMarketHistorySeries(points);
  const books = [...new Set(points.map((point) => point.sportsbook))].sort();
  const earliest = points[0];
  const latest = points[points.length - 1];
  return <div className="market-history-panel"><div className="market-history-head"><div><span className="eyebrow">Stored market movement</span><strong>{titleCase(market)} · {titleCase(side)}</strong></div><dl><div><dt>Earliest</dt><dd>{formatLine(earliest.point)} {american(earliest.american_odds)}</dd></div><div><dt>Current stored</dt><dd>{formatLine(latest.point)} {american(latest.american_odds)}</dd></div><div><dt>Best executable</dt><dd>{bestSportsbook ? `${titleCase(bestSportsbook)} · ${formatLine(bestPoint)} ${american(bestOdds)}` : "Unavailable"}</dd></div><div><dt>Books</dt><dd>{books.length}</dd></div><div><dt>Last observed</dt><dd>{formatDateTime(latest.observed_at)}</dd></div></dl></div><div className="market-history-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={series}><XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} stroke="#5f6b7b" fontSize={9} /><YAxis domain={["auto", "auto"]} stroke="#5f6b7b" fontSize={9} /><Tooltip labelFormatter={(value) => formatDateTime(String(value))} contentStyle={{ background: "#0d131b", border: "1px solid #222c38", fontSize: 10 }} /><Line type="stepAfter" dataKey="consensus" stroke="#edf1f5" strokeWidth={2} dot={false} />{books.map((book, index) => <Line key={book} type="stepAfter" dataKey={book} stroke={colors[index % colors.length]} strokeWidth={1.2} dot={false} connectNulls />)}</LineChart></ResponsiveContainer></div><small className="market-history-note">Uses stored snapshots only. The white series is stored median consensus; book series remain separate. For moneylines the chart axis is American odds; for spreads/totals it is the exact point.</small></div>;
}
