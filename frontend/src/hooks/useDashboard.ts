import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { approveRecommendation, loadDashboard, loadMarketHistory, refreshMarkets, rejectRecommendation } from "../api/client";
import { demoData } from "../data/demo";
import type { DashboardData } from "../types";

const portfolioId = import.meta.env.VITE_PORTFOLIO_ID || "paper-main";
const demoMode = import.meta.env.VITE_DEMO_MODE === "true" || import.meta.env.MODE === "test" || (import.meta.env.DEV && import.meta.env.VITE_DEMO_MODE !== "false");
const slateDate = new Date().toISOString().slice(0, 10);

export function useDashboard() {
  return useQuery<DashboardData>({
    queryKey: ["dashboard", portfolioId, slateDate, demoMode],
    queryFn: () => demoMode ? Promise.resolve(demoData) : loadDashboard(portfolioId, slateDate),
  });
}

export function useRecommendationAction() {
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: async ({ id, action }: { id: string; action: "approve" | "reject" }) => {
      if (demoMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 250));
        return;
      }
      return action === "approve" ? approveRecommendation(id) : rejectRecommendation(id);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["dashboard"] }),
  });
  return { ...mutation, demoMode };
}

export function useMarketRefresh() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (demoMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 350));
        return {
          status: "completed" as const,
          snapshot_id: "preview-snapshot",
          requested_at: new Date().toISOString(),
          provider: "preview",
          provider_metadata: {},
          from_cache: false,
          events_received: 3,
          upcoming_events: 3,
          observations_created: 54,
          warnings: [],
          decisions: [],
        };
      }
      return refreshMarkets(portfolioId);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["dashboard"] }),
  });
}

export function useMarketHistory(eventId: string | null, market: string, side: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["market-history", eventId, market, side],
    queryFn: () => loadMarketHistory(eventId!, market, side!),
    enabled: enabled && !demoMode && Boolean(eventId && side),
  });
}

export { demoMode, portfolioId, slateDate };
