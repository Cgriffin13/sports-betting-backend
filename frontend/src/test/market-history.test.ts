import { describe, expect, it } from "vitest";
import { buildMarketHistorySeries } from "../utils/marketHistory";
import type { MovementPoint } from "../types";

const point = (timestamp: string, sportsbook: string, value: number): MovementPoint => ({
  snapshot_id: `${timestamp}-${sportsbook}`,
  requested_at: timestamp,
  observed_at: timestamp,
  sportsbook,
  market: "spread",
  side: "home",
  point: value,
  american_odds: -110,
  is_stale: false,
});

describe("stored market-history chart transformation", () => {
  it("builds deterministic per-book and median-consensus steps", () => {
    const series = buildMarketHistorySeries([
      point("2026-09-01T13:00:00Z", "fanduel", -3.5),
      point("2026-09-01T10:00:00Z", "draftkings", -3),
      point("2026-09-01T13:00:00Z", "draftkings", -4),
      point("2026-09-01T10:00:00Z", "fanduel", -3.5),
    ]);
    expect(series.map((row) => row.timestamp)).toEqual([
      "2026-09-01T10:00:00Z",
      "2026-09-01T13:00:00Z",
    ]);
    expect(series[0].consensus).toBe(-3.25);
    expect(series[1].draftkings).toBe(-4);
  });
});
