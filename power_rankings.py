"""
Weekly power ranking system for the in-progress season.

Plain pandas, no Streamlit and no ESPN calls - live_data.py fetches the raw
ESPN data (current rosters, schedule results, draft order), and this module
turns it into one 0-100 power score per team, following the same
"data loading is separate from math" split as league_data.py.

Five signals feed the score, each converted to a 0-100 scale so they combine
on equal footing:

  record          - win pct this season (a tie counts as half a win)
  points_for      - percentile rank of total points scored, across the league
  strength_of_schedule - percentile rank of the average win pct of opponents
                    actually played so far (tougher schedule = higher score)
  roster_talent   - for every rostered player, how their season point total
                    ranks against everyone else at their position (e.g.
                    "3rd-best RB currently rostered by anyone in the league"),
                    averaged across the whole roster. This is what rewards a
                    team for having the league's best RB/WR/etc.
  draft_value     - the same positional ranking, but measured against where
                    each player was actually picked in this league's draft
                    (there's no external ADP feed, so the league's own
                    overall_pick stands in for it). A player taken with the
                    last pick and outperforming the top pick at their
                    position scores very high here; a 1.1 pick performing
                    exactly like a 1.1 pick scores neutral, since they're
                    meeting expectations rather than beating them.

draft_value's weight starts at DRAFT_VALUE_BASE_WEIGHT in week 1 and decays
linearly to 0 by the final week of the regular season - a hot streak off a
16th-round flier means a lot less by week 2 than a cold one off a 1.1 does,
and by design that gap should close as the sample size grows. Whatever
weight draft_value gives up is added to roster_talent, so the five weights
always sum to 100.
"""

import pandas as pd

RECORD_WEIGHT = 25
POINTS_WEIGHT = 20
SOS_WEIGHT = 15
ROSTER_BASE_WEIGHT = 25
DRAFT_VALUE_BASE_WEIGHT = 15


def _percentile(series: pd.Series) -> pd.Series:
    """0-100 percentile rank within the series, best value = 100.

    Ties share the average rank. A series with no spread (everyone tied,
    e.g. week 1 before any games) returns 50 for everyone rather than an
    arbitrary ranking of identical values.
    """
    if series.nunique(dropna=True) <= 1:
        return pd.Series(50.0, index=series.index)
    return series.rank(pct=True, method="average") * 100


def draft_value_weight(current_week: int, reg_season_weeks: int) -> float:
    """draft_value's share of the score (0..DRAFT_VALUE_BASE_WEIGHT), decaying
    linearly from full weight in week 1 to zero by the last regular season
    week."""
    if reg_season_weeks <= 1:
        return 0.0
    decay = 1 - (current_week - 1) / (reg_season_weeks - 1)
    return DRAFT_VALUE_BASE_WEIGHT * max(0.0, min(1.0, decay))


def _score_rosters(roster_df: pd.DataFrame, draft_pick_by_player: dict, total_picks: int) -> pd.DataFrame:
    """Adds per-player position_percentile, draft_percentile and
    value_over_adp columns to a copy of roster_df."""
    roster = roster_df.copy()
    roster["position_percentile"] = roster.groupby("position")["total_points"].transform(_percentile)
    roster["position_rank"] = roster.groupby("position")["total_points"].rank(
        ascending=False, method="min"
    ).astype(int)

    total_picks = max(total_picks, 1)
    roster["draft_pick"] = roster["player_id"].map(draft_pick_by_player).fillna(total_picks + 1)
    # 1st overall -> 100 (highest draft capital); undrafted -> 0 (no expectations at all).
    roster["draft_percentile"] = ((1 - (roster["draft_pick"] - 1) / total_picks) * 100).clip(0, 100)
    roster["value_over_adp"] = roster["position_percentile"] - roster["draft_percentile"]
    return roster


def _weighted_value(group: pd.DataFrame) -> float:
    """Team-level draft value: each player's value_over_adp weighted by how
    good they currently are, so a league-winning waiver pickup swings this a
    lot more than a bench-warmer's meaningless value-over-ADP noise does."""
    weights = group["position_percentile"].clip(lower=1)
    return float((group["value_over_adp"] * weights).sum() / weights.sum())


def build_power_rankings(
    teams: list[dict],
    schedule: list[dict],
    rosters: list[dict],
    draft_picks: list[dict],
    current_week: int,
    reg_season_weeks: int,
) -> tuple[pd.DataFrame, dict]:
    """One row per team, sorted best to worst, plus the weight breakdown used.

    teams: espn_team_id, team_name, wins, losses, ties, points_for,
        points_against, logo_url (as returned by live_data.live_standings)
    schedule: espn_team_id, week, opponent_espn_team_id - one row per game
        actually played so far (byes and future weeks excluded)
    rosters: espn_team_id, player_id, player_name, position, total_points,
        avg_points - one row per currently-rostered player
    draft_picks: player_id, overall_pick - this season's draft, in pick order
    """
    teams_df = pd.DataFrame(teams)
    if teams_df.empty:
        return teams_df, {"draft_value_weight": 0.0, "roster_weight": ROSTER_BASE_WEIGHT}

    games_played = teams_df["wins"] + teams_df["losses"] + teams_df["ties"]
    teams_df["win_pct"] = (
        (teams_df["wins"] + 0.5 * teams_df["ties"]) / games_played.where(games_played > 0)
    ).fillna(0.0)
    teams_df["record_score"] = teams_df["win_pct"] * 100
    teams_df["points_score"] = _percentile(teams_df["points_for"])

    win_pct_by_team = teams_df.set_index("espn_team_id")["win_pct"]
    schedule_df = pd.DataFrame(schedule, columns=["espn_team_id", "week", "opponent_espn_team_id"])
    if not schedule_df.empty:
        schedule_df["opponent_win_pct"] = schedule_df["opponent_espn_team_id"].map(win_pct_by_team)
        sos_raw = schedule_df.groupby("espn_team_id")["opponent_win_pct"].mean()
    else:
        sos_raw = pd.Series(dtype=float)
    teams_df["sos_raw"] = teams_df["espn_team_id"].map(sos_raw).fillna(teams_df["win_pct"].mean())
    teams_df["sos_score"] = _percentile(teams_df["sos_raw"])

    draft_pick_by_player = {d["player_id"]: d["overall_pick"] for d in draft_picks}
    total_picks = max((d["overall_pick"] for d in draft_picks), default=0)
    roster_df = pd.DataFrame(
        rosters, columns=["espn_team_id", "player_id", "player_name", "position", "total_points", "avg_points"]
    )
    if not roster_df.empty:
        roster_df = _score_rosters(roster_df, draft_pick_by_player, total_picks)
        roster_talent = roster_df.groupby("espn_team_id")["position_percentile"].mean()
        draft_value_raw = roster_df.groupby("espn_team_id").apply(_weighted_value, include_groups=False)
    else:
        roster_talent = pd.Series(dtype=float)
        draft_value_raw = pd.Series(dtype=float)

    teams_df["roster_talent_score"] = teams_df["espn_team_id"].map(roster_talent).fillna(50.0)
    # draft_value_raw is a -100..100 percentile-point swing; 50 = playing exactly to draft slot.
    teams_df["draft_value_score"] = (teams_df["espn_team_id"].map(draft_value_raw) / 2 + 50).fillna(50.0).clip(0, 100)

    dv_weight = draft_value_weight(current_week, reg_season_weeks)
    roster_weight = ROSTER_BASE_WEIGHT + (DRAFT_VALUE_BASE_WEIGHT - dv_weight)

    teams_df["power_score"] = (
        teams_df["record_score"] * RECORD_WEIGHT
        + teams_df["points_score"] * POINTS_WEIGHT
        + teams_df["sos_score"] * SOS_WEIGHT
        + teams_df["roster_talent_score"] * roster_weight
        + teams_df["draft_value_score"] * dv_weight
    ) / 100.0

    teams_df = teams_df.sort_values("power_score", ascending=False).reset_index(drop=True)
    teams_df["rank"] = teams_df.index + 1
    weights = {
        "record_weight": RECORD_WEIGHT,
        "points_weight": POINTS_WEIGHT,
        "sos_weight": SOS_WEIGHT,
        "roster_weight": roster_weight,
        "draft_value_weight": dv_weight,
    }
    return teams_df, weights


def team_highlights(rosters: list[dict], draft_picks: list[dict]) -> pd.DataFrame:
    """Per team: best player by position rank, and best value-over-ADP pick.

    Backs a "why this ranking" readout under the leaderboard - the
    user-facing version of the 1.1-RB-vs-last-round-RB example.
    """
    roster_df = pd.DataFrame(
        rosters, columns=["espn_team_id", "player_id", "player_name", "position", "total_points", "avg_points"]
    )
    if roster_df.empty:
        return pd.DataFrame(
            columns=[
                "espn_team_id", "best_player_name", "best_player_position", "best_player_rank",
                "value_player_name", "value_player_position", "value_player_pick", "value_over_adp",
            ]
        )

    draft_pick_by_player = {d["player_id"]: d["overall_pick"] for d in draft_picks}
    total_picks = max((d["overall_pick"] for d in draft_picks), default=0)
    roster_df = _score_rosters(roster_df, draft_pick_by_player, total_picks)

    rows = []
    for team_id, group in roster_df.groupby("espn_team_id"):
        best = group.loc[group["position_percentile"].idxmax()]
        value = group.loc[group["value_over_adp"].idxmax()]
        rows.append(
            {
                "espn_team_id": team_id,
                "best_player_name": best["player_name"],
                "best_player_position": best["position"],
                "best_player_rank": int(best["position_rank"]),
                "value_player_name": value["player_name"],
                "value_player_position": value["position"],
                "value_player_pick": None if value["draft_pick"] > total_picks else int(value["draft_pick"]),
                "value_over_adp": round(float(value["value_over_adp"]), 1),
            }
        )
    return pd.DataFrame(rows)
