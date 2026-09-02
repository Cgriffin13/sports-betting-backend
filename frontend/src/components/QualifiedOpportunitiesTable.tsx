import type { QualifiedOpportunity } from "../types";
import { american, currency, line, percent, signedPercent, titleCase } from "../utils/format";
import { StatusBadge } from "./Primitives";

export function QualifiedOpportunitiesTable({ items }: { items: QualifiedOpportunity[] }) {
  if (!items.length) {
    return <div className="compact-empty">No pricing-qualified opportunities were blocked by portfolio controls.</div>;
  }
  return <div className="table-shell"><table className="qualified-opportunities-table"><thead><tr><th>Matchup / selection</th><th>Market</th><th>Book</th><th>Line</th><th>Odds</th><th>Fair</th><th>Implied</th><th>Edge</th><th>EV</th><th>Books</th><th>Dispersion</th><th>Calculated stake</th><th>Blocker</th></tr></thead><tbody>{items.map((item) => <tr key={item.qualified_opportunity_id}><td data-label="Selection"><strong>{item.selection}</strong><small>{item.away_team} @ {item.home_team}</small></td><td data-label="Market">{titleCase(item.market)}</td><td data-label="Book">{titleCase(item.sportsbook)}</td><td data-label="Line">{line(item.point)}</td><td data-label="Odds">{american(item.odds)}</td><td data-label="Fair">{percent(item.fair_probability)}</td><td data-label="Implied">{percent(item.implied_probability)}</td><td data-label="Edge"><span className="positive-value">{signedPercent(item.edge)}</span></td><td data-label="EV"><span className="positive-value">{signedPercent(item.ev_per_unit)}</span></td><td data-label="Books">{item.books_count}</td><td data-label="Dispersion">{percent(item.dispersion)}</td><td data-label="Calculated stake"><strong>{currency(item.calculated_stake)}</strong><small>Minimum {currency(item.minimum_operational_stake)} · not rounded up</small></td><td data-label="Blocker"><StatusBadge tone="warning">{titleCase(item.blocker)}</StatusBadge><small>Qualified · not actionable · not approvable</small></td></tr>)}</tbody></table></div>;
}
