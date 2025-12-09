from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional, Literal, Dict, Tuple
from datetime import date, datetime
from uuid import uuid4
import os
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

# -------------------------------------------------------------------
# Environment & app setup
# -------------------------------------------------------------------

load_dotenv()  # loads variables from .env locally
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

app = FastAPI(
    title="Sports Betting Portfolio Backend",
    version="1.1.0",
    description="Backend for odds, stats, bankroll tracking, and learning stats."
)

# -------------------------------------------------------------------
# Persistence: JSON-backed "database"
# -------------------------------------------------------------------

STARTING_BANKROLL = 200.0

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_FILE = DATA_DIR / "portfolio_db.json"


def load_db_from_file() -> Dict[str, dict]:
    """
    Load DB from JSON file if it exists, otherwise return default structure.
    """
    if DB_FILE.exists():
        try:
            with DB_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # If file is corrupted, fall back to default
            pass

    # Default structure (fresh portfolio)
    return {
        "portfolios": {
            "main": {
                "bankroll": STARTING_BANKROLL,
                "bets": []
            }
        }
    }


def save_db_to_file():
    """
    Persist current DB to JSON file.
    """
    try:
        with DB_FILE.open("w", encoding="utf-8") as f:
            json.dump(DB, f, indent=2, default=str)
    except Exception:
        # For now we silently ignore save errors; could log later.
        pass


# In-memory copy, backed by JSON file
DB: Dict[str, dict] = load_db_from_file()

# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------

class OddsRequest(BaseModel):
    date: date
    # Our high-level sport labels; backend maps them to The Odds API keys
    sports: Optional[List[str]] = None
    # Requestable market types; backend will filter to allowed ones
    markets: Optional[List[str]] = None


class BetIn(BaseModel):
    portfolio_id: str
    date: date
    sport: str
    league: str
    market_type: str  # moneyline, spread, total, player_prop, etc.
    selection: str
    book: str
    odds: int          # American odds, e.g. -110, +150
    stake: float       # amount in dollars

    # Hybrid model metadata (GPT fills these when placing a bet)
    model_prob: Optional[float] = None       # p_model (0-1)
    book_prob: Optional[float] = None        # p_book (0-1)
    edge: Optional[float] = None             # p_model - p_book
    ev_per_1: Optional[float] = None         # expected value per $1 staked


class BetResultIn(BaseModel):
    portfolio_id: str
    bet_id: str
    result: Literal["win", "loss", "push"]
    payout: float               # net profit/loss (e.g. +18.18, -10)
    closing_odds: Optional[int] = None       # optional for CLV
    closing_book_prob: Optional[float] = None


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

def get_portfolio(portfolio_id: str):
    """
    Get or initialize a portfolio. New portfolios start with STARTING_BANKROLL.
    """
    if portfolio_id not in DB["portfolios"]:
        DB["portfolios"][portfolio_id] = {
            "bankroll": STARTING_BANKROLL,
            "bets": []
        }
        save_db_to_file()
    return DB["portfolios"][portfolio_id]


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal."""
    if odds > 0:
        return 1 + odds / 100.0
    else:
        return 1 + 100.0 / (-odds)


def american_to_implied_prob(odds: int) -> float:
    """Implied probability from American odds (before de-juicing)."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    else:
        return (-odds) / ((-odds) + 100.0)


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.post("/odds")
def get_odds(req: OddsRequest):
    """
    Fetch real odds from The Odds API and normalize them.

    GPT decides which sports to query and can control the markets list.
    We only pass through markets The Odds API supports in this basic plan
    (no player props yet; those are handled synthetically in the GPT logic).
    """
    if not ODDS_API_KEY:
        return {
            "error": "Missing ODDS_API_KEY in server environment.",
            "date": str(req.date),
            "sports": req.sports or [],
            "games": []
        }

    # Map our sport labels to The Odds API sport keys
    sport_keys = {
        "NFL": "americanfootball_nfl",
        "NCAAB": "basketball_ncaab",
        "NBA": "basketball_nba",
        "NHL": "icehockey_nhl",
        "MLB": "baseball_mlb",
        "WNBA": "basketball_wnba",
    }

    # Default priority set if GPT doesn't specify sports
    sports_to_query = req.sports or ["NFL", "NCAAB", "NBA", "NHL", "MLB", "WNBA"]

    # Only allow markets that the Odds API supports in our plan (no props)
    ALLOWED_MARKETS = {"h2h", "spreads", "totals"}
    requested_markets = req.markets or ["h2h", "spreads", "totals"]
    markets = [m for m in requested_markets if m in ALLOWED_MARKETS]
    if not markets:
        markets = ["h2h", "spreads", "totals"]

    all_games: List[dict] = []

    for sport in sports_to_query:
        key = sport_keys.get(sport.upper())
        if not key:
            continue

        url = f"https://api.the-odds-api.com/v4/sports/{key}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": ",".join(markets),
            "oddsFormat": "american"
            # Free plan doesn’t support historical date filter; we still include
            # req.date in the response for bookkeeping.
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            all_games.append({
                "sport": sport,
                "error": f"Failed to fetch odds: {e}"
            })
            continue

        # Normalize into our internal structure
        for game in data:
            game_markets = []

            for bookmaker in game.get("bookmakers", []):
                book_name = bookmaker.get("title")

                for market in bookmaker.get("markets", []):
                    market_type = market.get("key")  # 'h2h', 'spreads', 'totals', etc.
                    for outcome in market.get("outcomes", []):
                        game_markets.append({
                            "book": book_name,
                            "market_type": market_type,
                            "selection": outcome.get("name"),
                            "odds": outcome.get("price")
                        })

            all_games.append({
                "game_id": game.get("id"),
                "sport": sport,
                "league": sport,
                "home_team": game.get("home_team"),
                "away_team": game.get("away_team"),
                "commence_time": game.get("commence_time"),
                "markets": game_markets
            })

    return {
        "date": str(req.date),
        "sports": sports_to_query,
        "markets": markets,
        "games": all_games
    }


@app.get("/stats")
def get_stats(
    sport: str,
    season: str,
    teams: Optional[str] = None,
    players: Optional[str] = None
):
    """
    TEMPORARY: returns dummy stats data.
    teams and players are comma-separated strings if provided.
    """
    team_list = teams.split(",") if teams else []
    player_list = players.split(",") if players else []

    return {
        "sport": sport,
        "season": season,
        "teams": team_list,
        "players": player_list,
        "note": "Dummy stats endpoint – replace with real data later."
    }


@app.get("/portfolio/{portfolio_id}")
def get_bankroll_and_bet_history(portfolio_id: str, limit: int = 200):
    """
    Returns current bankroll and last N bets.
    """
    portfolio = get_portfolio(portfolio_id)
    bets = portfolio["bets"][-limit:]
    return {
        "portfolio_id": portfolio_id,
        "bankroll": portfolio["bankroll"],
        "bets": bets
    }


@app.post("/bets")
def record_bet(bet: BetIn):
    """
    Record a new bet and reduce bankroll by the stake.
    GPT should send model_prob, book_prob, edge, ev_per_1 if available.
    """
    portfolio = get_portfolio(bet.portfolio_id)
    bet_id = str(uuid4())

    # Reduce bankroll by stake
    portfolio["bankroll"] -= bet.stake

    bet_dict = bet.model_dump()
    bet_dict["bet_id"] = bet_id
    bet_dict["result"] = None
    bet_dict["payout"] = 0.0
    bet_dict["created_at"] = datetime.utcnow().isoformat()
    bet_dict["closing_odds"] = None
    bet_dict["closing_book_prob"] = None

    portfolio["bets"].append(bet_dict)
    save_db_to_file()

    return {
        "message": "Bet recorded",
        "bet_id": bet_id,
        "bankroll_after": portfolio["bankroll"]
    }


@app.post("/bet-result")
def record_bet_result(data: BetResultIn):
    """
    Update a bet with its result and adjust bankroll.
    Optionally records closing odds for future CLV analysis.
    """
    portfolio = get_portfolio(data.portfolio_id)
    for bet in portfolio["bets"]:
        if bet["bet_id"] == data.bet_id:
            bet["result"] = data.result
            bet["payout"] = data.payout
            bet["closing_odds"] = data.closing_odds
            bet["closing_book_prob"] = data.closing_book_prob
            portfolio["bankroll"] += data.payout

            save_db_to_file()

            return {
                "message": "Bet result recorded",
                "bankroll_after": portfolio["bankroll"]
            }

    return {"error": "Bet not found"}


@app.get("/portfolio/{portfolio_id}/stats")
def get_portfolio_stats(portfolio_id: str):
    """
    Compute learning stats for a portfolio:
    - Overall ROI, hit rate, etc.
    - ROI by (sport, market_type) bucket.
    """
    portfolio = get_portfolio(portfolio_id)
    bets = portfolio["bets"]

    # Only consider bets that have been settled (win/loss/push)
    settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]

    total_staked = sum(b["stake"] for b in settled)
    total_profit = sum(b.get("payout", 0.0) for b in settled)
    wins = sum(1 for b in settled if b["result"] == "win")
    losses = sum(1 for b in settled if b["result"] == "loss")
    pushes = sum(1 for b in settled if b["result"] == "push")
    n_settled = len(settled)

    hit_rate = (wins / n_settled) if n_settled > 0 else 0.0
    roi = (total_profit / total_staked) if total_staked > 0 else 0.0

    # Bucket-level stats by (sport, market_type)
    bucket_map: Dict[Tuple[str, str], dict] = {}

    for b in settled:
        sport = b.get("sport", "UNKNOWN")
        market_type = b.get("market_type", "UNKNOWN")
        key = (sport, market_type)

        if key not in bucket_map:
            bucket_map[key] = {
                "sport": sport,
                "market_type": market_type,
                "bets_settled": 0,
                "wins": 0,
                "losses": 0,
                "pushes": 0,
                "total_staked": 0.0,
                "total_profit": 0.0,
            }

        bucket = bucket_map[key]
        bucket["bets_settled"] += 1
        bucket["total_staked"] += b["stake"]
        bucket["total_profit"] += b.get("payout", 0.0)
        if b["result"] == "win":
            bucket["wins"] += 1
        elif b["result"] == "loss":
            bucket["losses"] += 1
        elif b["result"] == "push":
            bucket["pushes"] += 1

    # Finalize ROI and hit rate per bucket
    buckets = []
    for bucket in bucket_map.values():
        ts = bucket["total_staked"]
        bucket["roi"] = (bucket["total_profit"] / ts) if ts > 0 else 0.0
        if bucket["bets_settled"] > 0:
            bucket["hit_rate"] = bucket["wins"] / bucket["bets_settled"]
        else:
            bucket["hit_rate"] = 0.0
        buckets.append(bucket)

    return {
        "portfolio_id": portfolio_id,
        "starting_bankroll": STARTING_BANKROLL,
        "current_bankroll": portfolio["bankroll"],
        "net_pnl": portfolio["bankroll"] - STARTING_BANKROLL,
        "overall": {
            "bets_settled": n_settled,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "hit_rate": hit_rate,
            "total_staked": total_staked,
            "total_profit": total_profit,
            "roi": roi,
        },
        "by_bucket": buckets,
    }
