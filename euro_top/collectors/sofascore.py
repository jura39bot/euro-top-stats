"""
Collecteur xG — Sofascore (API non officielle, lecture seule).

Sofascore expose ses données de match via une API publique non documentée.
Aucune clé API requise. Aucune inscription. Aucun quota officiel.

⚠️  Utilisation raisonnable : préférer Understat pour les xG de saison.
    Sofascore est utile pour les xG/stats d'un match précis en temps réel
    ou quand Understat n'a pas encore mis à jour ses données.

Sources alternatives :
    - Understat  → xG saison courante, top 5 ligues
    - Sofascore  → xG + stats match, toutes compétitions, plus réactif

⚠️  Cette API est non officielle et peut changer sans préavis.
    Ne pas abuser : ajouter un délai entre les requêtes (sleep inclus).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.sofascore.com/api/v1"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# Session persistante (conserve les cookies entre requêtes)
_session = requests.Session()
_session.headers.update(_HEADERS)

# IDs Sofascore pour les tournois (uniqueTournament)
TOURNAMENT_IDS = {
    "ligue1":     34,
    "pl":         17,
    "laliga":     8,
    "seriea":     23,
    "bundesliga": 35,
    "cl":         7,
    "el":         679,
    "ecl":        17015,
}


def _get(url: str, timeout: int = 10) -> Optional[dict]:
    """Requête GET via session persistante (cookies conservés)."""
    try:
        r = _session.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.warning(f"Sofascore GET {url}: {e}")
        return None


# ── Stats d'un match ──────────────────────────────────────────────────────────

def fetch_match_stats(match_id: int) -> Optional[dict]:
    """
    Récupère les statistiques d'un match Sofascore.

    Retourne :
        {
            "home": {"xg": float, "possession": int, "shots": int, ...},
            "away": {"xg": float, ...},
        }
    ou None si indisponible.
    """
    data = _get(f"{_BASE}/event/{match_id}/statistics")
    if not data or "statistics" not in data:
        return None

    result: dict[str, dict] = {"home": {}, "away": {}}

    for period in data["statistics"]:
        if period.get("period") != "ALL":
            continue
        for group in period.get("groups", []):
            for item in group.get("statisticsItems", []):
                key = _normalize_stat_key(item["name"])
                try:
                    result["home"][key] = _parse_stat_value(item.get("home"))
                    result["away"][key] = _parse_stat_value(item.get("away"))
                except Exception:
                    pass

    return result or None


def fetch_match_xg(match_id: int) -> tuple[Optional[float], Optional[float]]:
    """
    Retourne (home_xg, away_xg) depuis Sofascore pour un match donné.
    Retourne (None, None) si indisponible.
    """
    stats = fetch_match_stats(match_id)
    if not stats:
        return None, None
    home_xg = stats["home"].get("expected_goals")
    away_xg = stats["away"].get("expected_goals")
    return home_xg, away_xg


# ── Matchs d'une journée ──────────────────────────────────────────────────────

def fetch_matches_by_date(match_date: date, league_key: str) -> list[dict]:
    """
    Récupère les matchs d'une ligue pour une date donnée.

    Retourne une liste de dicts :
        {id, home_team, away_team, home_goals, away_goals, status, match_date}
    """
    tournament_id = TOURNAMENT_IDS.get(league_key)
    date_str = match_date.strftime("%Y-%m-%d")
    data = _get(f"{_BASE}/sport/football/scheduled-events/{date_str}")
    if not data:
        return []

    results = []
    for event in data.get("events", []):
        ut = event.get("tournament", {}).get("uniqueTournament", {})
        if tournament_id and ut.get("id") != tournament_id:
            continue
        try:
            results.append({
                "id":          event["id"],
                "home_team":   event["homeTeam"]["name"],
                "away_team":   event["awayTeam"]["name"],
                "home_goals":  event.get("homeScore", {}).get("current"),
                "away_goals":  event.get("awayScore", {}).get("current"),
                "status":      event.get("status", {}).get("type"),
                "match_date":  match_date,
            })
        except KeyError:
            continue

    return results


def fetch_round_xg(
    match_ids: list[int],
    delay: float = 0.5,
) -> dict[int, tuple[Optional[float], Optional[float]]]:
    """
    Récupère les xG pour une liste de match IDs Sofascore.

    Args:
        match_ids : Liste d'IDs Sofascore
        delay     : Délai en secondes entre chaque requête (politesse)

    Retourne :
        {match_id: (home_xg, away_xg)}
    """
    results = {}
    for mid in match_ids:
        results[mid] = fetch_match_xg(mid)
        if delay > 0:
            time.sleep(delay)
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_stat_key(name: str) -> str:
    """Normalise les noms de stats Sofascore en snake_case."""
    return (
        name.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("(", "")
        .replace(")", "")
    )


def _parse_stat_value(val: Optional[str]):
    """Parse une valeur de stat Sofascore : '67%', '3.11', '17', None."""
    if val is None:
        return None
    val = str(val).strip()
    if val.endswith("%"):
        try:
            return int(val[:-1])
        except ValueError:
            return val
    try:
        f = float(val)
        return int(f) if f == int(f) else round(f, 4)
    except ValueError:
        return val
