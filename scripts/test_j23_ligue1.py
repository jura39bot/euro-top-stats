#!/usr/bin/env python3
"""
Test collecte J23 Ligue 1 2025-2026.

Sources :
  - Understat  → scores + xG (via understatapi)
  - Sofascore  → stats complémentaires (possession, tirs, corners, xG croisé)

Sortie :
  data/ligue1_j23_2025-26.json
  data/ligue1_j23_2025-26.csv

Usage :
  python3 scripts/test_j23_ligue1.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import csv
import time
import logging
from datetime import date, datetime, timezone

UTC = timezone.utc
from pathlib import Path

from euro_top.collectors.understat import fetch_last_round_xg
from euro_top.collectors.sofascore import (
    fetch_matches_by_date,
    fetch_match_stats,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_j23")

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SEASON = 2025
LEAGUE_KEY = "ligue1"

# Dates de la J23 Ligue 1 2025-2026
J23_DATES = [date(2026, 2, 20), date(2026, 2, 21), date(2026, 2, 22)]

# IDs Sofascore connus pour J23 (collectés manuellement le 2026-02-27)
# Permet d'éviter l'endpoint /scheduled-events si bloqué
KNOWN_SOFASCORE_IDS: dict[str, int] = {
    "Stade Brestois vs Olympique de Marseille": 14167866,
    "RC Lens vs AS Monaco":                     14167892,
    "Toulouse vs Paris FC":                     14167871,
    "Paris Saint-Germain vs Metz":              14167865,
    "Auxerre vs Stade Rennais":                 14167875,
    "Angers vs Lille":                          14167873,
    "Nantes vs Le Havre":                       14167869,
    "Nice vs Lorient":                          14167867,
    "RC Strasbourg vs Olympique Lyonnais":      14064501,
}


def collect_understat() -> list[dict]:
    """Récupère les 9 matchs de la J23 via Understat."""
    logger.info("Understat — récupération J23 Ligue 1 2025-2026…")
    matches = fetch_last_round_xg("Ligue_1", season=SEASON)
    logger.info(f"  → {len(matches)} matchs récupérés")
    return matches


def collect_sofascore_ids() -> dict[str, int]:
    """
    Récupère les IDs Sofascore des matchs J23.
    Tente d'abord l'endpoint /scheduled-events ; en cas de 403,
    repli sur KNOWN_SOFASCORE_IDS.
    """
    logger.info("Sofascore — récupération IDs matchs J23…")
    id_map = {}
    blocked = 0
    for d in J23_DATES:
        events = fetch_matches_by_date(d, LEAGUE_KEY)
        if not events:
            blocked += 1
        for ev in events:
            key = f"{ev['home_team']} vs {ev['away_team']}"
            id_map[key] = ev["id"]
        time.sleep(0.4)

    if blocked == len(J23_DATES) and not id_map:
        logger.warning("Sofascore /scheduled-events bloqué (403) — repli sur IDs connus")
        id_map = dict(KNOWN_SOFASCORE_IDS)

    logger.info(f"  → {len(id_map)} matchs trouvés")
    return id_map


def collect_sofascore_stats(id_map: dict[str, int]) -> dict[int, dict]:
    """Récupère les stats complètes depuis Sofascore pour chaque match."""
    logger.info("Sofascore — récupération stats par match…")
    stats_map = {}
    for key, mid in id_map.items():
        s = fetch_match_stats(mid)
        if s:
            stats_map[mid] = s
            logger.info(f"  ✓ {key} (ID {mid})")
        else:
            logger.warning(f"  ✗ {key} (ID {mid}) — stats non disponibles")
        time.sleep(0.5)
    return stats_map


def _match_sofascore_key(home: str, away: str, id_map: dict) -> int | None:
    """
    Fuzzy match nom équipe Understat → clé Sofascore.
    Understat utilise des noms courts, Sofascore des noms officiels.
    """
    # Correspondances directes Understat → Sofascore
    name_map = {
        "Paris Saint Germain": "Paris Saint-Germain",
        "Brest":               "Stade Brestois",
        "Rennes":              "Stade Rennais",
        "Lyon":                "Olympique Lyonnais",
        "Marseille":           "Olympique de Marseille",
        "Lens":                "RC Lens",
        "Monaco":              "AS Monaco",
        "Strasbourg":          "RC Strasbourg",
    }
    h = name_map.get(home, home)
    a = name_map.get(away, away)

    # Essai exact d'abord
    key = f"{h} vs {a}"
    if key in id_map:
        return id_map[key]

    # Recherche partielle (premier mot)
    for k, v in id_map.items():
        k_h, k_a = k.split(" vs ", 1)
        if h.split()[0] in k_h and a.split()[0] in k_a:
            return v
        if k_h.split()[-1] in h and k_a.split()[-1] in a:
            return v
    return None


def build_dataset(
    understat_matches: list[dict],
    id_map: dict[str, int],
    stats_map: dict[int, dict],
) -> list[dict]:
    """Fusionne les données Understat + Sofascore en un dataset unifié."""
    dataset = []
    for m in understat_matches:
        sid = _match_sofascore_key(m["home_team"], m["away_team"], id_map)
        sfs = stats_map.get(sid, {}) if sid else {}

        # Stats Sofascore (None si non disponibles)
        h_sfs = sfs.get("home", {})
        a_sfs = sfs.get("away", {})

        row = {
            "match_date":   str(m["match_date"]),
            "home_team":    m["home_team"],
            "away_team":    m["away_team"],
            "home_goals":   m["home_goals"],
            "away_goals":   m["away_goals"],
            # xG source principale : Understat
            "home_xg":             m["home_xg"],
            "away_xg":             m["away_xg"],
            # Stats complémentaires : Sofascore
            "home_possession":     h_sfs.get("ball_possession"),
            "away_possession":     a_sfs.get("ball_possession"),
            "home_shots":          h_sfs.get("total_shots"),
            "away_shots":          a_sfs.get("total_shots"),
            "home_shots_on":       h_sfs.get("shots_on_target") or h_sfs.get("shots_on_goal"),
            "away_shots_on":       a_sfs.get("shots_on_target") or a_sfs.get("shots_on_goal"),
            "home_corners":        h_sfs.get("corner_kicks"),
            "away_corners":        a_sfs.get("corner_kicks"),
            "home_fouls":          h_sfs.get("fouls"),
            "away_fouls":          a_sfs.get("fouls"),
            # xG Sofascore (croisement / vérification)
            "home_xg_sofascore":   h_sfs.get("expected_goals"),
            "away_xg_sofascore":   a_sfs.get("expected_goals"),
            # Identifiants sources
            "sofascore_id":        sid,
            "understat_id":        m.get("understat_id"),
            "source_xg":           "understat",
        }
        dataset.append(row)

    # Trier par date
    dataset.sort(key=lambda x: x["match_date"])
    return dataset


def save_json(dataset: list[dict], path: Path):
    payload = {
        "meta": {
            "competition": "Ligue 1",
            "season":      "2025-2026",
            "round":       "J23",
            "dates":       [str(d) for d in J23_DATES],
            "sources":     ["understat.com", "sofascore.com"],
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "matches":     len(dataset),
        },
        "matches": dataset,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    logger.info(f"JSON → {path}")


def save_csv(dataset: list[dict], path: Path):
    if not dataset:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=dataset[0].keys())
        writer.writeheader()
        writer.writerows(dataset)
    logger.info(f"CSV  → {path}")


def print_summary(dataset: list[dict]):
    print("\n" + "=" * 70)
    print(f"  🇫🇷 Ligue 1 — J23 (2025-2026)  |  {len(dataset)} matchs")
    print("=" * 70)
    fmt = "{:<25} {:>2} - {:<2} {:<25}  xG {:.2f} – {:.2f}"
    for m in dataset:
        print(fmt.format(
            m["home_team"], m["home_goals"] or 0, m["away_goals"] or 0,
            m["away_team"], m["home_xg"] or 0, m["away_xg"] or 0,
        ))
        if m.get("home_possession") is not None:
            print(f"  {'Possession':12} {m['home_possession']}% / {m['away_possession']}% "
                  f"| Tirs {m['home_shots']} / {m['away_shots']} "
                  f"| Corners {m['home_corners']} / {m['away_corners']}")
    print()


def main():
    logger.info("=== Test collecte J23 Ligue 1 2025-2026 ===")

    # 1. Understat (scores + xG)
    understat_matches = collect_understat()
    if not understat_matches:
        logger.error("Understat : aucun match récupéré. Abandon.")
        sys.exit(1)

    # 2. Sofascore (IDs + stats)
    id_map = collect_sofascore_ids()
    stats_map = collect_sofascore_stats(id_map)

    # 3. Fusion
    dataset = build_dataset(understat_matches, id_map, stats_map)

    # 4. Affichage
    print_summary(dataset)

    # 5. Export
    save_json(dataset, DATA_DIR / "ligue1_j23_2025-26.json")
    save_csv(dataset,  DATA_DIR / "ligue1_j23_2025-26.csv")

    logger.info("Collecte terminée ✅")


if __name__ == "__main__":
    main()
