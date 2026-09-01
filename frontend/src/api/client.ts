import type { DashboardData, MarketMovement, Portfolio, PortfolioStats, Recommendation, RiskExposure, SystemStatus } from "../types";

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
    request<{ recommendations: Recommendation[]; latest_decision: { as_of: string; pass_reasons: string[]; rejection_summary: Record<string, number> } | null }>(`/portfolio/${encoded}/recommendations?slate_date=${slateDate}`),
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

export async function approveRecommendation(recommendationId: string): Promise<void> {
  await request(`/recommendations/${encodeURIComponent(recommendationId)}/approve`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

export async function rejectRecommendation(recommendationId: string): Promise<void> {
  await request(`/recommendations/${encodeURIComponent(recommendationId)}/reject`, { method: "POST" });
}
