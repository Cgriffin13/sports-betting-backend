"""Reproduce the bounded 2020-2024 NCAAF cross-line calibration audit offline."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


ROOT = Path(".ncaaf-data")
MARKET_MANIFEST = (
    ROOT / "historical-market/manifests/bd88f4c68efbbc7d55d4ced6aeabec6304bbbd4125a2dcb89cc176174c183d5b.json"
)
FEATURE_MANIFEST = ROOT / "features/manifests/beebc297a31ff307daf7878215bb1554fb8421d5361fff652b8443191c568d24.json"
HORIZON = "morning_first_kickoff_minus_3h"


def implied(odds: int) -> float:
    return 100 / (odds + 100) if odds > 0 else abs(odds) / (abs(odds) + 100)


def decimal_odds(odds: int) -> float:
    return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)


def paired(rows: list[dict], market: str) -> list[dict]:
    sides = ("home", "away") if market == "spreads" else ("over", "under")
    by_book: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        if row["market_type"] == market and row["side"] in sides and row["supported_sportsbook"]:
            by_book[row["sportsbook"]][row["side"]] = row
    result = []
    for book, values in by_book.items():
        if set(values) != set(sides):
            continue
        a, b = values[sides[0]], values[sides[1]]
        if a["point"] is None or b["point"] is None:
            continue
        if market == "spreads" and not math.isclose(float(a["point"]), -float(b["point"]), abs_tol=1e-8):
            continue
        if market == "totals" and not math.isclose(float(a["point"]), float(b["point"]), abs_tol=1e-8):
            continue
        qa, qb = implied(int(a["american_odds"])), implied(int(b["american_odds"]))
        result.append({"book": book, "a": a, "b": b, "p": qa / (qa + qb), "overround": qa + qb - 1})
    return result


def moneyline_candidates(targets: dict[int, dict], seasons: dict[int, dict[int, list[dict]]]) -> list[dict]:
    output = []
    for season in sorted(seasons):
        for game_id, rows in seasons[season].items():
            by_book: dict[str, dict[str, dict]] = defaultdict(dict)
            for row in rows:
                if row["market_type"] == "h2h" and row["supported_sportsbook"] and row["side"] in {"home", "away"}:
                    by_book[row["sportsbook"]][row["side"]] = row
            books = []
            for book, sides in by_book.items():
                if set(sides) != {"home", "away"}:
                    continue
                qh, qa = implied(int(sides["home"]["american_odds"])), implied(int(sides["away"]["american_odds"]))
                books.append((book, sides, qh / (qh + qa), qh + qa - 1))
            if len(books) < 2:
                continue
            actual = float(targets[game_id]["target_margin"])
            for side in ("home", "away"):
                fair = float(np.median([item[2] if side == "home" else 1 - item[2] for item in books]))
                offers = [item[1][side] for item in books]
                offer = max(offers, key=lambda item: decimal_odds(int(item["american_odds"])))
                price = decimal_odds(int(offer["american_odds"]))
                edge = fair - 1 / price
                ev = fair * price - 1
                won = actual > 0 if side == "home" else actual < 0
                output.append(
                    {
                        "season": season,
                        "game_id": game_id,
                        "market": "h2h",
                        "side": side,
                        "odds": int(offer["american_odds"]),
                        "edge": edge,
                        "ev": ev,
                        "realized": price - 1 if won else -1,
                        "books": len(books),
                        "dispersion": max(item[2] if side == "home" else 1 - item[2] for item in books)
                        - min(item[2] if side == "home" else 1 - item[2] for item in books),
                    }
                )
    return output


def discrete_probs(
    residuals: np.ndarray, center: float, line: float, market: str, first_side: bool
) -> tuple[float, float, float]:
    values = center + residuals
    lower = np.floor(values)
    fraction = values - lower
    upper = lower + 1
    if market == "spreads":
        lower_result = lower + line if first_side else lower - line
        upper_result = upper + line if first_side else upper - line
    else:
        lower_result = lower - line
        upper_result = upper - line

    def outcome_mass(results: np.ndarray, weights: np.ndarray) -> tuple[float, float, float]:
        if first_side:
            win = float(np.sum(weights[results > 1e-9]))
            loss = float(np.sum(weights[results < -1e-9]))
        else:
            win = float(np.sum(weights[results < -1e-9]))
            loss = float(np.sum(weights[results > 1e-9]))
        push = float(np.sum(weights[np.abs(results) <= 1e-9]))
        return win, push, loss

    n = len(residuals)
    low = outcome_mass(lower_result, (1 - fraction) / n)
    high = outcome_mass(upper_result, fraction / n)
    return tuple(low[i] + high[i] for i in range(3))


def infer_center(residuals: np.ndarray, line: float, market: str, target: float) -> float:
    base = -line if market == "spreads" else line
    lo, hi = base - 40.0, base + 40.0
    for _ in range(55):
        mid = (lo + hi) / 2
        win, _push, loss = discrete_probs(residuals, mid, line, market, True)
        conditional = win / (win + loss)
        if conditional < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def weighted_huber(values: list[float], overrounds: list[float]) -> tuple[float, float]:
    base = np.asarray([min(2.0, max(0.5, 0.04 / max(value, 0.02))) for value in overrounds])
    data = np.asarray(values)
    order = np.argsort(data)
    cumulative = np.cumsum(base[order])
    median = float(data[order[np.searchsorted(cumulative, cumulative[-1] / 2)]])
    deviations = np.abs(data - median)
    mad = float(np.median(deviations))
    cutoff = max(0.5, 1.5 * 1.4826 * mad)
    influence = np.minimum(1.0, cutoff / np.maximum(deviations, 1e-12))
    weights = base * influence
    center = float(np.sum(data * weights) / np.sum(weights))
    return center, float(np.max(data) - np.min(data))


def load() -> tuple[dict[int, dict], dict[int, dict[int, list[dict]]]]:
    feature_manifest = json.loads(FEATURE_MANIFEST.read_text())
    feature_artifact = next(
        a for a in feature_manifest["artifacts"] if a["dataset"] == "model_ready_games" and "2f219" in a["uri"]
    )
    features = (
        pq.ParquetFile(ROOT / feature_artifact["uri"])
        .read(columns=["provider_game_id", "season", "target_margin", "target_total"])
        .to_pylist()
    )
    targets = {int(row["provider_game_id"]): row for row in features}
    market_manifest = json.loads(MARKET_MANIFEST.read_text())
    seasons: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    columns = [
        "cfbd_game_id",
        "season",
        "horizon",
        "sportsbook",
        "supported_sportsbook",
        "market_type",
        "side",
        "point",
        "american_odds",
    ]
    for artifact in market_manifest["artifacts"]:
        if artifact["dataset"] != "observations":
            continue
        for batch in pq.ParquetFile(ROOT / artifact["uri"]).iter_batches(batch_size=16384, columns=columns):
            for row in batch.to_pylist():
                if row["horizon"] == HORIZON and int(row["cfbd_game_id"]) in targets:
                    seasons[int(row["season"])][int(row["cfbd_game_id"])].append(row)
    return targets, seasons


def raw_center(rows: list[dict], market: str) -> float | None:
    pairs = paired(rows, market)
    if len(pairs) < 2:
        return None
    points = [-float(item["a"]["point"]) if market == "spreads" else float(item["a"]["point"]) for item in pairs]
    return float(np.median(points))


def candidate_rows(targets: dict[int, dict], seasons: dict[int, dict[int, list[dict]]]) -> list[dict]:
    historical: dict[str, list[float]] = {"spreads": [], "totals": []}
    output = []
    for season in sorted(seasons):
        print("cross-line-season", season, flush=True)
        training = {market: np.asarray(values, dtype=float) for market, values in historical.items()}
        center_cache: dict[tuple[str, float, float], float] = {}
        for game_id, rows in seasons[season].items():
            target = targets[game_id]
            for market, target_name in (("spreads", "target_margin"), ("totals", "target_total")):
                center0 = raw_center(rows, market)
                pairs = paired(rows, market)
                if center0 is None:
                    continue
                actual = float(target[target_name])
                if len(training[market]) >= 300:
                    book_centers = []
                    for item in pairs:
                        cache_key = (market, float(item["a"]["point"]), round(item["p"], 6))
                        if cache_key not in center_cache:
                            center_cache[cache_key] = infer_center(
                                training[market], float(item["a"]["point"]), market, item["p"]
                            )
                        book_centers.append(center_cache[cache_key])
                    center, center_dispersion = weighted_huber(book_centers, [item["overround"] for item in pairs])
                    for first_side in (True, False):
                        options = []
                        for item in pairs:
                            offer = item["a"] if first_side else item["b"]
                            win, push, loss = discrete_probs(
                                training[market], center, float(offer["point"]), market, first_side
                            )
                            price = decimal_odds(int(offer["american_odds"]))
                            ev = win * (price - 1) - loss
                            conditional = win / (win + loss)
                            edge = conditional - 1 / price
                            projected = [
                                discrete_probs(
                                    training[market],
                                    book_center,
                                    float(offer["point"]),
                                    market,
                                    first_side,
                                )
                                for book_center in book_centers
                            ]
                            conditional = [value[0] / (value[0] + value[2]) for value in projected]
                            dispersion = max(conditional) - min(conditional)
                            options.append((ev, edge, offer, win, push, loss, price, dispersion))
                        ev, edge, offer, win, push, loss, price, dispersion = max(
                            options, key=lambda item: (item[0], item[1], item[2]["american_odds"])
                        )
                        if market == "spreads":
                            settlement = (
                                actual + float(offer["point"]) if first_side else actual - float(offer["point"])
                            )
                            realized = (
                                price - 1
                                if (settlement > 0 if first_side else settlement < 0)
                                else 0
                                if settlement == 0
                                else -1
                            )
                        else:
                            settlement = actual - float(offer["point"])
                            realized = (
                                price - 1
                                if (settlement > 0 if first_side else settlement < 0)
                                else 0
                                if settlement == 0
                                else -1
                            )
                        output.append(
                            {
                                "season": season,
                                "game_id": game_id,
                                "market": market,
                                "side": ("home" if first_side else "away")
                                if market == "spreads"
                                else ("over" if first_side else "under"),
                                "center": center,
                                "center_dispersion": center_dispersion,
                                "line": float(offer["point"]),
                                "odds": int(offer["american_odds"]),
                                "win": win,
                                "push": push,
                                "loss": loss,
                                "edge": edge,
                                "ev": ev,
                                "realized": realized,
                                "books": len(pairs),
                                "dispersion": dispersion,
                                "advantage": (center + float(offer["point"]))
                                if market == "spreads" and first_side
                                else (
                                    (-center + float(offer["point"]))
                                    if market == "spreads"
                                    else (
                                        center - float(offer["point"]) if first_side else float(offer["point"]) - center
                                    )
                                ),
                            }
                        )
                historical[market].append(actual - center0)
    return output


def summarize(rows: list[dict]) -> None:
    print("rows", len(rows))
    for market in ("spreads", "totals", "h2h"):
        data = [row for row in rows if row["market"] == market]
        main_board = [row for row in data if row["odds"] <= 500]
        print("\n", market, "rows", len(data))
        print("main-board-eligible rows", len(main_board))
        for season in sorted({row["season"] for row in data}):
            season_rows = [row for row in data if row["season"] == season]
            print(
                "season",
                season,
                "n",
                len(season_rows),
                "mean_ev",
                np.mean([r["ev"] for r in season_rows]),
                "roi",
                np.mean([r["realized"] for r in season_rows]),
            )
        for threshold in (0.0, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03):
            picked = [row for row in data if row["edge"] >= threshold and row["ev"] >= 0.015]
            main_board_picked = [row for row in picked if row["odds"] <= 500]
            print(
                "edge>=",
                threshold,
                "ev>=.015",
                "n",
                len(picked),
                "roi",
                round(float(np.mean([r["realized"] for r in picked])), 4) if picked else None,
                "modeled",
                round(float(np.mean([r["ev"] for r in picked])), 4) if picked else None,
                "2024n",
                sum(r["season"] == 2024 for r in picked),
                "2024roi",
                round(float(np.mean([r["realized"] for r in picked if r["season"] == 2024])), 4)
                if any(r["season"] == 2024 for r in picked)
                else None,
                "main_board_n",
                len(main_board_picked),
                "main_board_roi",
                round(float(np.mean([r["realized"] for r in main_board_picked])), 4)
                if main_board_picked
                else None,
            )
        buckets = ((-99, 0), (0, 0.005), (0.005, 0.01), (0.01, 0.02), (0.02, 0.04), (0.04, 99))
        for lo, hi in buckets:
            picked = [r for r in data if lo <= r["edge"] < hi]
            print(
                "edge bucket",
                lo,
                hi,
                "n",
                len(picked),
                "roi",
                round(float(np.mean([r["realized"] for r in picked])), 4) if picked else None,
                "modeled",
                round(float(np.mean([r["ev"] for r in picked])), 4) if picked else None,
            )
        print("edge quantiles", np.quantile([r["edge"] for r in data], [0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1]))
        print("top", sorted(data, key=lambda r: r["ev"], reverse=True)[:5])
        if market != "h2h":
            for lo, hi in ((-99, 0), (0, 0.5), (0.5, 1), (1, 2), (2, 99)):
                picked = [r for r in data if lo <= r["advantage"] < hi]
                print(
                    "advantage bucket",
                    lo,
                    hi,
                    "n",
                    len(picked),
                    "roi",
                    round(float(np.mean([r["realized"] for r in picked])), 4) if picked else None,
                )


if __name__ == "__main__":
    targets, seasons = load()
    rows = candidate_rows(targets, seasons)
    rows.extend(moneyline_candidates(targets, seasons))
    summarize(rows)
