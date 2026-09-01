# Phase 6.5 NCAAF portfolio dashboard

Status: implemented as a paper-trading dashboard. It does not place real-money wagers.

## Architecture

The dashboard is a separate React 19 + TypeScript + Vite application under `frontend/`. It uses React Router for the page map, TanStack Query for server state/mutation revalidation, Recharts for restrained portfolio/market charts, and plain design-token CSS for the terminal-style responsive layout.

```text
Browser
  -> same-origin /api request
  -> Cloudflare Pages Function (BACKEND_API_KEY remains server-side)
  -> authenticated FastAPI endpoint on Render
  -> PostgreSQL / Phase 6 services
```

The browser never calls The Odds API. Current-market refreshes read stored backend state and therefore do not consume provider credits. Ingestion remains a scheduled or explicit backend operation.

The client does not calculate fair value, implied probability, edge, EV, Kelly size, qualification, exposure eligibility, correlation, or parlay joint probability. It renders values and decisions returned by FastAPI. Approval and rejection mutations are re-fetched after the server responds; approval-time portfolio risk is revalidated transactionally by the backend.

## Pages

- **Today**: equity/exposure/P&L/slate summary, scan deltas, CORE and OPPORTUNISTIC recommendations, PASS reasons, parlay state, exposure-to-limit bars, and portfolio trend.
- **Portfolio**: ledger balances, equity curve, drawdown/ROI/turnover/hit rate, market performance, and attribution.
- **Bets**: recommended, approved, open, settled, and rejected lifecycle views with explicit approve/reject actions.
- **Parlay**: qualified combined quote or an intentional PASS with the sleeve's correlation and risk requirements.
- **Market Movement**: stored book/line history, first/current observations, recommendation marker, timestamp freshness, and explicit “opening unavailable” state when the provider did not label an opener.
- **Models**: retained benchmark, diagnostic/rejected models, holdout and promotion decisions, and registry hashes.
- **Research**: report-driven Phase 5 evidence timeline, coverage, sources, and locked-holdout conclusion.
- **History**: settled paper positions and cumulative filtered results.
- **Settings**: read-only backend policy values. No local copy can silently override the active server policy.

Desktop uses a persistent left navigation. At widths below 820px, the required primary destinations move to a fixed bottom navigation and secondary destinations move to a More drawer. Pick tables collapse to decision cards while retaining approval access.

## Backend read contracts

Existing Phase 6 endpoints remain authoritative. Phase 6.5 adds only:

- `GET /dashboard/system`: safe policy values, retained/diagnostic/rejected registry entries, latest stored NCAAF snapshot time, and freshness/system status. It never returns credentials.
- `GET /dashboard/market-movement`: a date- and cutoff-bounded scalar projection of stored observations. It does not select snapshot raw JSON.
- `GET /portfolio/{id}/recommendations` now includes nullable `latest_decision` metadata (PASS reasons, rejection summary, policy versions, state, timestamp, and hash) while preserving the existing `recommendations` list.

All three remain authenticated with `X-API-Key` at the FastAPI boundary. The Pages Function supplies that credential server-side.

## Local development

Supported frontend runtime: Node.js 22+ and pnpm 11.x.

```bash
cd frontend
cp .env.example .env.local
pnpm install --frozen-lockfile
pnpm dev
```

Run FastAPI separately on `http://127.0.0.1:8000`. `DASHBOARD_BACKEND_URL` and `DASHBOARD_BACKEND_API_KEY` are consumed only by the Vite development proxy. They are deliberately not prefixed with `VITE_`, so Vite does not expose them to browser code.

Development defaults to clearly labeled preview data unless `VITE_DEMO_MODE=false`. Production builds must set it to `false`.

Validation:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

## Cloudflare Pages

Create a Pages project with:

- root directory: `frontend`
- build command: `pnpm install --frozen-lockfile && pnpm build`
- output directory: `dist`
- Node version: 22 or newer
- production build variable: `VITE_DEMO_MODE=false`
- optional build variable: `VITE_PORTFOLIO_ID=paper-main`
- Pages Function variable: `BACKEND_API_URL=https://<render-service>`
- encrypted Pages Function secret: `BACKEND_API_KEY=<APP_API_KEY value>`

Protect the Pages deployment with Cloudflare Access before treating it as a private operational dashboard. The Pages Function is an authentication bridge, not end-user identity. Never create `VITE_BACKEND_API_KEY`; every `VITE_*` value is embedded in the public static bundle.

The checked-in `_redirects` file provides SPA route fallback. The `/api/*` Pages Function remains the only browser-to-backend path. No automatic deployment is performed by this phase.

## Freshness and limitations

- “Last odds refresh” is the latest successful/partial stored NCAAF snapshot. “Next refresh” is unavailable until a backend scheduler publishes a schedule.
- New/disappeared opportunity counts compare the current response with the previous scan observed in that browser session; they are presentation-only and do not alter decisions.
- The current market archive does not mark a true opening price, so the UI displays “Opening unavailable” and separately labels the first stored observation.
- The backend does not yet expose a full time-series bankroll ledger or CLV series. The UI shows the available current/settled evidence and does not manufacture missing values in production.
- Profit factor and editable settings remain hidden/read-only unless the backend supplies authoritative values.
