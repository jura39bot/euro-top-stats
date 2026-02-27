#!/usr/bin/env python3
"""
Détection de value bets — xG Understat × cotes The Odds API.

Principe :
  1. Calcul des probabilités de victoire estimées via xG cumulé de la saison
     (forme récente sur les N derniers matchs par équipe)
  2. Récupération des cotes pré-match The Odds API (marchés à venir)
  3. Comparaison : si P(xG) > P(implicite bookmaker) + seuil → VALUE BET

Usage :
  python3 scripts/value_bets.py --league ligue1
  python3 scripts/value_bets.py --league ligue1 pl --min-value 5
  python3 scripts/value_bets.py --league ligue1 --last 10 --min-value 3 --export

⚠️  Ceci est un outil d'analyse, pas un conseil de pari.
    Les marchés intègrent déjà le xG — la valeur réelle peut être faible.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from euro_top.config import resolve_league, ODDS_API_KEY
from euro_top.collectors.understat import fetch_league_xg
from euro_top.collectors.odds import OddsClient, parse_h2h, implied_to_fair

logging.basicConfig(
    level=logging.WARNING,  # Silencieux par défaut
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("value_bets")
console = Console()

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Ligues couvertes par Understat (xG saison courante)
UNDERSTAT_LEAGUES = {"ligue1", "pl", "laliga", "seriea", "bundesliga"}


# ── Estimation des probabilités via xG ────────────────────────────────────────

def compute_team_xg_probs(
    matches: list[dict],
    last_n: int = 10,
) -> dict[str, dict]:
    """
    Calcule, pour chaque équipe, la probabilité de gagner / nul / perdre
    basée sur le xG moyen des N derniers matchs.

    Modèle simplifié (Dixon-Coles-like) :
      - λ_home = xG moyen offensif domicile × facteur défense adverse
      - Probabilités via distribution de Poisson approximée

    Retourne :
        {team_name: {xg_for, xg_against, matches, win_rate_xg, ...}}
    """
    # Construire historique par équipe (triés par date)
    history: dict[str, list[dict]] = defaultdict(list)
    for m in sorted(matches, key=lambda x: x.get("match_date") or ""):
        if m.get("home_xg") is None:
            continue
        history[m["home_team"]].append({
            "xg_for":     m["home_xg"],
            "xg_against": m["away_xg"],
            "is_home":    True,
            "date":       m.get("match_date"),
        })
        history[m["away_team"]].append({
            "xg_for":     m["away_xg"],
            "xg_against": m["home_xg"],
            "is_home":    False,
            "date":       m.get("match_date"),
        })

    team_stats = {}
    for team, games in history.items():
        recent = games[-last_n:]
        n = len(recent)
        if n == 0:
            continue
        xg_for     = sum(g["xg_for"]     for g in recent) / n
        xg_against = sum(g["xg_against"] for g in recent) / n
        team_stats[team] = {
            "xg_for":     round(xg_for, 3),
            "xg_against": round(xg_against, 3),
            "matches":    n,
        }
    return team_stats


def xg_to_prob(
    home_xg_for: float,
    home_xg_against: float,
    away_xg_for: float,
    away_xg_against: float,
    home_advantage: float = 0.10,
) -> tuple[float, float, float]:
    """
    Estime P(home_win), P(draw), P(away_win) via xG moyen des deux équipes.

    Combine les stats de chaque équipe (attaque × défense adverse)
    avec un facteur d'avantage domicile.

    Approximation Poisson (pas un modèle précis, base de travail).
    """
    import math

    # Lambda attendus
    lam_home = ((home_xg_for + away_xg_against) / 2) * (1 + home_advantage)
    lam_away = ((away_xg_for + home_xg_against) / 2) * (1 - home_advantage * 0.5)

    # P(home=i buts, away=j buts) via Poisson, i,j ∈ [0..6]
    max_goals = 7
    p_home_win = p_draw = p_away_win = 0.0

    def poisson_pmf(lam: float, k: int) -> float:
        return (lam ** k) * math.exp(-lam) / math.factorial(k)

    for i in range(max_goals):
        for j in range(max_goals):
            p = poisson_pmf(lam_home, i) * poisson_pmf(lam_away, j)
            if i > j:
                p_home_win += p
            elif i == j:
                p_draw += p
            else:
                p_away_win += p

    # Normaliser (Poisson tronqué perd un peu de masse)
    total = p_home_win + p_draw + p_away_win
    return p_home_win / total, p_draw / total, p_away_win / total


# ── Value bets ─────────────────────────────────────────────────────────────────

def find_value_bets(
    odds_events: list[dict],
    team_stats: dict[str, dict],
    min_value_pct: float = 3.0,
    last_n: int = 10,
) -> list[dict]:
    """
    Compare probabilités xG vs probabilités implicites des bookmakers.

    Retourne la liste des value bets détectés, triés par value décroissante.
    """
    results = []

    for event in odds_events:
        h2h = parse_h2h(event)
        if not h2h:
            continue

        home = h2h["home_team"]
        away = h2h["away_team"]

        # Chercher les stats xG (fuzzy match nom)
        home_stats = _find_team(home, team_stats)
        away_stats = _find_team(away, team_stats)

        if not home_stats or not away_stats:
            logger.debug(f"Stats xG manquantes : {home} / {away}")
            continue

        # Probabilités estimées via xG (modèle Poisson)
        p_home, p_draw, p_away = xg_to_prob(
            home_stats["xg_for"],  home_stats["xg_against"],
            away_stats["xg_for"],  away_stats["xg_against"],
        )

        # Probabilités implicites des cotes (marge supprimée)
        if not h2h.get("best_home_odds"):
            continue
        fair_home, fair_draw, fair_away = implied_to_fair(
            h2h["best_home_odds"],
            h2h["best_draw_odds"],
            h2h["best_away_odds"],
        )

        # Calcul de la value pour chaque issue
        bets = []
        for outcome, p_model, p_fair, best_odds, best_book in [
            ("home", p_home, fair_home, h2h["best_home_odds"], h2h["best_home_book"]),
            ("draw", p_draw, fair_draw, h2h["best_draw_odds"], h2h["best_draw_book"]),
            ("away", p_away, fair_away, h2h["best_away_odds"], h2h["best_away_book"]),
        ]:
            if not best_odds:
                continue
            value_pct = (p_model - p_fair) * 100
            ev = p_model * best_odds - 1  # Espérance de valeur (mise = 1)

            if value_pct >= min_value_pct:
                bets.append({
                    "outcome":    outcome,
                    "value_pct":  round(value_pct, 2),
                    "ev":         round(ev, 4),
                    "p_model":    round(p_model * 100, 1),
                    "p_implied":  round(p_fair * 100, 1),
                    "best_odds":  best_odds,
                    "best_book":  best_book,
                })

        if not bets:
            continue

        commence = h2h.get("commence_time", "")
        try:
            dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            match_time = dt.strftime("%a %d/%m %H:%M")
        except Exception:
            match_time = commence[:16] if commence else "?"

        results.append({
            "home":          home,
            "away":          away,
            "match_time":    match_time,
            "home_xg_for":   home_stats["xg_for"],
            "away_xg_for":   away_stats["xg_for"],
            "p_home":        round(p_home * 100, 1),
            "p_draw":        round(p_draw * 100, 1),
            "p_away":        round(p_away * 100, 1),
            "margin_pct":    h2h.get("market_margin_pct"),
            "books_count":   h2h.get("bookmakers_count"),
            "value_bets":    sorted(bets, key=lambda b: -b["value_pct"]),
            # Toutes les cotes pour référence
            "best_home_odds": h2h["best_home_odds"],
            "best_draw_odds": h2h["best_draw_odds"],
            "best_away_odds": h2h["best_away_odds"],
        })

    return sorted(results, key=lambda r: -r["value_bets"][0]["value_pct"])


def _find_team(name: str, stats: dict[str, dict]) -> dict | None:
    """Fuzzy match nom d'équipe entre Odds API et Understat."""
    if name in stats:
        return stats[name]
    name_l = name.lower()
    for k, v in stats.items():
        k_l = k.lower()
        if k_l in name_l or name_l in k_l:
            return v
        # Match sur premier mot (ex. "Paris Saint-Germain" vs "Paris Saint Germain")
        if k_l.split()[0] == name_l.split()[0]:
            return v
    return None


# ── Affichage ──────────────────────────────────────────────────────────────────

def print_value_table(league_key: str, results: list[dict], last_n: int):
    from euro_top.config import resolve_league
    league = resolve_league(league_key)
    flag = league.flag if league else ""
    name = league.name if league else league_key

    if not results:
        console.print(
            f"\n{flag} [bold]{name}[/bold] — Aucun value bet détecté\n",
            style="dim"
        )
        return

    console.print(
        f"\n{flag} [bold]{name}[/bold] — Value bets "
        f"(modèle xG {last_n} derniers matchs)\n"
    )

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    table.add_column("Match",       min_width=30)
    table.add_column("Date",        width=14)
    table.add_column("Issue",       width=6)
    table.add_column("Cote",        width=6, justify="right")
    table.add_column("Book",        width=12)
    table.add_column("P(xG)",       width=7, justify="right")
    table.add_column("P(marché)",   width=10, justify="right")
    table.add_column("Value",       width=8, justify="right")
    table.add_column("EV",          width=7, justify="right")

    OUTCOME_LABELS = {"home": "1", "draw": "X", "away": "2"}
    OUTCOME_STYLES = {"home": "green", "draw": "yellow", "away": "red"}

    for r in results:
        match_str = f"{r['home']} — {r['away']}"
        for i, bet in enumerate(r["value_bets"]):
            style = OUTCOME_STYLES.get(bet["outcome"], "white")
            value_str = f"[bold green]+{bet['value_pct']:.1f}%[/bold green]"
            ev_str = f"[{'green' if bet['ev'] > 0 else 'red'}]{bet['ev']:+.3f}[/]"
            table.add_row(
                match_str if i == 0 else "",
                r["match_time"] if i == 0 else "",
                f"[{style}]{OUTCOME_LABELS[bet['outcome']]}[/{style}]",
                f"[bold]{bet['best_odds']:.2f}[/bold]",
                bet["best_book"],
                f"{bet['p_model']:.1f}%",
                f"{bet['p_implied']:.1f}%",
                value_str,
                ev_str,
            )

    console.print(table)

    # Résumé marge marché
    margins = [r["margin_pct"] for r in results if r.get("margin_pct") is not None]
    if margins:
        avg_margin = sum(margins) / len(margins)
        console.print(
            f"  Marge bookmaker moyenne : [yellow]{avg_margin:.1f}%[/yellow] "
            f"| {results[0]['books_count']} bookmakers agrégés\n"
        )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Value bets : xG Understat × cotes The Odds API"
    )
    parser.add_argument(
        "--league", nargs="+", default=["ligue1"],
        help="Ligues (ex: ligue1 pl laliga). Default: ligue1"
    )
    parser.add_argument(
        "--last", type=int, default=10,
        help="Derniers N matchs pour le calcul xG (default: 10)"
    )
    parser.add_argument(
        "--min-value", type=float, default=3.0,
        help="Seuil minimum de value en %% (default: 3.0)"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Exporte les résultats en JSON dans data/value_bets.json"
    )
    args = parser.parse_args()

    if not ODDS_API_KEY:
        console.print(
            "[red]ODDS_API_KEY non définie.[/red] "
            "Inscription : [link]https://the-odds-api.com[/link]\n"
            "Puis : [bold]ODDS_API_KEY=ta_clé[/bold] dans .env"
        )
        sys.exit(1)

    client = OddsClient()
    all_results: dict[str, list[dict]] = {}

    for league_key in args.league:
        league = resolve_league(league_key)
        if not league:
            console.print(f"[red]Ligue inconnue : {league_key}[/red]")
            continue

        # 1. xG historique via Understat (top 5 ligues uniquement)
        if league_key in UNDERSTAT_LEAGUES:
            console.print(
                f"\n{league.flag} [dim]Chargement xG Understat "
                f"[{league.name} 2025]...[/dim]"
            )
            matches = fetch_league_xg(league.understat_slug, season=2025)
        else:
            console.print(
                f"\n{league.flag} [yellow]{league.name} : "
                "xG Understat non dispo pour compétitions européennes — "
                "affichage cotes uniquement[/yellow]"
            )
            matches = []

        team_stats = compute_team_xg_probs(matches, last_n=args.last)

        # 2. Cotes à venir via The Odds API
        console.print(f"  [dim]Récupération cotes The Odds API...[/dim]")
        events = client.fetch_odds(league_key, markets=["h2h"])

        if not events:
            console.print(f"  [yellow]Aucun match à venir trouvé pour {league.name}[/yellow]")
            continue

        # 3. Value bets
        if matches:
            results = find_value_bets(events, team_stats, args.min_value, args.last)
        else:
            # Pas de xG : afficher juste les cotes disponibles
            results = []
            _print_odds_only(league_key, events)

        print_value_table(league_key, results, args.last)

        if client.quota_remaining is not None:
            console.print(
                f"  [dim]Quota The Odds API : "
                f"{client.quota_remaining} req restantes ce mois[/dim]\n"
            )

        all_results[league_key] = results

    if args.export and all_results:
        out = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model":        f"xG Poisson (last {args.last} matches)",
            "min_value_pct": args.min_value,
            "leagues":      all_results,
        }
        path = DATA_DIR / "value_bets.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False, default=str)
        console.print(f"[green]Exporté → {path}[/green]")


def _print_odds_only(league_key: str, events: list[dict]):
    """Affiche les cotes brutes sans analyse value (ligues sans xG)."""
    from euro_top.config import resolve_league
    league = resolve_league(league_key)
    flag = league.flag if league else ""
    name = league.name if league else league_key

    console.print(f"\n{flag} [bold]{name}[/bold] — Prochains matchs (cotes 1X2)\n")
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Match",     min_width=35)
    table.add_column("Date",      width=14)
    table.add_column("Cote 1",    width=7, justify="right")
    table.add_column("Cote X",    width=7, justify="right")
    table.add_column("Cote 2",    width=7, justify="right")
    table.add_column("Marge %",   width=8, justify="right")

    for event in events[:15]:
        h2h = parse_h2h(event)
        if not h2h:
            continue
        commence = h2h.get("commence_time", "")
        try:
            dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            match_time = dt.strftime("%a %d/%m %H:%M")
        except Exception:
            match_time = commence[:16]

        margin_str = (
            f"{h2h['market_margin_pct']:.1f}%"
            if h2h.get("market_margin_pct") else "—"
        )
        table.add_row(
            f"{h2h['home_team']} — {h2h['away_team']}",
            match_time,
            f"{h2h['best_home_odds']:.2f}" if h2h.get("best_home_odds") else "—",
            f"{h2h['best_draw_odds']:.2f}" if h2h.get("best_draw_odds") else "—",
            f"{h2h['best_away_odds']:.2f}" if h2h.get("best_away_odds") else "—",
            margin_str,
        )
    console.print(table)


if __name__ == "__main__":
    main()
