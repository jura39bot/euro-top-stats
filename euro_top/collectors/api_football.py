"""Collecteur API-Football (api-sports.io) — free tier 100 req/jour."""
from __future__ import annotations
import logging
import time
from datetime import datetime, date

import httpx

from ..config import API_FOOTBALL_KEY, API_FOOTBALL_BASE, API_DAILY_LIMIT, SEASON
from ..db import (
    Session, count_api_calls_today, log_api_call,
    upsert_standings, upsert_players, upsert_matches,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "x-apisports-key": API_FOOTBALL_KEY,
}


class RateLimitError(Exception):
    pass


class ApiFootballClient:
    """Client HTTP pour API-Football."""

    def __init__(self, session: Session):
        self.session = session
        self._client = httpx.Client(
            base_url=API_FOOTBALL_BASE,
            headers=HEADERS,
            timeout=15,
        )

    def _check_rate_limit(self):
        used = count_api_calls_today(self.session)
        if used >= API_DAILY_LIMIT:
            raise RateLimitError(
                f"Quota journalier atteint ({used}/{API_DAILY_LIMIT} req). "
                "Réessaie demain ou augmente ton plan."
            )

    def _get(self, endpoint: str, params: dict, league_id: int | None = None) -> dict:
        self._check_rate_limit()
        resp = self._client.get(endpoint, params=params)
        log_api_call(
            self.session,
            endpoint=f"{endpoint}?{resp.request.url.query}",
            league_id=league_id,
            season=params.get("season"),
            status=resp.status_code,
        )
        resp.raise_for_status()
        data = resp.json()
        time.sleep(0.3)  # Politesse
        return data

    def close(self):
        self._client.close()

    # ── Standings ─────────────────────────────────────────────────────────────

    def fetch_standings(self, league_id: int, season: int = SEASON) -> list[dict]:
        """Récupère le classement d'une ligue."""
        data = self._get("/standings", {"league": league_id, "season": season}, league_id)
        rows = []
        for entry in data.get("response", []):
            league_data = entry.get("league", {})
            for group in league_data.get("standings", []):
                for team_entry in group:
                    team = team_entry.get("team", {})
                    all_ = team_entry.get("all", {})
                    goals = all_.get("goals", {})
                    rows.append({
                        "league_id": league_id,
                        "season": season,
                        "rank": team_entry.get("rank"),
                        "team": team.get("name"),
                        "team_short": (team.get("name") or "")[:20],
                        "played": all_.get("played", 0),
                        "won": all_.get("win", 0),
                        "drawn": all_.get("draw", 0),
                        "lost": all_.get("lose", 0),
                        "goals_for": goals.get("for", 0),
                        "goals_against": goals.get("against", 0),
                        "goal_diff": team_entry.get("goalsDiff", 0),
                        "points": team_entry.get("points", 0),
                        "form": team_entry.get("form"),
                        "fetched_at": datetime.utcnow(),
                    })
        upsert_standings(self.session, rows)
        logger.info(f"Standings [{league_id}] saison {season} : {len(rows)} équipes")
        return rows

    # ── Top scorers / assisters ───────────────────────────────────────────────

    def fetch_top_scorers(self, league_id: int, season: int = SEASON) -> list[dict]:
        return self._fetch_players("/players/topscorers", league_id, season)

    def fetch_top_assisters(self, league_id: int, season: int = SEASON) -> list[dict]:
        return self._fetch_players("/players/topassists", league_id, season)

    def _fetch_players(self, endpoint: str, league_id: int, season: int) -> list[dict]:
        data = self._get(endpoint, {"league": league_id, "season": season}, league_id)
        rows = []
        for entry in data.get("response", []):
            player = entry.get("player", {})
            stats_list = entry.get("statistics", [{}])
            stats = stats_list[0] if stats_list else {}
            goals_ = stats.get("goals", {})
            games_ = stats.get("games", {})
            rows.append({
                "api_id": player.get("id", 0),
                "name": player.get("name"),
                "team": (stats.get("team") or {}).get("name"),
                "league_id": league_id,
                "season": season,
                "goals": goals_.get("total") or 0,
                "assists": goals_.get("assists") or 0,
                "matches_played": games_.get("appearences") or 0,
                "minutes": games_.get("minutes") or 0,
                "penalties": (stats.get("penalty") or {}).get("scored") or 0,
                "xg": None,   # Pas dispo dans ce endpoint
                "xa": None,
                "fetched_at": datetime.utcnow(),
            })
        upsert_players(self.session, rows)
        logger.info(f"Players [{endpoint}] ligue {league_id} : {len(rows)} joueurs")
        return rows

    # ── Fixtures (résultats) ──────────────────────────────────────────────────

    def fetch_fixtures(self, league_id: int, season: int = SEASON,
                       last: int | None = None) -> list[dict]:
        """Récupère les résultats terminés."""
        params: dict = {"league": league_id, "season": season, "status": "FT"}
        if last:
            params["last"] = last
        data = self._get("/fixtures", params, league_id)
        rows = []
        for f in data.get("response", []):
            fixture = f.get("fixture", {})
            teams = f.get("teams", {})
            goals = f.get("goals", {})
            league = f.get("league", {})
            score = f.get("score", {}).get("fulltime", {})
            rows.append({
                "id": fixture.get("id"),
                "league_id": league_id,
                "league_name": league.get("name"),
                "season": season,
                "match_date": _parse_date(fixture.get("date")),
                "home_team": teams.get("home", {}).get("name"),
                "away_team": teams.get("away", {}).get("name"),
                "home_goals": score.get("home"),
                "away_goals": score.get("away"),
                "status": "FT",
                "home_xg": None,
                "away_xg": None,
                "home_km": None,
                "away_km": None,
                "fetched_at": datetime.utcnow(),
            })
        upsert_matches(self.session, rows)
        logger.info(f"Fixtures ligue {league_id} : {len(rows)} matchs")
        return rows

    # ── Fixture statistics (xG + distance) ───────────────────────────────────

    def fetch_fixture_stats(self, fixture_id: int, league_id: int,
                            home_team: str, away_team: str, season: int = SEASON):
        """
        Récupère les stats d'un match (xG, distance) et met à jour la DB.
        Coûte 1 requête API par match — à utiliser avec parcimonie.
        """
        data = self._get("/fixtures/statistics", {"fixture": fixture_id}, league_id)
        home_xg = away_xg = home_km = away_km = None

        for team_stats in data.get("response", []):
            team_name = team_stats.get("team", {}).get("name", "")
            stats = {s["type"]: s["value"] for s in team_stats.get("statistics", [])}
            xg = _safe_float(stats.get("expected_goals") or stats.get("Expected Goals"))
            km = _safe_float(stats.get("Distance Covered") or stats.get("distance_covered"))

            # Certaines APIs retournent km * 1000 (en mètres), on normalise en km
            if km and km > 500:
                km = km / 1000.0

            if team_name == home_team or (home_team and home_team in team_name):
                home_xg, home_km = xg, km
            elif team_name == away_team or (away_team and away_team in team_name):
                away_xg, away_km = xg, km

        # Mise à jour du match en DB
        from sqlalchemy import update
        from ..db import Match, engine
        with engine.connect() as conn:
            conn.execute(
                update(Match)
                .where(Match.id == fixture_id)
                .values(home_xg=home_xg, away_xg=away_xg,
                        home_km=home_km, away_km=away_km)
            )
            conn.commit()

        logger.debug(f"  Fixture {fixture_id}: xG {home_xg}/{away_xg}, km {home_km}/{away_km}")
        return home_xg, away_xg, home_km, away_km


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except Exception:
        return None


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
