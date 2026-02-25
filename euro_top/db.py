"""Base de données SQLite via SQLAlchemy (sync)."""
from __future__ import annotations
import json
from datetime import datetime, date
from typing import Any

from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, Date, Boolean, Text, UniqueConstraint,
    func, desc, asc
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import DATABASE_URL


# ── ORM ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class Match(Base):
    __tablename__ = "matches"
    id          = Column(Integer, primary_key=True)       # ID API-Football
    league_id   = Column(Integer, nullable=False, index=True)
    league_name = Column(String(80))
    season      = Column(Integer, nullable=False, index=True)
    match_date  = Column(Date)
    home_team   = Column(String(100))
    away_team   = Column(String(100))
    home_goals  = Column(Integer)
    away_goals  = Column(Integer)
    status      = Column(String(20))   # FT, NS, ...
    # xG
    home_xg     = Column(Float)
    away_xg     = Column(Float)
    # Distance (km)
    home_km     = Column(Float)
    away_km     = Column(Float)
    # Meta
    fetched_at  = Column(DateTime, default=datetime.utcnow)


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("api_id", "league_id", "season"),)
    id              = Column(Integer, primary_key=True, autoincrement=True)
    api_id          = Column(Integer, nullable=False)
    name            = Column(String(120))
    team            = Column(String(100))
    league_id       = Column(Integer, nullable=False, index=True)
    season          = Column(Integer, nullable=False)
    goals           = Column(Integer, default=0)
    assists         = Column(Integer, default=0)
    matches_played  = Column(Integer, default=0)
    minutes         = Column(Integer, default=0)
    penalties       = Column(Integer, default=0)
    xg              = Column(Float)    # xG total saison (si dispo)
    xa              = Column(Float)    # xA total saison (si dispo)
    fetched_at      = Column(DateTime, default=datetime.utcnow)


class Standing(Base):
    __tablename__ = "standings"
    __table_args__ = (UniqueConstraint("league_id", "season", "team"),)
    id          = Column(Integer, primary_key=True, autoincrement=True)
    league_id   = Column(Integer, nullable=False, index=True)
    season      = Column(Integer, nullable=False)
    rank        = Column(Integer)
    team        = Column(String(100))
    team_short  = Column(String(20))
    played      = Column(Integer, default=0)
    won         = Column(Integer, default=0)
    drawn       = Column(Integer, default=0)
    lost        = Column(Integer, default=0)
    goals_for   = Column(Integer, default=0)
    goals_against = Column(Integer, default=0)
    goal_diff   = Column(Integer, default=0)
    points      = Column(Integer, default=0)
    form        = Column(String(20))
    fetched_at  = Column(DateTime, default=datetime.utcnow)


class ApiCallLog(Base):
    __tablename__ = "api_calls"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    called_at   = Column(DateTime, default=datetime.utcnow)
    endpoint    = Column(String(200))
    league_id   = Column(Integer)
    season      = Column(Integer)
    status      = Column(Integer)   # HTTP status code


# ── Engine & session ──────────────────────────────────────────────────────────

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db():
    """Crée les tables si elles n'existent pas."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()


# ── Helpers API call counting ─────────────────────────────────────────────────

def count_api_calls_today(session: Session) -> int:
    today = date.today()
    return session.query(ApiCallLog).filter(
        func.date(ApiCallLog.called_at) == today
    ).count()


def log_api_call(session: Session, endpoint: str, league_id: int | None,
                 season: int | None, status: int):
    session.add(ApiCallLog(endpoint=endpoint, league_id=league_id,
                           season=season, status=status))
    session.commit()


# ── Queries ───────────────────────────────────────────────────────────────────

def upsert_standings(session: Session, rows: list[dict]):
    for r in rows:
        stmt = sqlite_insert(Standing).values(**r)
        stmt = stmt.on_conflict_do_update(
            index_elements=["league_id", "season", "team"],
            set_={k: v for k, v in r.items() if k not in ("league_id", "season", "team")}
        )
        session.execute(stmt)
    session.commit()


def upsert_players(session: Session, rows: list[dict]):
    for r in rows:
        stmt = sqlite_insert(Player).values(**r)
        stmt = stmt.on_conflict_do_update(
            index_elements=["api_id", "league_id", "season"],
            set_={k: v for k, v in r.items() if k not in ("api_id", "league_id", "season")}
        )
        session.execute(stmt)
    session.commit()


def upsert_matches(session: Session, rows: list[dict]):
    for r in rows:
        stmt = sqlite_insert(Match).values(**r)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={k: v for k, v in r.items() if k != "id"}
        )
        session.execute(stmt)
    session.commit()


def get_standings(session: Session, league_id: int, season: int) -> list[Standing]:
    return (
        session.query(Standing)
        .filter_by(league_id=league_id, season=season)
        .order_by(asc(Standing.rank))
        .all()
    )


def get_top_scorers(session: Session, league_id: int, season: int, limit: int = 20) -> list[Player]:
    return (
        session.query(Player)
        .filter_by(league_id=league_id, season=season)
        .filter(Player.goals > 0)
        .order_by(desc(Player.goals), desc(Player.assists))
        .limit(limit)
        .all()
    )


def get_top_assisters(session: Session, league_id: int, season: int, limit: int = 20) -> list[Player]:
    return (
        session.query(Player)
        .filter_by(league_id=league_id, season=season)
        .filter(Player.assists > 0)
        .order_by(desc(Player.assists), desc(Player.goals))
        .limit(limit)
        .all()
    )


def get_recent_matches(session: Session, league_id: int, season: int, limit: int = 10) -> list[Match]:
    return (
        session.query(Match)
        .filter_by(league_id=league_id, season=season, status="FT")
        .order_by(desc(Match.match_date))
        .limit(limit)
        .all()
    )


def get_matches_with_xg(session: Session, league_id: int, season: int, limit: int = 10) -> list[Match]:
    return (
        session.query(Match)
        .filter_by(league_id=league_id, season=season, status="FT")
        .filter(Match.home_xg != None)
        .order_by(desc(Match.match_date))
        .limit(limit)
        .all()
    )


def get_matches_with_distance(session: Session, league_id: int, season: int, limit: int = 10) -> list[Match]:
    return (
        session.query(Match)
        .filter_by(league_id=league_id, season=season, status="FT")
        .filter(Match.home_km != None)
        .order_by(desc(Match.match_date))
        .limit(limit)
        .all()
    )


def get_xg_by_team(session: Session, league_id: int, season: int) -> list[dict]:
    """Retourne le xG agrégé par équipe pour la saison."""
    matches = (
        session.query(Match)
        .filter_by(league_id=league_id, season=season, status="FT")
        .filter(Match.home_xg != None)
        .all()
    )
    teams: dict[str, dict] = {}
    for m in matches:
        for team, xg_for, xg_against in [
            (m.home_team, m.home_xg, m.away_xg),
            (m.away_team, m.away_xg, m.home_xg),
        ]:
            if team not in teams:
                teams[team] = {"team": team, "xg_for": 0.0, "xg_against": 0.0, "matches": 0}
            teams[team]["xg_for"] += xg_for or 0
            teams[team]["xg_against"] += xg_against or 0
            teams[team]["matches"] += 1
    result = sorted(teams.values(), key=lambda x: x["xg_for"], reverse=True)
    for r in result:
        if r["matches"]:
            r["xg_for_avg"] = round(r["xg_for"] / r["matches"], 2)
            r["xg_against_avg"] = round(r["xg_against"] / r["matches"], 2)
            r["xg_diff"] = round(r["xg_for"] - r["xg_against"], 2)
    return result


def get_distance_by_team(session: Session, league_id: int, season: int, last: int = 10) -> list[dict]:
    """Retourne la distance moyenne par équipe (derniers N matchs)."""
    matches = (
        session.query(Match)
        .filter_by(league_id=league_id, season=season, status="FT")
        .filter(Match.home_km != None)
        .order_by(desc(Match.match_date))
        .limit(last * 20)
        .all()
    )
    teams: dict[str, dict] = {}
    for m in matches:
        for team, km in [(m.home_team, m.home_km), (m.away_team, m.away_km)]:
            if team not in teams:
                teams[team] = {"team": team, "total_km": 0.0, "matches": 0}
            teams[team]["total_km"] += km or 0
            teams[team]["matches"] += 1
    result = []
    for t in teams.values():
        if t["matches"] > 0:
            t["avg_km"] = round(t["total_km"] / t["matches"], 1)
            result.append(t)
    return sorted(result, key=lambda x: x["avg_km"], reverse=True)
