import { ChevronDown, ChevronUp, Clock3 } from "lucide-react";
import { useState } from "react";
import type { WatchlistItem } from "../types";
import { american, formatDateTime, line, percent, titleCase } from "../utils/format";
import { MarketHistoryPanel } from "./MarketHistoryPanel";
import { StatusBadge } from "./Primitives";

export function WatchlistTable({ items, limit }: { items: WatchlistItem[]; limit?: number }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const visible = limit ? items.slice(0, limit) : items;
  if (!visible.length) return <div className="compact-empty">No current markets are near qualification.</div>;
  return <div className="table-shell"><table className="watchlist-table"><thead><tr><th>Rank</th><th>Matchup / selection</th><th>Market</th><th>Price</th><th>Fair / implied</th><th>Edge</th><th>EV</th><th>Books</th><th>Dispersion</th><th>Timing</th><th>Primary blocker</th><th><span className="sr-only">Details</span></th></tr></thead><tbody>{visible.map((item, index) => <WatchlistRows key={item.watchlist_id} item={item} rank={index + 1} expanded={expanded === item.watchlist_id} toggle={() => setExpanded(expanded === item.watchlist_id ? null : item.watchlist_id)} />)}</tbody></table></div>;
}

function WatchlistRows({ item, rank, expanded, toggle }: { item: WatchlistItem; rank: number; expanded: boolean; toggle: () => void }) {
  return <>
    <tr><td><span className="watch-rank">{rank}</span></td><td><strong>{item.away_team} @ {item.home_team}</strong><small>{item.selection} · {formatDateTime(item.scheduled_start)}</small></td><td>{titleCase(item.market)}<small>{item.side}</small></td><td>{titleCase(item.sportsbook)}<small>{line(item.point)} · {american(item.odds)}</small></td><td>{percent(item.fair_probability)}<small>{percent(item.implied_probability)} implied</small></td><td>{percent(item.edge)}</td><td>{percent(item.ev_per_unit)}</td><td>{item.books_count}</td><td>{percent(item.dispersion)}</td><td><StatusBadge tone={item.timing_classification === "OFFICIAL_PRIMARY_HORIZON" ? "positive" : "warning"}>{titleCase(item.timing_classification)}</StatusBadge></td><td><span className="blocker">{titleCase(item.primary_blocker)}</span></td><td><button className="icon-button" aria-label={`${expanded ? "Collapse" : "Expand"} ${item.selection}`} onClick={toggle}>{expanded ? <ChevronUp /> : <ChevronDown />}</button></td></tr>
    {expanded && <tr className="detail-row"><td colSpan={12}><div className="watchlist-detail"><div><span className="eyebrow">Research-only gate analysis</span><p>This market remains non-actionable and carries no stake. It failed {item.failed_gate_count} production gate{item.failed_gate_count === 1 ? "" : "s"}.</p><div className="tag-row">{item.rejection_reasons.map((reason) => <span className="data-tag" key={reason}>{titleCase(reason)}</span>)}</div></div><dl><div><dt>Distance score</dt><dd>{item.distance_to_qualification.toFixed(3)}</dd></div><div><dt>Freshness</dt><dd><Clock3 size={13} /> {item.freshness_age_seconds}s</dd></div><div><dt>Primary horizon</dt><dd>{formatDateTime(item.primary_horizon_at)}</dd></div><div><dt>Research status</dt><dd>Not actionable</dd></div></dl></div><MarketHistoryPanel eventId={item.event_id} market={item.market} side={item.side} bestSportsbook={item.sportsbook} bestOdds={item.odds} bestPoint={item.point} /></td></tr>}
  </>;
}
