from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Tuple, Any
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
    version="1.2.0",
    description="Backend for odds, bankroll tracking, bet logging, and learning stats."
)

# -------------------------------------------------------------------
# Persistence: JSON-backed "database"
# -------------------------------------------------------------------

STARTING_BANKROLL = float(os.getenv("STARTING_BANKROLL", "200.0"))

# IMPORTANT for Render persistence:
# - locally: defaults to ./data
# - on Render: set DATA_DIR=/var/data (and mount a Render Disk to /var/data)
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_FILE = DATA_DIR / "portfolio_db.json"


def _default_db() -> Dict[str, Any]:
    return {
        "portfolios": {
            "main": {
                "bankroll": STARTING_BANKROLL,
                "bets": []
            }
        }
    }


def load_db_from_file() -> Dict[str, Any]:
    if DB_FILE.exists():
        try:
            with DB_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # basic shape validation
            if isinstance(data, dict) and "portfolios" in data:
                return data
        except Exception:
            pass
    return _default_db()


def save_db_to_file(db: Dict[str, Any]) -> None:
    try:
        tmp = DB_FILE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, default=str)
        tmp.replace(DB_FILE)
    except Exception:
        # If disk is misconfigured on Render, saves can fail silently.
        # Check Render Logs if you suspect this.
        pass


DB: Dict[str, Any] = load_db_from_file()

# -------------------------------------------------------------------
# Normalization helpers (this fixes your "GPT says no odds" mismatch)
# -------------------------------------------------------------------

SUPPORTED_SPORTS = {"NFL", "NCAAB", "NBA", "NHL", "MLB", "WNBA"}

SPORT_ALIASES = {
    # common lowercase / variants
    "NFL": "NFL",
    "NCAAB": "NCAAB",
    "NCAAM": "NCAAB",
    "NCAA": "NCAAB",
    "NCAA_M": "NCAAB",
    "NCCAMB": "NCAAB",  # <-- your earlier typo
    "COLLEGE": "NCAAB",
    "COLLEGE_BASKETBALL": "NCAAB",
    "COLLEGE_MENS_BASKETBALL": "NCAAB",
    "NBA": "NBA",
    "NHL": "NHL",
    "MLB": "MLB",
    "WNBA": "WNBA",
}

# Odds API sport keys
SPORT_KEYS = {
    "NFL": "americanfootball_nfl",
    "NCAAB": "basketball_ncaab",
    "NBA": "basketball_nba",
    "NHL": "icehockey_nhl",
    "MLB": "baseball_mlb",
    "WNBA": "basketball_wnba",
}

# We only support these markets for now from The Odds API plan
ALLOWED_MARKETS = {"h2h", "spreads", "totals"}

MARKET_ALIASES = {
    "ML": "h2h",
    "MONEYLINE": "h2h",
    "H2H": "h2h",
    "SPREAD": "spreads",
    "SPREADS": "spreads",
    "TOTAL": "totals",
    "TOTALS": "totals",
    "OU": "totals",
    "OVER_UNDER": "totals",
}


def normalize_sport(s: str) -> str:
    x = (s or "").strip().upper()
    # if they send "nba" -> "NBA"
    # if they send "basketball_nba" -> not supported; keep as-is (will error)
    return SPORT_ALIASES.get(x, x)


def normalize_markets(markets: Optional[List[str]]) -> List[str]:
    if not markets:
        return ["h2h", "spreads", "totals"]
    out = []
    for m in markets:
        x = (m or "").strip().upper()
        out.append(MARKET_ALIASES.get(x, (m or "").strip().lower()))
    # filter to what we actually support
    out = [m for m in out if m in ALLOWED_MARKETS]
    return out or ["h2h", "spreads", "totals"]


# Books filter (you asked DK/FD/BetMGM only)
DEFAULT_ALLOWED_BOOKS = {"DraftKings", "FanDuel", "BetMGM"}


# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------

class OddsRequest(BaseModel):
    date: date
    sports: Optional[List[str]] = None
    markets: Optional[List[str]] = None
    # optional controls to avoid huge responses
    allowed_books: Optional[List[str]] = None
    max_games_per_sport: int = Field(default=50, ge=1, le=200)


class BetIn(BaseModel):
    portfolio_id: str
    date: date
    sport: str
    league: str
    market_type: str  # h2h, spreads, totals, (future: player_prop)
    selection: str
    book: str
    odds: int
    stake: float

    # model metadata
    model_prob: Optional[float] = None
    book_prob: Optional[float] = None
    edge: Optional[float] = None
    ev_per_1: Optional[float] = None


class BetResultIn(BaseModel):
    portfolio_id: str
    bet_id: str
    result: Literal["win", "loss", "push"]
    payout: float  # NET profit/loss (e.g. +18.18, -10.00, 0.00 for push)
    closing_odds: Optional[int] = None
    closing_book_prob: Optional[float] = None


# -------------------------------------------------------------------
# Portfolio helpers
# -------------------------------------------------------------------

def get_portfolio(portfolio_id: str) -> Dict[str, Any]:
    if "portfolios" not in DB:
        DB["portfolios"] = {}

    if portfolio_id not in DB["portfolios"]:
        DB["portfolios"][portfolio_id] = {"bankroll": STARTING_BANKROLL, "bets": []}
        save_db_to_file(DB)

    return DB["portfolios"][portfolio_id]


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "ok": True,
        "has_odds_key": bool(ODDS_API_KEY),
        "db_file": str(DB_FILE),
        "data_dir": str(DATA_DIR),
        "time_utc": datetime.utcnow().isoformat()
    }


@app.post("/odds")
def get_odds(req: OddsRequest):
    """
    Fetch odds from The Odds API and normalize them.
    - Sports are normalized (nba/NCCAMB/etc).
    - Markets are normalized and restricted (h2h/spreads/totals).
    - Books are filtered to keep responses small (default DK/FD/BetMGM).
    """
    if not ODDS_API_KEY:
        return {"error": "Missing ODDS_API_KEY in server environment.", "date": str(req.date), "games": []}

    # normalize sports
    raw_sports = req.sports or ["NFL", "NCAAB", "NBA", "NHL", "MLB", "WNBA"]
    sports_to_query = [normalize_sport(s) for s in raw_sports]

    # normalize markets
    markets = normalize_markets(req.markets)

    # allowed books
    allowed_books = set(req.allowed_books) if req.allowed_books else DEFAULT_ALLOWED_BOOKS

    all_games: List[dict] = []
    per_sport_errors: List[dict] = []

    for sport in sports_to_query:
        if sport not in SUPPORTED_SPORTS:
            per_sport_errors.append({"sport": sport, "error": f"Unsupported sport '{sport}'"})
            continue

        odds_key = SPORT_KEYS[sport]
        url = f"https://api.the-odds-api.com/v4/sports/{odds_key}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": ",".join(markets),
            "oddsFormat": "american",
        }

        try:
            resp = requests.get(url, params=params, timeout=12)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            per_sport_errors.append({"sport": sport, "error": f"Failed to fetch odds: {e}"})
            continue

        # cap games per sport (prevents ResponseTooLarge)
        data = data[: req.max_games_per_sport]

        for game in data:
            offers: List[dict] = []

            for bookmaker in game.get("bookmakers", []):
                book_name = bookmaker.get("title")
                if book_name not in allowed_books:
                    continue

                for market in bookmaker.get("markets", []):
                    market_type = market.get("key")
                    if market_type not in ALLOWED_MARKETS:
                        continue

                    for outcome in market.get("outcomes", []):
                        offer = {
                            "book": book_name,
                            "market_type": market_type,
                            "selection": outcome.get("name"),
                            "odds": outcome.get("price"),
                        }
                        # spreads/totals include a "point" field; include if present
                        if "point" in outcome:
                            offer["point"] = outcome.get("point")
                        offers.append(offer)

            # if none of our books had lines, skip the game to keep results clean
            if not offers:
                continue

            all_games.append({
                "game_id": game.get("id"),
                "sport": sport,
                "league": sport,
                "home_team": game.get("home_team"),
                "away_team": game.get("away_team"),
                "commence_time": game.get("commence_time"),
                "offers": offers,
            })

    return {
        "date": str(req.date),
        "sports": sports_to_query,
        "markets": markets,
        "allowed_books": sorted(list(allowed_books)),
        "games": all_games,
        "errors": per_sport_errors,
    }


@app.get("/portfolio/{portfolio_id}")
def get_bankroll_and_bet_history(portfolio_id: str, limit: int = 200):
    portfolio = get_portfolio(portfolio_id)
    bets = portfolio["bets"][-limit:]
    return {"portfolio_id": portfolio_id, "bankroll": portfolio["bankroll"], "bets": bets}


@app.post("/bets")
def record_bet(bet: BetIn):
    portfolio = get_portfolio(bet.portfolio_id)

    if bet.stake <= 0:
        raise HTTPException(status_code=400, detail="Stake must be > 0")

    if portfolio["bankroll"] < bet.stake:
        raise HTTPException(status_code=400, detail="Insufficient bankroll for this stake")

    bet_id = str(uuid4())

    # deduct stake now (cash leaves bankroll while bet is open)
    portfolio["bankroll"] -= bet.stake

    bet_dict = bet.model_dump()
    bet_dict["bet_id"] = bet_id
    bet_dict["result"] = None
    bet_dict["payout"] = 0.0  # NET payout (profit/loss). For wins, positive profit; for loss, -stake; for push, 0.
    bet_dict["created_at"] = datetime.utcnow().isoformat()
    bet_dict["closing_odds"] = None
    bet_dict["closing_book_prob"] = None

    portfolio["bets"].append(bet_dict)
    save_db_to_file(DB)

    return {"message": "Bet recorded", "bet_id": bet_id, "bankroll_after": portfolio["bankroll"]}


@app.post("/bet-result")
def record_bet_result(data: BetResultIn):
    """
    IMPORTANT: `payout` is NET profit/loss.
    Since we already deducted the stake at bet placement, settlement should add back:
      bankroll += stake + net_payout

    Examples:
      - $10 at -110 wins -> net profit ~ +9.09 -> add back 10 + 9.09 = 19.09
      - loss -> net payout = -10.00 -> add back 10 + (-10) = 0
      - push -> net payout = 0.00 -> add back 10 + 0 = 10
    """
    portfolio = get_portfolio(data.portfolio_id)

    for bet in portfolio["bets"]:
        if bet["bet_id"] == data.bet_id:
            if bet.get("result") in ("win", "loss", "push"):
                raise HTTPException(status_code=400, detail="Bet already settled")

            bet["result"] = data.result
            bet["payout"] = float(data.payout)
            bet["closing_odds"] = data.closing_odds
            bet["closing_book_prob"] = data.closing_book_prob
            bet["settled_at"] = datetime.utcnow().isoformat()

            stake = float(bet.get("stake", 0.0))
            bankroll_adjust = stake + float(data.payout)
            portfolio["bankroll"] += bankroll_adjust

            save_db_to_file(DB)
            return {"message": "Bet result recorded", "bankroll_after": portfolio["bankroll"]}

    raise HTTPException(status_code=404, detail="Bet not found")


@app.get("/portfolio/{portfolio_id}/stats")
def get_portfolio_stats(portfolio_id: str):
    portfolio = get_portfolio(portfolio_id)
    bets = portfolio["bets"]

    settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]

    total_staked = sum(float(b.get("stake", 0.0)) for b in settled)
    # payout is NET profit/loss (so ROI = net_profit / total_staked)
    total_profit = sum(float(b.get("payout", 0.0)) for b in settled)

    wins = sum(1 for b in settled if b["result"] == "win")
    losses = sum(1 for b in settled if b["result"] == "loss")
    pushes = sum(1 for b in settled if b["result"] == "push")
    n_settled = len(settled)

    hit_rate = (wins / n_settled) if n_settled > 0 else 0.0
    roi = (total_profit / total_staked) if total_staked > 0 else 0.0

    bucket_map: Dict[Tuple[str, str], dict] = {}

    for b in settled:
        sport = str(b.get("sport", "UNKNOWN"))
        market_type = str(b.get("market_type", "UNKNOWN"))
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
        bucket["total_staked"] += float(b.get("stake", 0.0))
        bucket["total_profit"] += float(b.get("payout", 0.0))
        if b["result"] == "win":
            bucket["wins"] += 1
        elif b["result"] == "loss":
            bucket["losses"] += 1
        else:
            bucket["pushes"] += 1

    buckets = []
    for bucket in bucket_map.values():
        ts = float(bucket["total_staked"])
        bucket["roi"] = (float(bucket["total_profit"]) / ts) if ts > 0 else 0.0
        bucket["hit_rate"] = (bucket["wins"] / bucket["bets_settled"]) if bucket["bets_settled"] > 0 else 0.0
        buckets.append(bucket)

    return {
        "portfolio_id": portfolio_id,
        "starting_bankroll": STARTING_BANKROLL,
        "current_bankroll": float(portfolio["bankroll"]),
        "net_pnl": float(portfolio["bankroll"]) - STARTING_BANKROLL,
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
