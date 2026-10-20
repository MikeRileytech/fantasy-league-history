"""
Power rankings week by week, for the Power Rankings tab's rank chart.

One snapshot per finished regular-season week: build_power_rankings() run
on the league as it stood when that week's Monday night game ended -
records, points and opponents through that week, each team's roster for
that week, and each rostered player's points through that week.

Snapshots are rebuilt from ESPN's week-by-week data (each week's box
scores, and every player's points by week from his player card) rather
than copied from the live rankings, so one comes out the same whenever it
is taken: an app asleep on Monday night catches up later, and waiver moves
made later in the week don't leak in. That also means small differences
from the live table are expected - there, rosters are today's.

Players who can't play don't count (power_rankings.can_play). Box scores
keep each week's lineup slots, so a player in an IR slot is left out of
that week; but ESPN only says who is hurt today, so injury statuses count
only for the week that just finished.

season_refresh.py takes the snapshots on Streamlit Cloud and commits them
with the season data. history_file() holds them, one row per team per week.
"""

import pandas as pd

import league_data
import live_data
import power_rankings

COLUMNS = [
    "season", "week", "espn_team_id", "team_name", "rank", "power_score",
    "record_score", "points_score", "sos_score", "roster_talent_score", "rule",
]

# The ranking rule a snapshot was made under. Bump it when the ranking
# changes, and the weeks saved under the old one are rebuilt. 2: players
# who can't play don't count.
RULE = 2

# Players per ESPN player-card request. A week's rosters are about 200
# players, each sent with every week's stats.
PLAYER_BATCH = 50


def history_file(season: int):
    return league_data.PROCESSED_DIR / f"power_rankings_{season}.csv"


def load_history(season: int) -> pd.DataFrame:
    """Every saved snapshot for `season`, empty if none."""
    path = history_file(season)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(path)


def saved_weeks(history: pd.DataFrame) -> set[int]:
    """The weeks in history saved under the current RULE."""
    rule = history["rule"] if "rule" in history else pd.Series(index=history.index, dtype=float)
    return set(history.loc[rule == RULE, "week"].astype(int))


def missing_weeks(season: int, finished: int) -> list[int]:
    """Weeks 1..finished with no snapshot under the current RULE yet."""
    saved = saved_weeks(load_history(season))
    return [week for week in range(1, finished + 1) if week not in saved]


# The rank chart's last point: the live table's ranks.
NOW = "Now"


def chart_rows(history: pd.DataFrame, live: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[str]]:
    """The rank chart's rows and its x-axis order: the saved weeks, then
    NOW - the live table's ranks - when given. Weeks become text, kept in
    week order (10 after 9)."""
    rows = history.assign(week=history["week"].astype(int).astype(str))
    order = [str(week) for week in sorted(history["week"].astype(int).unique())]
    if live is not None and not live.empty:
        now = live[["espn_team_id", "team_name", "rank", "power_score"]].assign(week=NOW)
        rows = pd.concat([rows, now], ignore_index=True)
        order.append(NOW)
    return rows, order


def scoreboard(boxes) -> list[dict]:
    """One week's box scores as matchup rows, byes left out.

    A week ESPN has moved past but not finalized reads 0-0 in its box
    scores, so its scores are summed from the starters instead, as
    season_refresh.week_scores does.
    """
    import season_refresh

    rows = []
    for box in boxes:
        home, away = box.home_team, box.away_team
        if not hasattr(home, "team_id") or not hasattr(away, "team_id"):
            continue  # a bye
        home_score, away_score = box.home_score, box.away_score
        if not (home_score or away_score):
            home_score = season_refresh._starters_points(box.home_lineup)
            away_score = season_refresh._starters_points(box.away_lineup)
        rows.append({
            "home_team_id": home.team_id, "home_team_name": home.team_name,
            "home_score": home_score,
            "away_team_id": away.team_id, "away_team_name": away.team_name,
            "away_score": away_score,
        })
    return rows


def records_through(matchups_by_week: dict) -> tuple[list[dict], list[dict]]:
    """(teams, schedule) for build_power_rankings() from final scores.

    matchups_by_week maps week -> scoreboard() rows. Team names are ESPN's
    current ones, as its standings show them.
    """
    teams, schedule = {}, []
    for week in sorted(matchups_by_week):
        for m in matchups_by_week[week]:
            for me, them in (("home", "away"), ("away", "home")):
                team_id = m[f"{me}_team_id"]
                row = teams.setdefault(team_id, {
                    "espn_team_id": team_id, "wins": 0, "losses": 0, "ties": 0,
                    "points_for": 0.0, "points_against": 0.0,
                })
                row["team_name"] = m[f"{me}_team_name"]
                mine, theirs = m[f"{me}_score"], m[f"{them}_score"]
                row["wins"] += mine > theirs
                row["losses"] += mine < theirs
                row["ties"] += mine == theirs
                row["points_for"] = round(row["points_for"] + mine, 2)
                row["points_against"] = round(row["points_against"] + theirs, 2)
                schedule.append({
                    "espn_team_id": team_id, "week": week,
                    "opponent_espn_team_id": m[f"{them}_team_id"],
                })
    return sorted(teams.values(), key=lambda r: r["espn_team_id"]), schedule


def rosters_as_of(league, boxes, week: int, points: dict, statuses: bool = True) -> list[dict]:
    """Every team's week-`week` roster (from that week's box scores), with
    each player's points through that week - the rows
    build_power_rankings() takes as `rosters`. Each row has that week's
    lineup slot, and the player's injury status (today's) when `statuses`.

    Points come from the players' cards, not the box scores, so a player
    picked up off waivers keeps what he scored as a free agent, as in the
    live table. points caches ESPN player id -> {week: fantasy points}
    across calls, so a run saving several weeks fetches each player once.
    Raises on any ESPN failure: a snapshot missing a team's roster would
    rank it wrongly for good, so the week is left for the next check
    instead.
    """
    lineups = {}
    for box in boxes:
        for team, lineup in ((box.home_team, box.home_lineup), (box.away_team, box.away_lineup)):
            if hasattr(team, "team_id"):  # not a bye
                lineups[team.team_id] = lineup
    rostered = []
    # In league.teams order, as the live table's rosters are: the score
    # breaks ties (undrafted players' draft slots) by row order.
    for team in league.teams:
        if team.team_id not in lineups:
            continue  # a bye
        if not lineups[team.team_id]:
            raise RuntimeError(f"ESPN returned no week {week} roster for team {team.team_id}")
        rostered += [(team.team_id, p) for p in lineups[team.team_id]]

    needed = sorted({p.playerId for _, p in rostered} - set(points))
    for start in range(0, len(needed), PLAYER_BATCH):
        found = league.player_info(playerId=needed[start:start + PLAYER_BATCH])
        # espn_api hands back a lone player bare, and none as None.
        if not isinstance(found, list):
            found = [found] if found else []
        for player in found:
            points[player.playerId] = {w: s.get("points", 0.0) for w, s in player.stats.items()}
    for pid in needed:
        points.setdefault(pid, {})

    rows = []
    for team_id, p in rostered:
        weekly = [points[p.playerId].get(w, 0.0) for w in range(1, week + 1)]
        # Weeks with any points stand in for games played: a bye or an
        # injury scores nothing.
        played = [value for value in weekly if value]
        rows.append({
            "espn_team_id": team_id,
            "player_id": p.playerId,
            "player_name": p.name,
            "position": p.position,
            "total_points": round(sum(weekly), 2),
            "avg_points": round(sum(played) / len(played), 2) if played else None,
            "slot": p.slot_position,
            "status": p.injuryStatus if statuses else None,
        })
    return rows


def snapshot_rows(season: int, week: int, teams, schedule, rosters, draft,
                  reg_season_weeks: int) -> pd.DataFrame:
    """One week's rankings as history rows. current_week is the week after
    `week`, as the live tab passes it once that week is over, so the
    draft-slot signal fades the same way."""
    rankings, _ = power_rankings.build_power_rankings(
        teams, schedule, rosters, draft, week + 1, reg_season_weeks
    )
    rankings["season"] = season
    rankings["week"] = week
    rankings["rule"] = RULE
    scores = ["power_score", "record_score", "points_score", "sos_score", "roster_talent_score"]
    rankings[scores] = rankings[scores].round(2)
    return rankings[COLUMNS]


def save_weeks(league, season: int, weeks: list[int]) -> tuple[list[int], list[str]]:
    """Build each week's snapshot and add it to history_file().

    Weeks saved under an older RULE are rebuilt too, whichever weeks were
    asked for: a saver thread still running older code asks only for the
    weeks it hasn't saved. Weeks from the playoffs on are skipped: the
    standings stop there. A week whose scores aren't in, or that fails to
    build, is left out and comes back from missing_weeks() on the next
    check. Returns (weeks saved, notes on the ones left out).
    """
    reg_season_weeks = league.settings.reg_season_count
    history = load_history(season)
    outdated = set(history["week"].astype(int)) - saved_weeks(history)
    weeks = sorted(week for week in set(weeks) | outdated if week <= reg_season_weeks)
    if not weeks:
        return [], []

    draft = live_data._draft_picks(league)
    if not draft:
        # Early weeks lean on draft slots; without them a snapshot would be
        # ranked on noise and kept for good.
        return [], [f"ESPN sent no {season} draft"]
    scoreboards, boxes, points = {}, {}, {}
    built, notes = [], []
    for week in weeks:
        # ESPN's injury statuses are today's: they count only for the week
        # that just finished. Older weeks go by that week's IR slots alone.
        statuses = week == weeks[-1] and week >= league.current_week - 1
        try:
            for w in range(1, week + 1):
                if w not in scoreboards:
                    week_boxes = league.box_scores(w)
                    final = scoreboard(week_boxes)
                    if not final or any(not (m["home_score"] or m["away_score"]) for m in final):
                        raise RuntimeError(f"ESPN's week {w} scores aren't in yet")
                    scoreboards[w], boxes[w] = final, week_boxes
            teams, schedule = records_through({w: scoreboards[w] for w in range(1, week + 1)})
            rosters = rosters_as_of(league, boxes[week], week, points, statuses)
            built.append(snapshot_rows(season, week, teams, schedule, rosters, draft, reg_season_weeks))
        except Exception as exc:
            notes.append(f"week {week}: {exc}")

    if built:
        history = pd.concat([history, *built], ignore_index=True)
        history = history.drop_duplicates(["week", "espn_team_id"], keep="last")
        history.sort_values(["week", "rank"]).to_csv(history_file(season), index=False)
    return [int(frame["week"].iloc[0]) for frame in built], notes
