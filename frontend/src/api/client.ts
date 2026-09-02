import type { DashboardData, MarketHistory, MarketMovement, MarketRefreshResult, Portfolio, PortfolioStats, Recommendation, RiskExposure, SystemStatus } from "../types";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(response.status, body?.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function loadDashboard(portfolioId: string, slateDate: string): Promise<DashboardData> {
  const encoded = encodeURIComponent(portfolioId);
  const [system, portfolio, stats, risk, recommendationResponse, movement] = await Promise.all([
    request<SystemStatus>("/dashboard/system"),
    request<Portfolio>(`/portfolio/${encoded}`),
    request<PortfolioStats>(`/portfolio/${encoded}/stats`),
    request<RiskExposure>(`/portfolio/${encoded}/risk?slate_date=${slateDate}`),
    request<{ recommendations: Recommendation[]; latest_decision: { as_of: string; pass_reasons: string[]; rejection_summary: Record<string, number> } | null }>(`/portfolio/${encoded}/recommendations?upcoming_only=true`),
    request<MarketMovement>(`/dashboard/market-movement?slate_date=${slateDate}`),
  ]);
  return {
    system,
    portfolio,
    stats,
    risk,
    recommendations: recommendationResponse.recommendations,
    movement,
    passReasons: recommendationResponse.latest_decision?.pass_reasons ?? [],
    rejectionSummary: recommendationResponse.latest_decision?.rejection_summary ?? {},
    decisionAsOf: recommendationResponse.latest_decision?.as_of ?? null,
  };
}

export async function refreshMarkets(portfolioId: string): Promise<MarketRefreshResult> {
  return request<MarketRefreshResult>(`/dashboard/portfolio/${encodeURIComponent(portfolioId)}/refresh-markets`, {
    method: "POST",
  });
}

export async function loadMarketHistory(
  eventId: string,
  market: string,
  side: string,
): Promise<MarketHistory> {
  const params = new URLSearchParams({ event_id: eventId, market_type: market, selection_side: side });
  return request<MarketHistory>(`/dashboard/market-history?${params.toString()}`);
}

export async function approveRecommendation(recommendationId: string): Promise<void> {
  await request(`/recommendations/${encodeURIComponent(recommendationId)}/approve`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

export async function rejectRecommendation(recommendationId: string): Promise<void> {
  await request(`/recommendations/${encodeURIComponent(recommendationId)}/reject`, { method: "POST" });
}
