import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { demoData } from "../data/demo";

function renderApp(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
}

describe("portfolio dashboard", () => {
  beforeEach(() => { demoData.system.stale = false; });

  it("renders the paper-trading shell, core and opportunistic picks, risk state, and parlay PASS", async () => {
    renderApp();
    expect(await screen.findByText("Portfolio decision desk")).toBeInTheDocument();
    expect(screen.getAllByText("POLARIS").length).toBeGreaterThan(0);
    expect(screen.getByText("Paper trading")).toBeInTheDocument();
    expect(screen.getAllByText("Core picks").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Opportunistic picks").length).toBeGreaterThan(0);
    expect(screen.getByText("No verified parlay quote")).toBeInTheDocument();
    expect(screen.getAllByText("NORMAL").length).toBeGreaterThan(0);
  });

  it("shows expandable lifecycle detail and requires server action completion", async () => {
    renderApp();
    const expand = await screen.findByLabelText("Expand Redwood State -3.5");
    fireEvent.click(expand);
    expect(screen.getByText("Recommended → Approved → Open → Settled")).toBeInTheDocument();
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

  it("provides the six primary destinations and nests methodology under settings", async () => {
    renderApp("/settings");
    expect(await screen.findByText("System / Methodology")).toBeInTheDocument();
    expect(screen.getAllByText("Market consensus supplies fair value").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Today" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Portfolio" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Bets" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Parlay" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "History" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Settings" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Models" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Research" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Market Movement" })).not.toBeInTheDocument();
  });

  it("runs a visible manual refresh workflow and disables duplicate clicks", async () => {
    renderApp();
    const refresh = await screen.findByRole("button", { name: "Refresh Markets" });
    fireEvent.click(refresh);
    await waitFor(() => expect(refresh).toBeDisabled());
    expect(await screen.findByText("Markets refreshed")).toBeInTheDocument();
  });
});
