"""Script de collecte autonome — peut être appelé en cron."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import argparse
from euro_top.db import init_db, get_session, count_api_calls_today
from euro_top.config import all_leagues, domestic_leagues, SEASON
from euro_top.collectors.api_football import ApiFootballClient, RateLimitError
from euro_top.collectors.understat import scrape_league_xg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Collecte des données football européen")
    parser.add_argument("--league", default="all", help="Ligue ou 'all'")
    parser.add_argument("--season", type=int, default=SEASON)
    parser.add_argument("--xg", action="store_true", help="Collecte xG via Understat")
    args = parser.parse_args()

    init_db()
    db = get_session()

    used = count_api_calls_today(db)
    logger.info(f"Quota API aujourd'hui : {used}/90")

    if args.league == "all":
        leagues = all_leagues()
    else:
        from euro_top.config import resolve_league
        lg = resolve_league(args.league)
        if not lg:
            logger.error(f"Ligue inconnue : {args.league}")
            sys.exit(1)
        leagues = [lg]

    client = ApiFootballClient(db)

    for lg in leagues:
        logger.info(f"=== {lg.flag} {lg.name} ===")
        try:
            client.fetch_standings(lg.id, args.season)
            client.fetch_fixtures(lg.id, args.season)
            client.fetch_top_scorers(lg.id, args.season)
            client.fetch_top_assisters(lg.id, args.season)

            if args.xg and lg.understat_slug:
                scrape_league_xg(lg.understat_slug, lg.id, args.season, db)

        except RateLimitError as e:
            logger.error(f"Quota atteint : {e}")
            break
        except Exception as e:
            logger.error(f"Erreur [{lg.name}]: {e}")
            continue

    client.close()
    db.close()
    logger.info("Collecte terminée.")


if __name__ == "__main__":
    main()
