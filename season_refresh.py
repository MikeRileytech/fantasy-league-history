"""
Keep the in-progress season's saved data current, from the deployed app.

update_current_season.py does this job when someone runs it by hand. This
does the same from inside the Streamlit Community Cloud app, which already
holds the league's credentials (LEAGUE_ID, ESPN_S2, SWID) and a GitHub token
(GITHUB_TOKEN) in its secrets: every CHECK_INTERVAL it asks ESPN how many
weeks are finished, and when that is more than data/processed/ holds, it
imports the season through ESPN, then commits the files to main in one
commit. Streamlit Cloud pulls that commit and the app shows the new data.
Each finished week's power rankings (power_history.py) are saved the same
way, in that commit when there is one.

A week counts as finished once ESPN's NFL scoreboard has every game of it
final - ESPN's own fantasy records can trail Monday night's final by hours,
so outcomes it hasn't decided yet are filled in from the scores. The season
is imported again once ESPN's records catch up, so its official numbers and
stat corrections replace those.

Only runs on Streamlit Cloud (the app lives under /mount/src there), so a
local `streamlit run` never commits on your behalf.

Streamlit Cloud doesn't restart the app when a commit lands, so app.py
reloads this module on every run, like the others, and the background
check always calls the newest copy: a deploy's changes reach it without a
reboot. start() never runs a second check.
"""

import json
import os
import sys
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

# (season, finished, counted) last committed by this process, and the
# (season, week, power_history.RULE) power rankings it committed - with the
# rule, so a new one gets the weeks rebuilt. Streamlit Cloud pulls the
# commit into this folder a little later; until then the files here are
# the old ones, and this stops the same update going twice. Both survive
# app.py's reloads of this module.
_pushed = globals().get("_pushed", set())
_ranked = globals().get("_ranked", set())


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


def _starters_points(lineup) -> float:
    return round(sum(
        p.points or 0 for p in lineup if p.slot_position not in ("BE", "IR")
    ), 2)


def week_scores(league, week) -> dict:
    """team_id -> (score, opponent's score) for `week`, from ESPN's box
    scores. The season schedule the importer reads keeps a week's scores at
    0 until ESPN finalizes it. A box score carries the live total only while
    its week is ESPN's current one; once ESPN has moved on but not yet
    finalized, the total reads 0 too, so it's summed from the starters'
    points instead."""
    scores = {}
    for box in league.box_scores(week):
        home, away = box.home_team, box.away_team
        if not hasattr(home, "team_id") or not hasattr(away, "team_id"):
            continue  # a bye
        home_score, away_score = box.home_score, box.away_score
        if not (home_score or away_score):
            home_score = _starters_points(box.home_lineup)
            away_score = _starters_points(box.away_lineup)
        scores[home.team_id] = (home_score, away_score)
        scores[away.team_id] = (away_score, home_score)
    print(f"[season_refresh] week {week} box scores: {len(scores)} teams, "
          f"{sum(1 for a, _ in scores.values() if a)} with points", flush=True)
    return scores


def fill_scores(path: Path, league, first_week: int, last_week: int) -> None:
    """Scores for weeks ESPN hasn't finalized, from the box scores."""
    matchups = pd.read_csv(path)
    for week in range(first_week, last_week + 1):
        open_ = (matchups["week"] == week) & ~matchups["outcome"].isin(PLAYED)
        if not open_.any():
            continue
        scores = week_scores(league, week)
        ids = matchups.loc[open_, "espn_team_id"]
        matchups.loc[open_, "team_score"] = ids.map(lambda i: scores.get(i, (None, None))[0]).values
        matchups.loc[open_, "opponent_score"] = ids.map(lambda i: scores.get(i, (None, None))[1]).values
    matchups.to_csv(path, index=False)


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
    import power_history

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
    import_due = not (finished < FIRST_WEEK_TO_SAVE
                      or (season, finished, counted) in _pushed
                      or (saved >= finished and saved_games(league_id, season) >= counted))
    # The Power Rankings tab's rank chart: one snapshot per finished week.
    rankings_due = [week for week in power_history.missing_weeks(season, finished)
                    if (season, week, power_history.RULE) not in _ranked]
    if not import_due and not rankings_due:
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
        if import_due:
            espn_history_importer.import_season(league, league_id, season)
            fill_scores(_matchups_file(league_id, season), league, counted + 1, finished)
            decide_from_scores(_matchups_file(league_id, season), finished)
            generate_manager_mapping.main()
            propagate_manager_names.main()

            if saved_through_week(league_id, season) < finished:
                return f"{season}: ESPN's week {finished} scores aren't in yet"

        ranked, skipped = [], []
        if rankings_due:
            # Never at the season data's expense: a week that fails is left
            # for the next check, and the season data is committed anyway.
            try:
                ranked, skipped = power_history.save_weeks(league, season, rankings_due)
            except Exception as exc:
                skipped = [f"{type(exc).__name__}: {exc}"]
        notes = f" (power rankings not saved: {'; '.join(skipped)})" if skipped else ""

        changed = {
            path.relative_to(PROJECT_DIR).as_posix(): content.decode("utf-8")
            for path, content in _tracked_files().items()
            if before.get(path) != content
        }
        if not changed:
            return f"{season}: already up to date through week {finished}{notes}"
        if import_due:
            message = f"Update {season} season data through week {finished}"
        else:
            weeks = "week" + ("s" if len(ranked) > 1 else "")
            message = f"Save {season} power rankings for {weeks} {', '.join(map(str, ranked))}"
        github_store.put_files(token, REPO, changed, message)
        if import_due:
            _pushed.add((season, finished, counted))
        _ranked.update((season, week, power_history.RULE) for week in ranked)
        return f"{season}: {message} ({len(changed)} files){notes}"
    finally:
        _put_back(before)


THREAD_NAME = "season_refresh"


def _run_forever():
    while True:
        # The newest copy of this module, so a deploy's changes reach this
        # thread: app.py reloads it on every run, and Streamlit re-imports
        # it as a new copy when a deploy changes it while the app is open.
        refresh = getattr(sys.modules.get(__name__), "refresh_once", refresh_once)
        try:
            print(f"[season_refresh] {refresh()}", flush=True)
        except BaseException:  # the importer sys.exit()s on ESPN errors
            print("[season_refresh] failed:\n" + traceback.format_exc(), flush=True)
        time.sleep(CHECK_INTERVAL)


_lock = globals().get("_lock") or threading.Lock()


def _running() -> bool:
    """Whether this process already runs the check, whichever copy of this
    module started it. One started before the thread was named (it lasts
    until the app's next restart) has Python's default name."""
    return any(t.name == THREAD_NAME or t.name.endswith("(_run_forever)")
               for t in threading.enumerate())


def start() -> None:
    """Start the background check once per process, on Streamlit Cloud only.
    Safe on every run, and after this module is reloaded or re-imported."""
    if not str(PROJECT_DIR).startswith("/mount/src"):
        return
    with _lock:
        if not _running():
            threading.Thread(target=_run_forever, name=THREAD_NAME, daemon=True).start()
