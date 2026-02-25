"""euro-top — CLI stats football européen.

Usage :
    euro-top classement --league ligue1
    euro-top buteurs --league cl --top 20
    euro-top passeurs --league pl
    euro-top xg --league laliga --last 10
    euro-top distance --league bundesliga --last 5
    euro-top rapport
    euro-top collect --league all
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel
from rich.text import Text
from rich import box

from euro_top.config import resolve_league, all_leagues, domestic_leagues, SEASON
from euro_top.db import (
    init_db, get_session,
    get_standings, get_top_scorers, get_top_assisters,
    get_recent_matches, get_matches_with_xg, get_xg_by_team,
    get_matches_with_distance, get_distance_by_team,
    count_api_calls_today,
)

app = typer.Typer(
    name="euro-top",
    help=(
        "⚽ euro-top — Stats football européen\n\n"
        "Ligues: ligue1 🇫🇷  pl 🏴󠁧󠁢󠁥󠁮󠁧󠁿  laliga 🇪🇸  seriea 🇮🇹  bundesliga 🇩🇪\n"
        "Europe: cl 🏆  el 🟠  ecl ⚪"
    ),
    rich_markup_mode="rich",
)
console = Console()


def _get_league_or_exit(league_str: str):
    league = resolve_league(league_str)
    if not league:
        console.print(f"[red]Ligue inconnue : '{league_str}'. "
                      "Essaie : ligue1, pl, laliga, seriea, bundesliga, cl, el, ecl[/red]")
        raise typer.Exit(1)
    return league


def _form_colored(form: str | None) -> str:
    if not form:
        return ""
    result = []
    for c in form[-5:]:
        if c == "W":
            result.append("[green]W[/green]")
        elif c == "L":
            result.append("[red]L[/red]")
        elif c == "D":
            result.append("[yellow]D[/yellow]")
        else:
            result.append(c)
    return "".join(result)


def _xg_bar(xg: float, max_xg: float = 3.5, width: int = 12) -> str:
    """Mini barre visuelle pour les xG."""
    if xg is None:
        return "—"
    ratio = min(xg / max_xg, 1.0)
    filled = int(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {xg:.2f}"


# ── classement ───────────────────────────────────────────────────────────────

@app.command()
def classement(
    league: str = typer.Option(..., "--league", "-l", help="Ligue (ligue1, pl, laliga…)"),
    season: int = typer.Option(SEASON, "--season", "-s", help="Saison (ex: 2024)"),
):
    """🏆 Classement d'une ligue."""
    lg = _get_league_or_exit(league)
    db = get_session()
    rows = get_standings(db, lg.id, season)
    db.close()

    if not rows:
        console.print(f"[yellow]Aucune donnée. Lance : euro-top collect --league {lg.short}[/yellow]")
        raise typer.Exit()

    t = Table(
        title=f"{lg.flag} Classement {lg.name} — Saison {season}/{season+1}",
        box=box.ROUNDED, header_style="bold white",
        show_lines=False, expand=False
    )
    t.add_column("#",    width=4, style="bold dim", justify="right")
    t.add_column("Équipe", style="bold", min_width=22)
    t.add_column("J",   justify="right", width=4)
    t.add_column("G",   justify="right", style="green", width=4)
    t.add_column("N",   justify="right", style="yellow", width=4)
    t.add_column("P",   justify="right", style="red", width=4)
    t.add_column("BP",  justify="right", width=4)
    t.add_column("BC",  justify="right", width=4)
    t.add_column("Diff",justify="right", width=5)
    t.add_column("Pts", justify="right", style="bold cyan", width=4)
    t.add_column("Forme", width=16)

    for r in rows:
        diff = f"+{r.goal_diff}" if r.goal_diff > 0 else str(r.goal_diff)
        t.add_row(
            str(r.rank), r.team,
            str(r.played), str(r.won), str(r.drawn), str(r.lost),
            str(r.goals_for), str(r.goals_against), diff,
            str(r.points),
            _form_colored(r.form),
        )

    console.print(t)


# ── resultats ────────────────────────────────────────────────────────────────

@app.command()
def resultats(
    league: str = typer.Option(..., "--league", "-l"),
    season: int = typer.Option(SEASON, "--season", "-s"),
    last:   int = typer.Option(10, "--last", "-n", help="Nombre de matchs à afficher"),
):
    """📋 Résultats récents."""
    lg = _get_league_or_exit(league)
    db = get_session()
    matches = get_recent_matches(db, lg.id, season, last)
    db.close()

    if not matches:
        console.print(f"[yellow]Aucun résultat. Lance : euro-top collect --league {lg.short}[/yellow]")
        raise typer.Exit()

    t = Table(
        title=f"{lg.flag} {lg.name} — {last} derniers résultats",
        box=box.SIMPLE_HEAD, header_style="bold white",
    )
    t.add_column("Date", style="dim", width=12)
    t.add_column("Domicile", style="bold", min_width=22)
    t.add_column("Score", justify="center", style="bold yellow", width=7)
    t.add_column("Extérieur", min_width=22)
    t.add_column("xG", justify="center", style="cyan dim", width=12)

    for m in matches:
        score = f"{m.home_goals} - {m.away_goals}" if m.home_goals is not None else "— - —"
        xg_str = ""
        if m.home_xg is not None and m.away_xg is not None:
            xg_str = f"{m.home_xg:.2f} | {m.away_xg:.2f}"
        date_str = m.match_date.strftime("%d/%m/%Y") if m.match_date else "—"
        t.add_row(date_str, m.home_team, score, m.away_team, xg_str)

    console.print(t)


# ── buteurs ──────────────────────────────────────────────────────────────────

@app.command()
def buteurs(
    league: str = typer.Option(..., "--league", "-l"),
    season: int = typer.Option(SEASON, "--season", "-s"),
    top:    int = typer.Option(20, "--top", "-n"),
):
    """⚽ Top buteurs."""
    lg = _get_league_or_exit(league)
    db = get_session()
    players = get_top_scorers(db, lg.id, season, top)
    db.close()

    if not players:
        console.print(f"[yellow]Aucune donnée. Lance : euro-top collect --league {lg.short}[/yellow]")
        raise typer.Exit()

    t = Table(
        title=f"{lg.flag} Top Buteurs — {lg.name} {season}/{season+1}",
        box=box.ROUNDED, header_style="bold yellow",
    )
    t.add_column("#",       width=4, style="dim", justify="right")
    t.add_column("Joueur",  style="bold", min_width=22)
    t.add_column("Club",    min_width=18)
    t.add_column("Buts",    justify="right", style="green bold", width=6)
    t.add_column("(pen.)",  justify="right", style="dim", width=7)
    t.add_column("Passes D.", justify="right", style="cyan", width=9)
    t.add_column("Matchs",  justify="right", style="dim", width=7)
    t.add_column("xG",      justify="right", style="magenta", width=7)

    for i, p in enumerate(players, 1):
        pen = f"({p.penalties})" if p.penalties else "—"
        xg  = f"{p.xg:.2f}" if p.xg else "—"
        t.add_row(
            str(i), p.name or "—", p.team or "—",
            str(p.goals), pen,
            str(p.assists), str(p.matches_played), xg,
        )

    console.print(t)


# ── passeurs ─────────────────────────────────────────────────────────────────

@app.command()
def passeurs(
    league: str = typer.Option(..., "--league", "-l"),
    season: int = typer.Option(SEASON, "--season", "-s"),
    top:    int = typer.Option(15, "--top", "-n"),
):
    """🎯 Top passeurs décisifs."""
    lg = _get_league_or_exit(league)
    db = get_session()
    players = get_top_assisters(db, lg.id, season, top)
    db.close()

    if not players:
        console.print(f"[yellow]Aucune donnée. Lance : euro-top collect --league {lg.short}[/yellow]")
        raise typer.Exit()

    t = Table(
        title=f"{lg.flag} Top Passeurs — {lg.name} {season}/{season+1}",
        box=box.ROUNDED, header_style="bold cyan",
    )
    t.add_column("#",        width=4, style="dim", justify="right")
    t.add_column("Joueur",   style="bold", min_width=22)
    t.add_column("Club",     min_width=18)
    t.add_column("Passes D.", justify="right", style="cyan bold", width=9)
    t.add_column("Buts",     justify="right", style="green", width=6)
    t.add_column("Matchs",   justify="right", style="dim", width=7)

    for i, p in enumerate(players, 1):
        t.add_row(
            str(i), p.name or "—", p.team or "—",
            str(p.assists), str(p.goals), str(p.matches_played),
        )

    console.print(t)


# ── xg ───────────────────────────────────────────────────────────────────────

@app.command()
def xg(
    league: str = typer.Option(..., "--league", "-l"),
    season: int = typer.Option(SEASON, "--season", "-s"),
    last:   int = typer.Option(10, "--last", "-n", help="Derniers N matchs avec xG"),
    by_team: bool = typer.Option(False, "--team", "-t", help="Vue par équipe (saison entière)"),
):
    """📊 Expected Goals (xG) — par match ou par équipe."""
    lg = _get_league_or_exit(league)
    db = get_session()

    if by_team:
        data = get_xg_by_team(db, lg.id, season)
        db.close()
        if not data:
            console.print(f"[yellow]Aucun xG disponible pour {lg.name}.[/yellow]")
            raise typer.Exit()

        t = Table(
            title=f"{lg.flag} xG par équipe — {lg.name} {season}/{season+1}",
            box=box.ROUNDED, header_style="bold magenta",
        )
        t.add_column("#",          width=4, style="dim", justify="right")
        t.add_column("Équipe",     style="bold", min_width=22)
        t.add_column("Matchs",     justify="right", width=7)
        t.add_column("xG For",     justify="right", style="green bold", width=8)
        t.add_column("xG /match",  justify="right", style="green", width=9)
        t.add_column("xG Against", justify="right", style="red", width=11)
        t.add_column("xGA /match", justify="right", style="red dim", width=10)
        t.add_column("Diff xG",    justify="right", style="bold", width=9)

        for i, row in enumerate(data, 1):
            diff = row.get("xg_diff", 0)
            diff_str = f"+{diff:.2f}" if diff >= 0 else f"{diff:.2f}"
            diff_color = "green" if diff >= 0 else "red"
            t.add_row(
                str(i), row["team"], str(row["matches"]),
                f"{row['xg_for']:.2f}",
                f"{row.get('xg_for_avg', 0):.2f}",
                f"{row['xg_against']:.2f}",
                f"{row.get('xg_against_avg', 0):.2f}",
                f"[{diff_color}]{diff_str}[/{diff_color}]",
            )
    else:
        matches = get_matches_with_xg(db, lg.id, season, last)
        db.close()
        if not matches:
            console.print(f"[yellow]Aucun xG disponible. "
                          f"Lance : euro-top collect --league {lg.short} --xg[/yellow]")
            raise typer.Exit()

        t = Table(
            title=f"{lg.flag} xG par match — {lg.name} ({last} derniers)",
            box=box.SIMPLE_HEAD, header_style="bold magenta",
        )
        t.add_column("Date",      style="dim", width=12)
        t.add_column("Domicile",  style="bold", min_width=22)
        t.add_column("Score",     justify="center", style="bold yellow", width=7)
        t.add_column("Extérieur", min_width=22)
        t.add_column("xG dom.",   justify="center", style="green", width=14)
        t.add_column("xG ext.",   justify="center", style="red", width=14)

        for m in matches:
            score = f"{m.home_goals} - {m.away_goals}"
            date_str = m.match_date.strftime("%d/%m/%Y") if m.match_date else "—"
            t.add_row(
                date_str, m.home_team, score, m.away_team,
                _xg_bar(m.home_xg),
                _xg_bar(m.away_xg),
            )

    console.print(t)


# ── distance ─────────────────────────────────────────────────────────────────

@app.command()
def distance(
    league: str = typer.Option(..., "--league", "-l"),
    season: int = typer.Option(SEASON, "--season", "-s"),
    last:   int = typer.Option(10, "--last", "-n", help="Fenêtre derniers matchs"),
):
    """🏃 Distance couverte (km) par équipe par match."""
    lg = _get_league_or_exit(league)
    db = get_session()
    data = get_distance_by_team(db, lg.id, season, last)
    db.close()

    if not data:
        console.print(f"[yellow]Aucune donnée de distance. "
                      f"Lance : euro-top collect --league {lg.short} --stats[/yellow]")
        raise typer.Exit()

    t = Table(
        title=f"{lg.flag} Distance couverte — {lg.name} (moy. {last} derniers matchs)",
        box=box.ROUNDED, header_style="bold blue",
    )
    t.add_column("#",         width=4, style="dim", justify="right")
    t.add_column("Équipe",    style="bold", min_width=22)
    t.add_column("Matchs",   justify="right", width=7)
    t.add_column("Moy. km",  justify="right", style="blue bold", width=9)
    t.add_column("Total km", justify="right", style="dim", width=10)
    t.add_column("Intensité", width=16)

    max_km = max((r["avg_km"] for r in data), default=120)
    for i, row in enumerate(data, 1):
        avg = row["avg_km"]
        bar_len = int((avg / max_km) * 12)
        bar = "█" * bar_len + "░" * (12 - bar_len)
        t.add_row(
            str(i), row["team"],
            str(row["matches"]),
            f"{avg:.1f}",
            f"{row['total_km']:.0f}",
            bar,
        )

    console.print(t)


# ── rapport ──────────────────────────────────────────────────────────────────

@app.command()
def rapport(
    season: int = typer.Option(SEASON, "--season", "-s"),
):
    """📰 Rapport récap — toutes ligues (classement + buteur #1 + xG top)."""
    db = get_session()

    console.print(Panel(
        f"⚽ [bold white]euro-top rapport — Saison {season}/{season+1}[/bold white]",
        style="bold blue"
    ))

    for league in all_leagues():
        standings = get_standings(db, league.id, season)
        if not standings:
            continue

        top3 = standings[:3]
        leader = standings[0]

        scorers = get_top_scorers(db, league.id, season, 1)
        top_scorer = scorers[0] if scorers else None

        assisters = get_top_assisters(db, league.id, season, 1)
        top_assister = assisters[0] if assisters else None

        xg_data = get_xg_by_team(db, league.id, season)
        top_xg = xg_data[0] if xg_data else None

        t = Table(
            title=f"{league.flag} {league.name}",
            box=box.MINIMAL_DOUBLE_HEAD, header_style="bold",
            show_header=False, padding=(0, 1),
        )
        t.add_column("", style="dim", width=20)
        t.add_column("", style="bold")

        t.add_row("🥇 Leader", f"{leader.team} ({leader.points} pts, {leader.played} J)")
        if len(standings) >= 2:
            t.add_row("🥈 2e", f"{standings[1].team} ({standings[1].points} pts)")
        if len(standings) >= 3:
            t.add_row("🥉 3e", f"{standings[2].team} ({standings[2].points} pts)")

        if top_scorer:
            t.add_row("⚽ Top buteur",
                      f"{top_scorer.name} ({top_scorer.team}) — {top_scorer.goals} buts")
        if top_assister:
            t.add_row("🎯 Top passeur",
                      f"{top_assister.name} ({top_assister.team}) — {top_assister.assists} PD")
        if top_xg:
            t.add_row("📊 Top xG",
                      f"{top_xg['team']} — {top_xg['xg_for']:.1f} xGF "
                      f"({top_xg.get('xg_for_avg', 0):.2f}/match)")

        console.print(t)
        console.print()

    db.close()


# ── collect ──────────────────────────────────────────────────────────────────

@app.command()
def collect(
    league: str = typer.Option("all", "--league", "-l",
                               help="Ligue ou 'all' pour toutes"),
    season: int  = typer.Option(SEASON, "--season", "-s"),
    xg_stats: bool = typer.Option(False, "--xg",
                                   help="Récupère aussi les xG via Understat"),
    match_stats: bool = typer.Option(False, "--stats",
                                     help="Récupère stats par match (xG + km, coûte 1 req/match)"),
    last: int = typer.Option(5, "--last",
                             help="Nb matchs récents pour --stats"),
):
    """📥 Collecte les données depuis l'API et Understat."""
    init_db()
    db = get_session()

    # Vérification clé API
    from euro_top.config import API_FOOTBALL_KEY
    if not API_FOOTBALL_KEY:
        console.print("[red]⚠️  API_FOOTBALL_KEY manquante. Copie .env.example → .env et renseigne ta clé.[/red]")
        console.print("👉 Inscription gratuite : https://api-sports.io/")
        raise typer.Exit(1)

    used_today = count_api_calls_today(db)
    console.print(f"[dim]Quota API aujourd'hui : {used_today}/90 requêtes[/dim]")

    # Sélection des ligues
    if league.lower() == "all":
        leagues = all_leagues()
    else:
        lg = _get_league_or_exit(league)
        leagues = [lg]

    from euro_top.collectors.api_football import ApiFootballClient, RateLimitError
    from euro_top.collectors.understat import scrape_league_xg

    client = ApiFootballClient(db)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        for lg in leagues:
            task = progress.add_task(f"{lg.flag} {lg.name}", total=4)

            try:
                # 1. Classement
                progress.update(task, description=f"{lg.flag} {lg.name} — classement")
                client.fetch_standings(lg.id, season)
                progress.advance(task)

                # 2. Résultats
                progress.update(task, description=f"{lg.flag} {lg.name} — résultats")
                fixtures = client.fetch_fixtures(lg.id, season)
                progress.advance(task)

                # 3. Buteurs
                progress.update(task, description=f"{lg.flag} {lg.name} — buteurs")
                client.fetch_top_scorers(lg.id, season)
                progress.advance(task)

                # 4. Passeurs
                progress.update(task, description=f"{lg.flag} {lg.name} — passeurs")
                client.fetch_top_assisters(lg.id, season)
                progress.advance(task)

                # 5. xG via Understat (top 5 ligues uniquement)
                if xg_stats and lg.understat_slug:
                    progress.update(task, description=f"{lg.flag} {lg.name} — xG Understat")
                    scrape_league_xg(lg.understat_slug, lg.id, season, db)

                # 6. Stats par match via API (coûteux)
                if match_stats:
                    ft_fixtures = [f for f in fixtures if f.get("status") == "FT"][:last]
                    for fx in ft_fixtures:
                        try:
                            client.fetch_fixture_stats(
                                fx["id"], lg.id,
                                fx.get("home_team", ""),
                                fx.get("away_team", ""),
                                season
                            )
                        except RateLimitError:
                            console.print("[yellow]Quota atteint, arrêt des stats par match.[/yellow]")
                            break

            except RateLimitError as e:
                console.print(f"\n[red]{e}[/red]")
                break
            except Exception as e:
                console.print(f"\n[red]Erreur [{lg.name}]: {e}[/red]")
                continue

    client.close()
    db.close()

    used_after = count_api_calls_today(get_session())
    console.print(f"\n[green]✅ Collecte terminée. Quota utilisé : {used_after}/90[/green]")


# ── status ────────────────────────────────────────────────────────────────────

@app.command()
def status():
    """ℹ️  Statut de la base de données et quota API."""
    init_db()
    db = get_session()
    used = count_api_calls_today(db)
    db.close()

    from euro_top.config import API_FOOTBALL_KEY, DATABASE_URL
    console.print(Panel(
        f"[bold]euro-top-stats[/bold]\n\n"
        f"API Football : {'[green]configurée ✅[/green]' if API_FOOTBALL_KEY else '[red]manquante ⚠️[/red]'}\n"
        f"Quota aujourd'hui : [{'green' if used < 70 else 'red'}]{used}/90[/]\n"
        f"Base : {DATABASE_URL}",
        title="⚽ Statut", border_style="blue"
    ))


if __name__ == "__main__":
    init_db()
    app()
