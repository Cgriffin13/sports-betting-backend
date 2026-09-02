import type { MovementPoint } from "../types";

export function buildMarketHistorySeries(
  points: MovementPoint[],
): Array<{ timestamp: string; consensus: number; [key: string]: string | number }> {
  const grouped = new Map<string, MovementPoint[]>();
  for (const point of points) {
    const key = point.requested_at;
    grouped.set(key, [...(grouped.get(key) ?? []), point]);
  }
  return [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([timestamp, rows]) => {
    const values = rows.map((row) => row.point ?? row.american_odds).sort((left, right) => left - right);
    const middle = Math.floor(values.length / 2);
    const consensus = values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
    return {
      timestamp,
      consensus,
      ...Object.fromEntries(rows.map((row) => [row.sportsbook, row.point ?? row.american_odds])),
    };
  });
}
