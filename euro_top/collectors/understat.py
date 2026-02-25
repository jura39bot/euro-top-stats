"""
Collecteur xG alternatif — plusieurs sources tentées.

Understat.com a migré ses données vers un rendu JS dynamique (mars 2026),
le scraping statique ne fonctionne plus.

Sources utilisées ici :
1. football-data.co.uk — CSV gratuits (résultats + stats de base, pas de xG)
2. API-Football /fixtures/statistics — xG par match (via api_football.py, 1 req/match)
3. Stub understat conservé pour compatibilité future (ex: ajout selenium)

Pour les xG riches, utiliser :
    euro-top collect --stats --last 10
(appelle API-Football /fixtures/statistics)
"""
from __future__ import annotations
import csv
import io
import logging
import time
from datetime import date, datetime
from typing import Optional

import requests

from ..config import SEASON
from ..db import Session, upsert_matches

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── football-data.co.uk ───────────────────────────────────────────────────────
# CSV gratuits (pas de xG, mais stats complètes : tirs, corners, fautes…)

FDCO_URLS: dict[str, dict[int, str]] = {
    "Ligue_1": {
        2024: "https://www.football-data.co.uk/mmz4281/2425/F1.csv",
        2023: "https://www.football-data.co.uk/mmz4281/2324/F1.csv",
    },
    "EPL": {
        2024: "https://www.football-data.co.uk/mmz4281/2425/E0.csv",
        2023: "https://www.football-data.co.uk/mmz4281/2324/E0.csv",
    },
    "La_liga": {
        2024: "https://www.football-data.co.uk/mmz4281/2425/SP1.csv",
        2023: "https://www.football-data.co.uk/mmz4281/2324/SP1.csv",
    },
    "Serie_A": {
        2024: "https://www.football-data.co.uk/mmz4281/2425/I1.csv",
        2023: "https://www.football-data.co.uk/mmz4281/2324/I1.csv",
    },
    "Bundesliga": {
        2024: "https://www.football-data.co.uk/mmz4281/2425/D1.csv",
        2023: "https://www.football-data.co.uk/mmz4281/2324/D1.csv",
    },
}


def fetch_fdco_matches(
    understat_slug: str,
    league_id: int,
    season: int = SEASON,
    session: Optional[Session] = None,
) -> list[dict]:
    """
    Télécharge les résultats depuis football-data.co.uk (CSV).
    Enrichit la DB avec les stats de base (pas de xG natif).
    
    Colonnes CSV utiles : HomeTeam, AwayTeam, FTHG, FTAG, Date,
    HS (Home Shots), AS (Away Shots), HST, AST, HC, AC…
    """
    urls = FDCO_URLS.get(understat_slug, {})
    url = urls.get(season)
    if not url:
        logger.info(f"football-data.co.uk: pas d'URL pour {understat_slug} {season}")
        return []

    logger.info(f"football-data.co.uk [{understat_slug} {season}]: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Erreur téléchargement FDCO: {e}")
        return []

    # Décoder le CSV (BOM UTF-8 possible)
    content = resp.content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))

    results = []
    for row in reader:
        if not row.get("HomeTeam") or not row.get("FTHG"):
            continue
        try:
            match_date = _parse_date_fdco(row.get("Date", ""))
            results.append({
                "home_team": row["HomeTeam"],
                "away_team": row["AwayTeam"],
                "home_goals": _int(row.get("FTHG")),
                "away_goals": _int(row.get("FTAG")),
                "match_date": match_date,
                "home_shots": _int(row.get("HS")),
                "away_shots": _int(row.get("AS")),
            })
        except Exception:
            continue

    logger.info(f"football-data.co.uk: {len(results)} matchs lus")
    return results


# ── Stub Understat (conservé pour compatibilité) ──────────────────────────────

def scrape_league_xg(
    understat_slug: str,
    league_id: int,
    season: int = SEASON,
    session: Optional[Session] = None,
) -> list[dict]:
    """
    Tente de scraper les xG depuis understat.com.
    
    ⚠️  Understat a migré vers un rendu JS dynamique (mars 2026).
    Cette fonction retourne [] si les données ne sont plus disponibles
    statiquement. Pour les xG, utiliser :
        euro-top collect --stats --last 10
    (API-Football /fixtures/statistics)
    """
    logger.info(f"xG [{understat_slug} {season}]: tentative understat.com…")

    try:
        import re, json
        resp = requests.get(
            f"https://understat.com/league/{understat_slug}/{season}",
            headers=HEADERS, timeout=20
        )
        resp.raise_for_status()

        # Chercher le JSON embarqué (ancien format)
        for var_name in ["datesData", "matchesData"]:
            pattern = rf"var\s+{var_name}\s*=\s*JSON\.parse\('(.+?)'\)"
            m = re.search(pattern, resp.text, re.DOTALL)
            if m:
                raw = m.group(1).encode().decode("unicode_escape")
                data = json.loads(raw)
                results = _parse_understat_matches(data, league_id, session, season)
                logger.info(f"Understat [{understat_slug}]: {len(results)} matchs avec xG")
                return results

        logger.warning(
            f"Understat [{understat_slug}]: données non disponibles statiquement. "
            "Utilise --stats pour les xG via API-Football."
        )
    except Exception as e:
        logger.warning(f"Understat [{understat_slug}]: {e}")

    return []


def scrape_player_xg(understat_slug: str, season: int = SEASON) -> list[dict]:
    """Scrape xG joueurs depuis understat (nécessite rendu JS — retourne [] si indisponible)."""
    logger.warning("scrape_player_xg: understat utilise JS dynamique, données non disponibles.")
    return []


def _parse_understat_matches(
    data: list,
    league_id: int,
    session: Optional[Session],
    season: int,
) -> list[dict]:
    """Parse le JSON datesData d'understat (ancien format)."""
    results = []
    for match in data:
        try:
            home_xg = _float(match.get("xG", {}).get("h"))
            away_xg = _float(match.get("xG", {}).get("a"))
            if home_xg is None or away_xg is None:
                continue
            results.append({
                "home_team": match.get("h", {}).get("title"),
                "away_team": match.get("a", {}).get("title"),
                "home_xg": home_xg,
                "away_xg": away_xg,
                "match_date": _parse_date_understat(match.get("datetime")),
            })
        except Exception:
            continue
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date_fdco(date_str: str) -> Optional[date]:
    """Parse les dates football-data.co.uk : DD/MM/YY ou DD/MM/YYYY."""
    if not date_str:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _parse_date_understat(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").date()
    except Exception:
        return None


def _int(val) -> Optional[int]:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _float(val) -> Optional[float]:
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None
