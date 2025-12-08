from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import date
from uuid import uuid4
import os

import requests
from dotenv import load_dotenv

# -------------------------------------------------------------------
# Environment & app setup
# -------------------------------------------------------------------

load_dotenv()  # loads variables from .env locally
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

app = FastAPI(
    title="Sports Betting Portfolio Backend",
    version="1.0.0",
    description="Simple backend for odds, stats, and bankroll tracking."
)

# -------------------------------------------------------------------
# In-memory "database" (resets when server restarts)
# -------------------------------------------------------------------

DB = {
    "portfolios": {
        "main": {
            "bankroll": 200.0,
            "bets": []  # list of bet dicts
        }
    }
}

# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------

class OddsRequest(BaseModel):
    date: date
    sports: Optional[List[str]] = None
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


class BetResultIn(BaseModel):
    portfolio_id: str
    bet_id: str
    result: Literal["win", "loss", "push"]
    payout: float      # net profit/loss (e.g. +18.18, -10)


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

def get_portfolio(portfolio_id: str):
    """Get or initialize a portfolio."""
    if portfolio_id not in DB["portfolios"]:
        DB["portfolios"][portfolio_id] = {"bankroll": 200.0, "bets": []}
    return DB["portfolios"][portfolio_id]


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.post("/odds")
def get_odds(req: OddsRequest):
    """
    Fetch real odds from The Odds API (or similar) and normalize them.
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
        "NBA": "basketball_nba",
        "NFL": "americanfootball_nfl",
        "MLB": "baseball_mlb",
        "NHL": "icehockey_nhl",
        # add more mappings if needed
    }

    sports_to_query = req.sports or ["NBA"]
    markets = req.markets or ["h2h"]  # 'h2h' = moneyline
    all_games: List[dict] = []

    for sport in sports_to_query:
        key = sport_keys.get(sport.upper())
        if not key:
            # skip unknown sports
            continue

        url = f"https://api.the-odds-api.com/v4/sports/{key}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",                 # US books
            "markets": ",".join(markets),
            "oddsFormat": "american"
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
                    market_type = market.get("key")  # e.g. 'h2h'
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
    """
    portfolio = get_portfolio(bet.portfolio_id)
    bet_id = str(uuid4())

    # reduce bankroll by stake
    portfolio["bankroll"] -= bet.stake

    bet_dict = bet.model_dump()
    bet_dict["bet_id"] = bet_id
    bet_dict["result"] = None
    bet_dict["payout"] = 0.0

    portfolio["bets"].append(bet_dict)

    return {
        "message": "Bet recorded",
        "bet_id": bet_id,
        "bankroll_after": portfolio["bankroll"]
    }


@app.post("/bet-result")
def record_bet_result(data: BetResultIn):
    """
    Update a bet with its result and adjust bankroll.
    """
    portfolio = get_portfolio(data.portfolio_id)
    for bet in portfolio["bets"]:
        if bet["bet_id"] == data.bet_id:
            bet["result"] = data.result
            bet["payout"] = data.payout
            portfolio["bankroll"] += data.payout
            return {
                "message": "Bet result recorded",
                "bankroll_after": portfolio["bankroll"]
            }

    return {"error": "Bet not found"}
