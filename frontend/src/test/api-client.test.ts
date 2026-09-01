import { beforeEach, describe, expect, it, vi } from "vitest";
import { approveRecommendation, loadDashboard, rejectRecommendation } from "../api/client";
import { demoData } from "../data/demo";

const jsonResponse = (value: unknown) => Promise.resolve(new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } }));

describe("typed API client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/dashboard/system")) return jsonResponse(demoData.system);
      if (url.includes("/stats")) return jsonResponse(demoData.stats);
      if (url.includes("/risk")) return jsonResponse(demoData.risk);
      if (url.includes("/recommendations")) return jsonResponse({ recommendations: demoData.recommendations, latest_decision: { as_of: demoData.decisionAsOf, pass_reasons: demoData.passReasons, rejection_summary: demoData.rejectionSummary } });
      if (url.includes("/market-movement")) return jsonResponse(demoData.movement);
      if (url.includes("/portfolio/")) return jsonResponse(demoData.portfolio);
      return jsonResponse({});
    }));
  });

  it("loads the Phase 6.5 contract from same-origin backend routes", async () => {
    const data = await loadDashboard("paper-main", "2026-09-01");
    expect(data.portfolio.portfolio_id).toBe("paper-main");
    expect(data.system.models[0].status).toBe("retained_benchmark");
    expect(data.recommendations).toHaveLength(3);
    expect(fetch).toHaveBeenCalledTimes(6);
    for (const call of vi.mocked(fetch).mock.calls) expect(String(call[0])).toMatch(/^\/api\//);
  });

  it("sends approval idempotency and rejection only to backend APIs", async () => {
    await approveRecommendation("rec-101");
    await rejectRecommendation("rec-102");
    const approve = vi.mocked(fetch).mock.calls[0];
    expect(approve[0]).toBe("/api/recommendations/rec-101/approve");
    expect((approve[1]?.headers as Record<string, string>)["Idempotency-Key"]).toBe("test-idempotency-key");
    expect(approve[1]?.method).toBe("POST");
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe("/api/recommendations/rec-102/reject");
  });
});
