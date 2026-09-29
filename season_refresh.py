"""
Keep the in-progress season's saved data current, from the deployed app.

update_current_season.py does this job when someone runs it by hand. This
does the same from inside the Streamlit Community Cloud app, which already
holds the league's credentials (LEAGUE_ID, ESPN_S2, SWID) and a GitHub token
(GITHUB_TOKEN) in its secrets: every CHECK_INTERVAL it asks ESPN how many
weeks are finished, and when that is more than data/processed/ holds, it
imports the season through ESPN, then commits the files to main in one
commit. Streamlit Cloud pulls that commit and the app shows the new data.

A week counts as finished once ESPN's NFL scoreboard has every game of it
final - ESPN's own fantasy records can trail Monday night's final by hours,
so outcomes it hasn't decided yet are filled in from the scores. The season
is imported again once ESPN's records catch up, so its official numbers and
stat corrections replace those.

Only runs on Streamlit Cloud (the app lives under /mount/src there), so a
local `streamlit run` never commits on your behalf.
"""

import json
import os
import threading
import time
import traceback
import urllib.request
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
RAW_DIR = PROJECT_DIR / "data" / "raw"
MAPPING_FILE = PROJECT_DIR / "manager_mapping.csv"
REPO = "MikeRileytech/fantasy-league-history"

CHECK_INTERVAL = 1800  # seconds; a finished week is news once a week
FIRST_WEEK_TO_SAVE = 2  # as update_current_season.py: one week is too noisy
PLAYED = ("W", "L", "T")

# (season, finished, counted) last committed by this process. Streamlit
# Cloud pulls the commit into this folder a little later; until then the
# files here are the old ones, and this stops the same update going twice.
_pushed = set()


def _matchups_file(league_id, season) -> Path:
    return PROCESSED_DIR / f"league_{league_id}_season_{season}_matchups.csv"


def saved_through_week(league_id, season) -> int:
    """The last week of `season` with a result saved, 0 if none."""
    try:
        matchups = pd.read_csv(_matchups_file(league_id, season))
    except Exception:
        return 0
    played = matchups[matchups["outcome"].isin(PLAYED)]
    return int(played["week"].max()) if not played.empty else 0


def saved_games(league_id, season) -> int:
    """Games in the saved team records (ESPN's count), 0 if none."""
    path = PROCESSED_DIR / f"league_{league_id}_season_{season}_teams.csv"
    try:
        teams = pd.read_csv(path)
        return int(teams[["wins", "losses", "ties"]].sum(axis=1).max())
    except Exception:
        return 0


def nfl_week_final(season, week) -> bool | None:
    """True when ESPN has every NFL game of `week` final, None if unknown."""
    url = (f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
           f"scoreboard?dates={season}&seasontype=2&week={week}")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            events = json.load(resp).get("events", [])
        return bool(events) and all(
            e["status"]["type"]["completed"] for e in events
        )
    except Exception:
        return None


def finished_week(league, counted: int) -> int:
    """The last regular-season week whose NFL games are all over."""
    current = league.current_week
    for week in (current, current - 1):
        if counted < week <= league.settings.reg_season_count and nfl_week_final(league.year, week):
            return week
    return counted


def decide_from_scores(path: Path, through_week: int) -> None:
    """Outcomes ESPN hasn't decided yet (U) for weeks that are over, from
    the scores - the app only counts W, L and T."""
    matchups = pd.read_csv(path)
    open_ = (
        (matchups["week"] <= through_week)
        & ~matchups["outcome"].isin(PLAYED)
        & matchups["team_score"].notna()
        & matchups["opponent_score"].notna()
        & ((matchups["team_score"] > 0) | (matchups["opponent_score"] > 0))
    )
    if not open_.any():
        return
    mine, theirs = matchups.loc[open_, "team_score"], matchups.loc[open_, "opponent_score"]
    matchups.loc[open_, "outcome"] = [
        "W" if a > b else "L" if a < b else "T" for a, b in zip(mine, theirs)
    ]
    matchups.to_csv(path, index=False)


def _secret(name):
    import live_data  # noqa: F401 - loads .env the same way the app does
    import streamlit as st

    value = os.getenv(name)
    if not value:
        try:
            value = st.secrets.get(name)
        except Exception:
            value = None
    return value or None


def _tracked_files() -> dict:
    """Path -> bytes for every file an import can write."""
    paths = [MAPPING_FILE, *PROCESSED_DIR.glob("*"), *RAW_DIR.glob("*")]
    return {p: p.read_bytes() for p in paths if p.is_file()}


def _put_back(before: dict) -> None:
    """Leave the folder as it was, so Streamlit Cloud's pull of the commit
    doesn't collide with the same changes sitting uncommitted here."""
    for path in _tracked_files():
        if path not in before:
            path.unlink()
    for path, content in before.items():
        if not path.exists() or path.read_bytes() != content:
            path.write_bytes(content)


def refresh_once() -> str:
    """One check. Returns what happened, for the log."""
    import league_data
    import live_data

    season = league_data.season_in_progress()
    if season is None:
        return "offseason"
    league_id, espn_s2, swid = live_data.espn_credentials()
    if league_id is None:
        return "no LEAGUE_ID"
    league = live_data.fetch_live_league(league_id, season, espn_s2, swid)
    if not league.teams:
        return f"ESPN has no teams for {season} yet"
    counted = max(t.wins + t.losses + t.ties for t in league.teams)
    finished = finished_week(league, counted)
    saved = saved_through_week(league_id, season)
    if (finished < FIRST_WEEK_TO_SAVE
            or (season, finished, counted) in _pushed
            or (saved >= finished and saved_games(league_id, season) >= counted)):
        return f"{season}: saved through week {saved}, {finished} finished - nothing to do"

    token = _secret("GITHUB_TOKEN")
    if not token:
        return "no GITHUB_TOKEN - can't save the update"

    import espn_history_importer
    import generate_manager_mapping
    import github_store
    import propagate_manager_names

    before = _tracked_files()
    try:
        espn_history_importer.import_season(league, league_id, season)
        decide_from_scores(_matchups_file(league_id, season), finished)
        generate_manager_mapping.main()
        propagate_manager_names.main()

        if saved_through_week(league_id, season) < finished:
            return f"{season}: ESPN's week {finished} scores aren't in yet"

        changed = {
            path.relative_to(PROJECT_DIR).as_posix(): content.decode("utf-8")
            for path, content in _tracked_files().items()
            if before.get(path) != content
        }
        if not changed:
            return f"{season}: already up to date through week {finished}"
        github_store.put_files(
            token, REPO, changed, f"Update {season} season data through week {finished}"
        )
        _pushed.add((season, finished, counted))
        return f"{season}: saved through week {finished} ({len(changed)} files)"
    finally:
        _put_back(before)


def _run_forever():
    while True:
        try:
            print(f"[season_refresh] {refresh_once()}", flush=True)
        except BaseException:  # the importer sys.exit()s on ESPN errors
            print("[season_refresh] failed:\n" + traceback.format_exc(), flush=True)
        time.sleep(CHECK_INTERVAL)


_lock = threading.Lock()
_started = False


def start() -> None:
    """Start the background check once per process, on Streamlit Cloud only."""
    global _started
    if not str(PROJECT_DIR).startswith("/mount/src"):
        return
    with _lock:
        if not _started:
            threading.Thread(target=_run_forever, daemon=True).start()
            _started = True
