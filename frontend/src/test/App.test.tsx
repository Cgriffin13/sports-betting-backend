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
    const approve = screen.getByRole("button", { name: "Approve paper bet" });
    fireEvent.click(approve);
    await waitFor(() => expect(approve).toBeDisabled());
    await waitFor(() => expect(approve).not.toBeDisabled());
  });

  it("renders stale-market warning without triggering provider work", async () => {
    demoData.system.stale = true;
    renderApp();
    expect(await screen.findByText("Stored market data is stale")).toBeInTheDocument();
    expect(screen.getByText(/Run backend ingestion before approving/)).toBeInTheDocument();
  });

  it("provides all required routes and the mobile navigation destinations", async () => {
    renderApp("/models");
    expect(await screen.findByText("Fair-value authority")).toBeInTheDocument();
    expect(screen.getAllByText("Market consensus powers fair value").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Today" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Portfolio" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Bets" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Parlay" }).length).toBeGreaterThan(0);
  });
});
