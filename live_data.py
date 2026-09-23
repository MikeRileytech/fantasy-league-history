"""
Live, in-progress-season data pulled directly from ESPN's API.

Unlike league_data.py (which reads the imported CSV snapshots in
data/processed/), everything here hits ESPN on every call. It backs the
app's "Live" tab, which shows the season currently being played even before
that season has been imported into the historical CSVs (see
update_current_season.py for when that import happens).
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from espn_api.football import League

import league_data

PROJECT_DIR = Path(__file__).resolve().parent


def espn_credentials():
    """LEAGUE_ID/ESPN_S2/SWID from .env locally, falling back to Streamlit
    secrets when deployed - Streamlit Community Cloud has no .env file, so
    the importer's local-only credentials wouldn't otherwise reach the
    deployed app's Live tab. Returns (None, None, None) if unset either way.
    """
    load_dotenv(PROJECT_DIR / ".env")
    league_id = os.getenv("LEAGUE_ID")
    espn_s2 = os.getenv("ESPN_S2")
    swid = os.getenv("SWID")

    if not league_id:
        try:
            league_id = st.secrets.get("LEAGUE_ID")
            espn_s2 = espn_s2 or st.secrets.get("ESPN_S2")
            swid = swid or st.secrets.get("SWID")
        except FileNotFoundError:
            pass

    if not league_id:
        return None, None, None
    return int(league_id), espn_s2 or None, swid or None


def fetch_live_league(league_id: int, season: int, espn_s2, swid) -> League:
    return League(league_id=league_id, year=season, espn_s2=espn_s2, swid=swid)


def live_standings(league: League) -> list[dict]:
    """Current record for every team, sorted best to worst."""
    return [
        {
            "espn_team_id": team.team_id,
            "team_name": team.team_name,
            "wins": team.wins,
            "losses": team.losses,
            "ties": team.ties,
            "points_for": round(team.points_for, 1),
            "points_against": round(team.points_against, 1),
            "logo_url": team.logo_url or None,
        }
        for team in league.standings()
    ]


def live_matchups(league: League, week: int) -> list[dict]:
    """One row per matchup for the given week, with live/projected scores."""
    rows = []
    for box in league.box_scores(week):
        rows.append(
            {
                "home_team_id": box.home_team.team_id if box.home_team else None,
                "home_team_name": box.home_team.team_name if box.home_team else "BYE",
                "home_score": box.home_score,
                "home_projected": box.home_projected,
                "away_team_id": box.away_team.team_id if box.away_team else None,
                "away_team_name": box.away_team.team_name if box.away_team else "BYE",
                "away_score": box.away_score,
                "away_projected": box.away_projected,
                "is_playoff": box.is_playoff,
            }
        )
    return rows


def latest_manager_by_team_id() -> dict:
    """Best-guess espn_team_id -> manager for a season that hasn't been
    imported yet, using the most recent season that ESPN team id appeared
    under. ESPN team ids are usually stable year to year unless ownership
    changes hands, so this is a good stand-in for the Live tab - the real
    manager_mapping.csv takes over once the season is actually imported."""
    mapping = league_data.load_mapping_full()
    latest = mapping.sort_values("season").drop_duplicates("espn_team_id", keep="last")
    return dict(zip(latest["espn_team_id"], latest["manager"]))
