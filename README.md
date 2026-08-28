# Sports Betting Portfolio Backend

Experimental backend for a quantitative sports-wagering portfolio manager. The current service retrieves sportsbook odds, records explicitly approved paper bets, tracks a test bankroll, settles results, and reports basic performance statistics.

This is a paper-trading research system. It does not place real-money wagers, calculate fair probability or EV, recommend stakes, or run proprietary predictive models yet. NCAAF/College Football is the immediate league priority, followed by NFL and NBA.

## Supported Python

Python **3.12.x** is the supported development and CI runtime. The `.python-version` file allows compatible version managers to select it automatically.

## Local setup

```bash
python -m venv .venv
```

Activate the environment:

```text
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Install the pinned runtime and development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` and replace placeholder values as needed. `.env` is ignored by Git.

## Environment variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `ODDS_API_KEY` | Required for `/odds` | None | The Odds API credential. |
| `STARTING_BANKROLL` | No | `200.0` | Paper bankroll assigned to a newly created portfolio. |
| `DATA_DIR` | No | `data` | Directory containing the prototype JSON database. On Render, use a persistent disk such as `/var/data`. |

Never commit real credentials. `.env.example` contains placeholders only.

## Run the API

```bash
python -m uvicorn main:app --reload
```

FastAPI documentation is available at `http://127.0.0.1:8000/docs` while the server is running.

## Run validation

```bash
python -m ruff check .
python -m mypy main.py
python -m pytest
```

Tests use temporary JSON storage and mocked provider calls. They do not require `ODDS_API_KEY` or live network access.

## API endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Service, provider-key presence, and storage health metadata. |
| `POST /odds` | Current/upcoming sportsbook odds filtered to the requested UTC calendar date. |
| `GET /portfolio/{portfolio_id}` | Current cash bankroll and recent bet history. |
| `POST /bets` | Record an explicitly approved paper bet and reserve its stake. |
| `POST /bet-result` | Settle a recorded bet as win, loss, or push. |
| `GET /portfolio/{portfolio_id}/stats` | Basic settled-bet and sport/market performance statistics. |

`POST /odds` does not query historical odds. It requests the provider's current/upcoming feed and retains games whose timezone-aware `commence_time` falls on the requested date in **UTC**. Past dates normally return no games.

## Project documentation

Durable product and engineering context lives in [`docs/`](docs/):

- [`PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md)
- [`ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`MODEL_LOGIC.md`](docs/MODEL_LOGIC.md)
- [`ROADMAP.md`](docs/ROADMAP.md)
- [`DECISIONS.md`](docs/DECISIONS.md)

Contributors and coding agents should read [`AGENTS.md`](AGENTS.md) before making changes.
