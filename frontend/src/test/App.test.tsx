import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { demoData } from "../data/demo";

function renderApp(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
}

describe("portfolio dashboard", () => {
  beforeEach(() => {
    demoData.system.stale = false;
    demoData.watchlist.pricing_pipeline_status = "HEALTHY";
    demoData.watchlist.pricing_pipeline_status_reason = null;
  });

  it("renders the paper-trading shell, core and opportunistic picks, risk state, and parlay PASS", async () => {
    renderApp();
    expect(await screen.findByText("Portfolio decision desk")).toBeInTheDocument();
    expect(screen.getAllByText("POLARIS").length).toBeGreaterThan(0);
    expect(screen.getByText("Paper trading")).toBeInTheDocument();
    expect(screen.getAllByText("Core picks").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Opportunistic picks").length).toBeGreaterThan(0);
    expect(screen.getByText("98 games")).toBeInTheDocument();
    expect(screen.getByText(/4 qualified · 3 actionable · 7 watchlist/)).toBeInTheDocument();
    const qualifiedPanel = screen.getByText("Qualified opportunities").closest("section");
    expect(qualifiedPanel).not.toBeNull();
    expect(screen.getByText("Silver State -2.5")).toBeInTheDocument();
    expect(screen.getByText("$0.72")).toBeInTheDocument();
    expect(screen.getByText(/Minimum \$1.00 · not rounded up/)).toBeInTheDocument();
    expect(screen.getByText(/Qualified · not actionable · not approvable/)).toBeInTheDocument();
    expect(within(qualifiedPanel!).queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.getByText("On the radar")).toBeInTheDocument();
    expect(screen.queryByText("Harbor A&M @ Western Plains")).not.toBeInTheDocument();
    expect(screen.getByText("No verified parlay quote")).toBeInTheDocument();
    expect(screen.getAllByText("NORMAL").length).toBeGreaterThan(0);
  });

  it("shows expandable lifecycle detail and requires server action completion", async () => {
    renderApp();
    const expand = await screen.findByLabelText("Expand Redwood State -3.5");
    fireEvent.click(expand);
    expect(screen.getByText("Recommended → Approved → Open → Settled")).toBeInTheDocument();
    expect(screen.getByText("Full Kelly")).toBeInTheDocument();
    expect(screen.getByText("Robust log-growth score")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("Stored market history appears here when connected to the backend.")).toBeInTheDocument();
    const approve = screen.getByRole("button", { name: "Approve paper bet" });
    fireEvent.click(approve);
    await waitFor(() => expect(approve).toBeDisabled());
    await waitFor(() => expect(approve).not.toBeDisabled());
  });

  it("renders stale-market warning without triggering provider work", async () => {
    demoData.system.stale = true;
    renderApp();
    expect(await screen.findByText("Stored market data is stale")).toBeInTheDocument();
    expect(screen.getByText(/Use Refresh Markets before approving/)).toBeInTheDocument();
  });

  it("renders a pricing collapse as DEGRADED rather than a successful PASS", async () => {
    demoData.watchlist.pricing_pipeline_status = "DEGRADED";
    demoData.watchlist.pricing_pipeline_status_reason = "observations_present_but_none_eligible";
    renderApp();
    expect(await screen.findByText("Pricing pipeline degraded")).toBeInTheDocument();
    expect(screen.getByText(/not a successful PASS/)).toBeInTheDocument();
  });

  it("provides the seven primary destinations and nests methodology under settings", async () => {
    renderApp("/settings");
    expect(await screen.findByText("System / Methodology")).toBeInTheDocument();
    expect(screen.getAllByText("Market consensus supplies fair value").length).toBeGreaterThan(0);
    expect(screen.getByText("Latest Pricing Funnel")).toBeInTheDocument();
    expect(screen.getByText("calculable_candidate_sides")).toBeInTheDocument();
    expect(screen.getByText(/60 games.*eligible observations.*paired markets.*280 calculable sides.*34 positive EV.*7 watchlist.*4 qualified.*3 actionable/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Today" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Watchlist" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Portfolio" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Bets" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Parlay" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "History" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Settings" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Models" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Research" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Market Movement" })).not.toBeInTheDocument();
  });

  it("renders every eligible watchlist market as non-actionable research with stored history expansion", async () => {
    renderApp("/watchlist");
    expect(await screen.findByText("RESEARCH ONLY — NOT RECOMMENDATIONS")).toBeInTheDocument();
    expect(screen.getByText("Harbor A&M @ Western Plains")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve paper bet" })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByLabelText("Expand Home -3.5")[0]);
    expect(screen.getByText("Stored market history appears here when connected to the backend.")).toBeInTheDocument();
    expect(screen.getByText("Not actionable")).toBeInTheDocument();
  });

  it("keeps watchlist markets out of the parlay sleeve", async () => {
    renderApp("/parlay");
    expect(await screen.findByText(/7 watchlist markets are nearing straight-bet qualification/)).toBeInTheDocument();
    expect(screen.getByText(/They remain ineligible for parlays/)).toBeInTheDocument();
    expect(screen.getByText("No verified parlay qualifies")).toBeInTheDocument();
  });

  it("runs a visible manual refresh workflow and disables duplicate clicks", async () => {
    renderApp();
    const refresh = await screen.findByRole("button", { name: "Refresh Markets" });
    fireEvent.click(refresh);
    await waitFor(() => expect(refresh).toBeDisabled());
    expect(await screen.findByText("Markets refreshed")).toBeInTheDocument();
  });
});
