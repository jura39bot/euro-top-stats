"""
Collecteur cotes — The Odds API (the-odds-api.com).

Agrège les cotes de +80 bookmakers pour les ligues couvertes.
Free tier : 500 req/mois (quota affiché dans les headers de réponse).

Clé API : variable d'env ODDS_API_KEY
Inscription gratuite : https://the-odds-api.com

Documentation : https://the-odds-api.com/liveapi/guides/v4/
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from ..config import ODDS_API_KEY

logger = logging.getLogger(__name__)

_BASE = "https://api.the-odds-api.com/v4"

# Mapping league_key → sport key The Odds API
ODDS_SPORT_KEYS: dict[str, str] = {
    "ligue1":     "soccer_france_ligue_one",
    "pl":         "soccer_epl",
    "laliga":     "soccer_spain_la_liga",
    "seriea":     "soccer_italy_serie_a",
    "bundesliga": "soccer_germany_bundesliga",
    "cl":         "soccer_uefa_champs_league",
    "el":         "soccer_uefa_europa_league",
    "ecl":        "soccer_uefa_europa_conference_league",
}

# Bookmakers européens pertinents (filtrés depuis la réponse)
EU_BOOKMAKERS = {
    "unibet_eu", "betclic", "winamax", "pinnacle",
    "betway", "bwin", "williamhill", "bet365",
    "ladbrokes", "pmu", "fdj",
}


class OddsQuotaError(Exception):
    """Quota mensuel The Odds API épuisé."""


class OddsClient:
    """Client The Odds API — lecture seule."""

    def __init__(self):
        if not ODDS_API_KEY:
            raise ValueError(
                "ODDS_API_KEY non définie. "
                "Inscription gratuite sur https://the-odds-api.com"
            )
        self._session = requests.Session()
        self._session.params = {"apiKey": ODDS_API_KEY}  # type: ignore
        self._remaining: Optional[int] = None
        self._used: Optional[int] = None

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        url = f"{_BASE}{path}"
        r = self._session.get(url, params=params or {}, timeout=15)

        # Quota dans les headers
        self._remaining = int(r.headers.get("x-requests-remaining", -1))
        self._used = int(r.headers.get("x-requests-used", -1))

        if r.status_code == 401:
            raise ValueError("ODDS_API_KEY invalide")
        if r.status_code == 429:
            raise OddsQuotaError(
                f"Quota mensuel The Odds API épuisé "
                f"({self._used} req utilisées)"
            )
        r.raise_for_status()
        return r.json()

    @property
    def quota_remaining(self) -> Optional[int]:
        return self._remaining

    # ── Sports disponibles ────────────────────────────────────────────────────

    def list_sports(self) -> list[dict]:
        """Liste les sports/compétitions actifs."""
        return self._get("/sports")  # type: ignore

    # ── Cotes à venir ─────────────────────────────────────────────────────────

    def fetch_odds(
        self,
        league_key: str,
        markets: list[str] | None = None,
        regions: str = "eu",
        bookmakers: list[str] | None = None,
        days_from_now: int = 7,
    ) -> list[dict]:
        """
        Récupère les cotes des prochains matchs d'une ligue.

        Args:
            league_key   : Ex. "ligue1", "cl"
            markets      : ["h2h"] (1X2), ["totals"] (o/u), ["spreads"]
            regions      : "eu" (Europe), "uk", "us", "au"
            bookmakers   : Filtrer sur certains bookmakers (None = tous)
            days_from_now: Horizon en jours (approximatif, dépend du schedule)

        Retourne une liste de matchs avec cotes :
            [{
                id, home_team, away_team, commence_time,
                bookmakers: [{name, markets: [{key, outcomes}]}]
            }]
        """
        sport_key = ODDS_SPORT_KEYS.get(league_key)
        if not sport_key:
            logger.error(
                f"Ligue '{league_key}' non supportée par The Odds API. "
                f"Ligues valides : {', '.join(ODDS_SPORT_KEYS)}"
            )
            return []

        markets = markets or ["h2h"]
        params: dict = {
            "regions":  regions,
            "markets":  ",".join(markets),
            "dateFormat": "iso",
            "oddsFormat": "decimal",
        }
        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)

        logger.info(
            f"The Odds API [{league_key}] {sport_key} — marchés: {markets}"
        )
        try:
            data = self._get(f"/sports/{sport_key}/odds", params)
            logger.info(
                f"  → {len(data)} matchs | "  # type: ignore
                f"quota restant: {self._remaining} req"
            )
            return data  # type: ignore
        except OddsQuotaError:
            logger.error("Quota mensuel épuisé — 500 req/mois max (free)")
            return []
        except Exception as e:
            logger.error(f"Erreur Odds API [{league_key}]: {e}")
            return []

    # ── Score scores (résultats avec cotes pré-match) ────────────────────────

    def fetch_scores(self, league_key: str, days_old: int = 3) -> list[dict]:
        """
        Récupère les résultats récents avec les cotes pré-match.
        Utile pour backtester la stratégie value.
        """
        sport_key = ODDS_SPORT_KEYS.get(league_key)
        if not sport_key:
            return []
        try:
            data = self._get(
                f"/sports/{sport_key}/scores",
                {"daysOld": days_old, "dateFormat": "iso"}
            )
            return data  # type: ignore
        except Exception as e:
            logger.error(f"Erreur scores Odds API [{league_key}]: {e}")
            return []


# ── Parsing / helpers ──────────────────────────────────────────────────────────

def parse_h2h(event: dict, preferred_books: set[str] | None = None) -> dict | None:
    """
    Extrait les meilleures cotes 1X2 d'un event Odds API.

    Retourne :
        {home_team, away_team, commence_time,
         best_home_odds, best_draw_odds, best_away_odds,
         best_home_book, best_draw_book, best_away_book,
         avg_home_odds, avg_draw_odds, avg_away_odds,
         implied_home_prob, implied_draw_prob, implied_away_prob,
         market_margin}
    """
    books = event.get("bookmakers", [])
    if not books:
        return None

    home = event["home_team"]
    away = event["away_team"]

    best: dict[str, tuple[float, str]] = {
        "home": (0.0, ""),
        "draw": (0.0, ""),
        "away": (0.0, ""),
    }
    sums: dict[str, list[float]] = {"home": [], "draw": [], "away": []}

    for book in books:
        bname = book["key"]
        if preferred_books and bname not in preferred_books:
            continue
        for market in book.get("markets", []):
            if market["key"] != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                oname = outcome["name"]
                price = float(outcome["price"])
                if oname == home:
                    sums["home"].append(price)
                    if price > best["home"][0]:
                        best["home"] = (price, bname)
                elif oname == away:
                    sums["away"].append(price)
                    if price > best["away"][0]:
                        best["away"] = (price, bname)
                elif oname == "Draw":
                    sums["draw"].append(price)
                    if price > best["draw"][0]:
                        best["draw"] = (price, bname)

    if not sums["home"]:
        return None

    avg_h = _avg(sums["home"])
    avg_d = _avg(sums["draw"])
    avg_a = _avg(sums["away"])

    # Probabilités implicites (best odds = moins de marge)
    ih = 1 / best["home"][0] if best["home"][0] else None
    id_ = 1 / best["draw"][0] if best["draw"][0] else None
    ia = 1 / best["away"][0] if best["away"][0] else None

    # Marge bookmaker (sur cotes moyennes)
    margin = None
    if avg_h and avg_d and avg_a:
        margin = round((1/avg_h + 1/avg_d + 1/avg_a - 1) * 100, 2)

    return {
        "home_team":          home,
        "away_team":          away,
        "commence_time":      event.get("commence_time"),
        "best_home_odds":     best["home"][0],
        "best_draw_odds":     best["draw"][0],
        "best_away_odds":     best["away"][0],
        "best_home_book":     best["home"][1],
        "best_draw_book":     best["draw"][1],
        "best_away_book":     best["away"][1],
        "avg_home_odds":      round(avg_h, 3) if avg_h else None,
        "avg_draw_odds":      round(avg_d, 3) if avg_d else None,
        "avg_away_odds":      round(avg_a, 3) if avg_a else None,
        "implied_home_prob":  round(ih, 4) if ih else None,
        "implied_draw_prob":  round(id_, 4) if id_ else None,
        "implied_away_prob":  round(ia, 4) if ia else None,
        "market_margin_pct":  margin,
        "bookmakers_count":   len(books),
    }


def implied_to_fair(home_odds: float, draw_odds: float, away_odds: float) -> tuple[float, float, float]:
    """
    Supprime la marge bookmaker et retourne les probabilités équitables.
    (normalisation de Shin simplifiée)
    """
    ih = 1 / home_odds
    id_ = 1 / draw_odds
    ia = 1 / away_odds
    total = ih + id_ + ia
    return ih / total, id_ / total, ia / total


def _avg(lst: list[float]) -> float | None:
    return sum(lst) / len(lst) if lst else None
