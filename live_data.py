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


def _schedule_played(league: League) -> list[dict]:
    """One row per game a team has actually played so far this season.

    Byes (ESPN points a team's schedule slot back at itself for a bye week -
    see espn_api's Team._fetch_schedule) and future/unplayed weeks
    (outcome 'U', undecided) are excluded, since neither is a real opponent
    to weigh strength of schedule against.
    """
    rows = []
    for team in league.teams:
        for week_index, (opponent, outcome) in enumerate(zip(team.schedule, team.outcomes)):
            if outcome not in ("W", "L", "T"):
                continue
            if opponent is None or opponent.team_id == team.team_id:
                continue
            rows.append(
                {
                    "espn_team_id": team.team_id,
                    "week": week_index + 1,
                    "opponent_espn_team_id": opponent.team_id,
                }
            )
    return rows


def _rosters(league: League) -> list[dict]:
    """One row per currently-rostered player, league-wide.

    total_points/avg_points are season-to-date (espn_api's Player class
    reads these from ESPN's scoring-period-0 stat entry, which is the
    season total), reflecting whoever holds the player right now - a
    mid-season trade or waiver move moves their season total with them.
    """
    rows = []
    for team in league.teams:
        for player in team.roster:
            rows.append(
                {
                    "espn_team_id": team.team_id,
                    "player_id": player.playerId,
                    "player_name": player.name,
                    "position": player.position,
                    "total_points": round(player.total_points, 2),
                    "avg_points": round(player.avg_points, 2),
                }
            )
    return rows


def _draft_picks(league: League) -> list[dict]:
    """This season's draft, in pick order - fetched live so it's available
    from week 1, before espn_history_importer.py has ever run for this
    season (see build_draft_rows() there for the same shape, pulled from
    the historical import path instead)."""
    return [
        {"player_id": pick.playerId, "overall_pick": overall_pick}
        for overall_pick, pick in enumerate(league.draft, start=1)
        if pick.playerId
    ]


def power_ranking_bundle(league: League) -> dict:
    """Everything power_rankings.build_power_rankings() needs for one
    live snapshot of the league: current standings, games played so far,
    current rosters, and this season's draft order."""
    return {
        "current_week": league.current_week,
        "reg_season_weeks": league.settings.reg_season_count,
        "teams": live_standings(league),
        "schedule": _schedule_played(league),
        "rosters": _rosters(league),
        "draft": _draft_picks(league),
    }


def latest_manager_by_team_id() -> dict:
    """Best-guess espn_team_id -> manager for a season that hasn't been
    imported yet, using the most recent season that ESPN team id appeared
    under. ESPN team ids are usually stable year to year unless ownership
    changes hands, so this is a good stand-in for the Live tab - the real
    manager_mapping.csv takes over once the season is actually imported."""
    mapping = league_data.load_mapping_full()
    latest = mapping.sort_values("season").drop_duplicates("espn_team_id", keep="last")
    return dict(zip(latest["espn_team_id"], latest["manager"]))
