"""
Collecteur xG — Understat.com via understatapi.

Understat fournit les xG par match pour les top 5 ligues européennes,
saison courante incluse (2025-2026).

Source : https://understat.com  |  Lib : https://pypi.org/project/understatapi/

Installation :
    pip install understatapi

Pas de clé API requise. Pas de quota. 100 % gratuit.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from ..config import SEASON
from ..db import Session, upsert_matches

logger = logging.getLogger(__name__)

# Mapping slug understat → slug understatapi (identiques sauf casse)
# Understat slugs : Ligue_1, EPL, La_liga, Serie_A, Bundesliga, RFPL
UNDERSTAT_LEAGUES = {
    "Ligue_1",
    "EPL",
    "La_liga",
    "Serie_A",
    "Bundesliga",
}


# ── Client understatapi ───────────────────────────────────────────────────────

def _get_client():
    """Retourne un UnderstatClient (synchrone)."""
    try:
        from understatapi import UnderstatClient
        return UnderstatClient()
    except ImportError as e:
        raise ImportError(
            "Installe understatapi : pip install understatapi"
        ) from e


def fetch_league_xg(
    understat_slug: str,
    season: int = SEASON,
    session: Optional[Session] = None,
) -> list[dict]:
    """
    Récupère les xG de tous les matchs terminés d'une ligue/saison.

    Retourne une liste de dicts :
        {home_team, away_team, home_goals, away_goals,
         home_xg, away_xg, home_npxg, away_npxg, match_date}

    Args:
        understat_slug : Ex. "Ligue_1", "EPL", "La_liga"
        season         : Année de début de saison (ex. 2025 pour 2025-2026)
        session        : Session SQLAlchemy optionnelle pour upsert en DB
    """
    if understat_slug not in UNDERSTAT_LEAGUES:
        logger.warning(
            f"Understat : slug '{understat_slug}' inconnu. "
            f"Slugs valides : {', '.join(UNDERSTAT_LEAGUES)}"
        )
        return []

    logger.info(f"Understat [{understat_slug} {season}] : récupération matchs xG…")

    try:
        with _get_client() as understat:
            raw_matches = understat.league(league=understat_slug).get_match_data(
                season=str(season)
            )
    except Exception as e:
        logger.error(f"Understat [{understat_slug}]: erreur réseau : {e}")
        return []

    results = []
    for m in raw_matches:
        if not m.get("isResult"):
            continue
        try:
            row = {
                "home_team":  m["h"]["title"],
                "away_team":  m["a"]["title"],
                "home_goals": _safe_int(m.get("goals", {}).get("h")),
                "away_goals": _safe_int(m.get("goals", {}).get("a")),
                "home_xg":    _safe_float(m.get("xG", {}).get("h")),
                "away_xg":    _safe_float(m.get("xG", {}).get("a")),
                "home_npxg":  _safe_float(m.get("npxG", {}).get("h")),
                "away_npxg":  _safe_float(m.get("npxG", {}).get("a")),
                "match_date": _parse_date(m.get("datetime")),
                "understat_id": m.get("id"),
            }
            results.append(row)
        except (KeyError, TypeError):
            continue

    logger.info(f"Understat [{understat_slug} {season}] : {len(results)} matchs récupérés")

    if session and results:
        upsert_matches(session, results)

    return results


def fetch_last_round_xg(
    understat_slug: str,
    season: int = SEASON,
    session: Optional[Session] = None,
) -> list[dict]:
    """
    Retourne les matchs de la dernière journée jouée (regroupés par date(s) proches).

    Understat ne numérote pas les journées : on groupe les matchs par date
    et on prend le cluster de dates le plus récent (fenêtre de 4 jours max).
    """
    all_matches = fetch_league_xg(understat_slug, season, session)
    if not all_matches:
        return []

    # Trouver la date la plus récente
    dated = [m for m in all_matches if m.get("match_date")]
    if not dated:
        return []

    latest = max(m["match_date"] for m in dated)

    # Regrouper les matchs dans une fenêtre de 4 jours autour de la dernière date
    from datetime import timedelta
    cutoff = latest - timedelta(days=4)
    last_round = [m for m in dated if m["match_date"] >= cutoff]

    logger.info(
        f"Understat [{understat_slug}] dernière journée : "
        f"{len(last_round)} matchs autour du {latest}"
    )
    return last_round


def fetch_team_xg_season(
    understat_slug: str,
    season: int = SEASON,
) -> list[dict]:
    """
    Retourne les xG cumulés par équipe sur la saison.

    Retourne une liste triée par (xG_for - xG_against) DESC :
        {team, matches, xg_for, xg_against, xg_diff, npxg_for, npxg_against}
    """
    all_matches = fetch_league_xg(understat_slug, season)
    if not all_matches:
        return []

    teams: dict[str, dict] = {}

    def _add(name, xg_for, xg_against, npxg_for, npxg_against):
        if name not in teams:
            teams[name] = {
                "team": name, "matches": 0,
                "xg_for": 0.0, "xg_against": 0.0,
                "npxg_for": 0.0, "npxg_against": 0.0,
            }
        t = teams[name]
        t["matches"] += 1
        t["xg_for"]      += xg_for or 0
        t["xg_against"]  += xg_against or 0
        t["npxg_for"]    += npxg_for or 0
        t["npxg_against"] += npxg_against or 0

    for m in all_matches:
        _add(m["home_team"], m["home_xg"], m["away_xg"], m["home_npxg"], m["away_npxg"])
        _add(m["away_team"], m["away_xg"], m["home_xg"], m["away_npxg"], m["home_npxg"])

    result = sorted(
        teams.values(),
        key=lambda t: t["xg_for"] - t["xg_against"],
        reverse=True,
    )
    for i, t in enumerate(result, 1):
        t["rank"] = i
        t["xg_diff"] = round(t["xg_for"] - t["xg_against"], 2)
        t["xg_for"] = round(t["xg_for"], 2)
        t["xg_against"] = round(t["xg_against"], 2)
        t["npxg_for"] = round(t["npxg_for"], 2)
        t["npxg_against"] = round(t["npxg_against"], 2)

    return result


# ── Fonctions legacy (conservées pour compatibilité) ─────────────────────────

def scrape_league_xg(
    understat_slug: str,
    league_id: int,
    season: int = SEASON,
    session: Optional[Session] = None,
) -> list[dict]:
    """Alias legacy — utilise fetch_league_xg en interne."""
    return fetch_league_xg(understat_slug, season, session)


def scrape_player_xg(understat_slug: str, season: int = SEASON) -> list[dict]:
    """xG joueur par match depuis Understat."""
    logger.info(f"Understat [{understat_slug} {season}] : récupération xG joueurs…")
    try:
        with _get_client() as understat:
            data = understat.league(league=understat_slug).get_player_data(
                season=str(season)
            )
        players = []
        for player_id, info in data.items():
            h = info.get("history", [])
            for match in h:
                players.append({
                    "player_id": player_id,
                    "player_name": info.get("player_name"),
                    "team": info.get("team_title"),
                    "xg": _safe_float(match.get("xG")),
                    "xa": _safe_float(match.get("xA")),
                    "goals": _safe_int(match.get("goals")),
                    "assists": _safe_int(match.get("assists")),
                    "match_date": _parse_date(match.get("date")),
                    "minutes": _safe_int(match.get("time")),
                })
        return players
    except Exception as e:
        logger.error(f"Understat player xG [{understat_slug}]: {e}")
        return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str[:19], fmt).date()
        except ValueError:
            continue
    return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return None
