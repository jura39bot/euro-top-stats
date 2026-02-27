#!/usr/bin/env python3
"""
Collecte + export + git push des données pour une ou plusieurs ligues.

Usage :
  python3 scripts/push_data.py --leagues ligue1 pl laliga seriea bundesliga
  python3 scripts/push_data.py --leagues cl
  python3 scripts/push_data.py --leagues el ecl

Sortie par ligue :
  data/<league>_latest.json   dernière journée avec xG
  data/<league>_latest.csv    même dataset au format tabulaire

Le script commit + push automatiquement sur origin/master.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import csv
import json
import logging
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("push_data")

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

REPO_DIR = Path(__file__).parent.parent

# Ligues domestiques couvertes par Understat (xG gratuit, saison courante)
UNDERSTAT_LEAGUES = {"ligue1", "pl", "laliga", "seriea", "bundesliga"}

# Ligues européennes — API-Football saison 2024 (free plan bloqué sur 2025)
EUROPEAN_LEAGUES = {"cl", "el", "ecl"}


# ── Collecte domestique via Understat ─────────────────────────────────────────

def collect_domestic(league_key: str) -> list[dict]:
    """Récupère la dernière journée jouée d'une ligue domestique via Understat."""
    from euro_top.config import resolve_league
    from euro_top.collectors.understat import fetch_last_round_xg

    league = resolve_league(league_key)
    if not league or not league.understat_slug:
        logger.error(f"Ligue domestique inconnue ou sans slug Understat : {league_key}")
        return []

    logger.info(f"{league.flag} {league.name} — collecte Understat saison 2025…")
    matches = fetch_last_round_xg(league.understat_slug, season=2025)

    if not matches:
        logger.warning(f"  Aucun match trouvé pour {league.name}")
        return []

    last_date = max(m["match_date"] for m in matches if m.get("match_date"))
    logger.info(f"  → {len(matches)} matchs | dernière journée autour du {last_date}")

    rows = []
    for m in sorted(matches, key=lambda x: x.get("match_date") or date.min):
        rows.append({
            "competition":  league.name,
            "season":       "2025-2026",
            "match_date":   str(m["match_date"]),
            "home_team":    m["home_team"],
            "away_team":    m["away_team"],
            "home_goals":   m["home_goals"],
            "away_goals":   m["away_goals"],
            "home_xg":      m["home_xg"],
            "away_xg":      m["away_xg"],
            "source_xg":    "understat",
            "understat_id": m.get("understat_id"),
        })

    # Affichage console
    _print_round(league.flag, league.name, rows)
    return rows


# ── Collecte européenne via API-Football ─────────────────────────────────────

def collect_european(league_key: str) -> list[dict]:
    """
    Récupère les derniers matchs d'une compétition européenne via API-Football.
    ⚠️ Plan free : saison 2024 uniquement (2024-2025).
    """
    from euro_top.config import resolve_league
    from euro_top.db import init_db, get_session
    from euro_top.collectors.api_football import ApiFootballClient, RateLimitError

    league = resolve_league(league_key)
    if not league:
        logger.error(f"Ligue inconnue : {league_key}")
        return []

    logger.info(f"{league.flag} {league.name} — collecte API-Football saison 2024…")

    init_db()
    db = get_session()
    client = ApiFootballClient(db)

    try:
        fixtures = client.fetch_fixtures(league.id, season=2024, last=10)
    except RateLimitError as e:
        logger.error(f"  Quota API atteint : {e}")
        return []
    except Exception as e:
        logger.error(f"  Erreur API-Football [{league.name}]: {e}")
        return []
    finally:
        client.close()
        db.close()

    if not fixtures:
        logger.warning(f"  Aucun match trouvé pour {league.name}")
        return []

    # Grouper par date et prendre les plus récents
    last_date = max(f["match_date"] for f in fixtures if f.get("match_date"))
    cutoff = last_date - timedelta(days=5)
    recent = [f for f in fixtures if f.get("match_date") and f["match_date"] >= cutoff]

    logger.info(f"  → {len(recent)} matchs | dernière journée autour du {last_date}")
    logger.warning(f"  ⚠️  Données saison 2024-2025 (plan free bloqué sur saison courante)")

    rows = []
    for f in sorted(recent, key=lambda x: x.get("match_date") or date.min):
        rows.append({
            "competition":  league.name,
            "season":       "2024-2025 (plan free)",
            "match_date":   str(f["match_date"]),
            "home_team":    f["home_team"],
            "away_team":    f["away_team"],
            "home_goals":   f["home_goals"],
            "away_goals":   f["away_goals"],
            "home_xg":      f.get("home_xg"),
            "away_xg":      f.get("away_xg"),
            "source_xg":    "api-football",
            "understat_id": None,
        })

    _print_round(league.flag, league.name, rows)
    return rows


# ── Export ────────────────────────────────────────────────────────────────────

def export(league_key: str, rows: list[dict]):
    """Exporte JSON + CSV pour une ligue."""
    if not rows:
        return

    from euro_top.config import resolve_league
    league = resolve_league(league_key)
    flag = league.flag if league else ""

    payload = {
        "meta": {
            "competition":  rows[0]["competition"],
            "season":       rows[0]["season"],
            "matches":      len(rows),
            "source_xg":    rows[0].get("source_xg", "understat"),
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "matches": rows,
    }

    json_path = DATA_DIR / f"{league_key}_latest.json"
    csv_path  = DATA_DIR / f"{league_key}_latest.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"  {flag} Exporté → {json_path.name} + {csv_path.name}")


# ── Git push ──────────────────────────────────────────────────────────────────

def git_push(league_keys: list[str], generated_at: str):
    """Commit + push les fichiers data/ modifiés."""
    logger.info("Git — commit + push…")

    # S'assurer qu'on est à jour avec le remote
    result = subprocess.run(
        ["git", "-C", str(REPO_DIR), "pull", "--rebase", "origin", "master"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        logger.warning(f"  git pull: {result.stderr.strip()}")

    # Ajouter les fichiers data/
    subprocess.run(
        ["git", "-C", str(REPO_DIR), "add", "data/"],
        check=True
    )

    # Vérifier s'il y a des changements
    status = subprocess.run(
        ["git", "-C", str(REPO_DIR), "diff", "--cached", "--stat"],
        capture_output=True, text=True
    )
    if not status.stdout.strip():
        logger.info("  Aucune modification — rien à committer")
        return

    leagues_str = " + ".join(league_keys)
    msg = (
        f"data: collecte automatique [{leagues_str}] — {generated_at}\n\n"
        f"Ligues : {leagues_str}\n"
        f"Fichiers : " + ", ".join(f"{k}_latest.{{json,csv}}" for k in league_keys)
    )

    subprocess.run(
        ["git", "-C", str(REPO_DIR), "commit", "-m", msg],
        check=True
    )
    result = subprocess.run(
        ["git", "-C", str(REPO_DIR), "push", "origin", "master"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        sha = subprocess.run(
            ["git", "-C", str(REPO_DIR), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True
        ).stdout.strip()
        logger.info(f"  ✅ Pushé — {sha}")
    else:
        logger.error(f"  ❌ git push échoué : {result.stderr.strip()}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_round(flag: str, name: str, rows: list[dict]):
    """Affiche les matchs en console."""
    if not rows:
        return
    print(f"\n{flag} {name} — {rows[0]['season']}")
    print("-" * 65)
    for r in rows:
        xg_str = ""
        if r.get("home_xg") is not None:
            xg_str = f"  xG {r['home_xg']:.2f}–{r['away_xg']:.2f}"
        print(f"  {r['home_team']:<22} {r['home_goals'] or 0}-{r['away_goals'] or 0}"
              f"  {r['away_team']:<22}{xg_str}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Collecte + export + push données football"
    )
    parser.add_argument(
        "--leagues", nargs="+", required=True,
        help="Codes ligues : ligue1 pl laliga seriea bundesliga cl el ecl"
    )
    parser.add_argument(
        "--no-push", action="store_true",
        help="Collecter et exporter sans git push"
    )
    args = parser.parse_args()

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    logger.info(f"=== Collecte [{' '.join(args.leagues)}] — {generated_at} ===")

    collected = []

    for key in args.leagues:
        try:
            if key in UNDERSTAT_LEAGUES:
                rows = collect_domestic(key)
            elif key in EUROPEAN_LEAGUES:
                rows = collect_european(key)
            else:
                logger.error(f"Ligue inconnue : {key}. "
                             "Valides : ligue1 pl laliga seriea bundesliga cl el ecl")
                continue

            if rows:
                export(key, rows)
                collected.append(key)
            else:
                logger.warning(f"  Aucune donnée pour {key} — pas d'export")

        except Exception as e:
            logger.error(f"Erreur [{key}]: {e}", exc_info=True)
            continue

        time.sleep(1)  # Politesse entre ligues

    if collected and not args.no_push:
        git_push(collected, generated_at)
    elif not collected:
        logger.warning("Aucune ligue collectée avec succès.")
    else:
        logger.info("--no-push : git push ignoré")

    logger.info(f"=== Terminé : {len(collected)}/{len(args.leagues)} ligues ===")


if __name__ == "__main__":
    main()
