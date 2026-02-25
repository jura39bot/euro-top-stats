"""Configuration des ligues et paramètres globaux."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
API_FOOTBALL_BASE = "https://v3.football-api-sports.io"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./euro_top.db")
SEASON = int(os.getenv("SEASON", "2024"))

# Limite journalière API-Football (free = 100, on prend de la marge)
API_DAILY_LIMIT = 90


@dataclass
class League:
    id: int          # ID API-Football
    name: str        # Nom officiel
    short: str       # Code court CLI
    aliases: list    # Aliases acceptés en CLI
    flag: str        # Emoji drapeau
    country: str
    understat_slug: str | None = None  # Pour scraping xG understat


LEAGUES: dict[str, League] = {
    "ligue1": League(
        id=61, name="Ligue 1", short="ligue1",
        aliases=["fr", "france", "l1", "ligue-1"],
        flag="🇫🇷", country="France",
        understat_slug="Ligue_1",
    ),
    "pl": League(
        id=39, name="Premier League", short="pl",
        aliases=["premier-league", "premier_league", "en", "england", "epl"],
        flag="🏴󠁧󠁢󠁥󠁮󠁧󠁿", country="England",
        understat_slug="EPL",
    ),
    "laliga": League(
        id=140, name="La Liga", short="laliga",
        aliases=["es", "spain", "espagne", "la-liga", "la_liga"],
        flag="🇪🇸", country="Spain",
        understat_slug="La_liga",
    ),
    "seriea": League(
        id=135, name="Serie A", short="seriea",
        aliases=["it", "italy", "italie", "serie-a", "serie_a"],
        flag="🇮🇹", country="Italy",
        understat_slug="Serie_A",
    ),
    "bundesliga": League(
        id=78, name="Bundesliga", short="bundesliga",
        aliases=["de", "germany", "allemagne", "buli"],
        flag="🇩🇪", country="Germany",
        understat_slug="Bundesliga",
    ),
    "cl": League(
        id=2, name="Champions League", short="cl",
        aliases=["champions-league", "champions_league", "ucl", "ldc"],
        flag="🏆", country="Europe",
    ),
    "el": League(
        id=3, name="Europa League", short="el",
        aliases=["europa-league", "europa_league", "uel", "lue"],
        flag="🟠", country="Europe",
    ),
    "ecl": League(
        id=848, name="Conference League", short="ecl",
        aliases=["conference-league", "conference_league", "uecl", "conference"],
        flag="⚪", country="Europe",
    ),
}

# Lookup rapide par alias
_ALIAS_MAP: dict[str, str] = {}
for key, league in LEAGUES.items():
    _ALIAS_MAP[key] = key
    _ALIAS_MAP[league.short] = key
    for alias in league.aliases:
        _ALIAS_MAP[alias] = key


def resolve_league(name: str) -> League | None:
    """Résout un nom/alias de ligue vers l'objet League."""
    key = _ALIAS_MAP.get(name.lower().replace(" ", "-"))
    return LEAGUES.get(key) if key else None


def all_leagues() -> list[League]:
    return list(LEAGUES.values())


def domestic_leagues() -> list[League]:
    return [l for l in LEAGUES.values() if l.understat_slug]


def european_leagues() -> list[League]:
    return [l for l in LEAGUES.values() if not l.understat_slug]
