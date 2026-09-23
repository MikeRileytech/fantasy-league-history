"""
Weekly power ranking system for the in-progress season.

Plain pandas, no Streamlit and no ESPN calls - live_data.py fetches the raw
ESPN data (current rosters, schedule results, draft order), and this module
turns it into one 0-100 power score per team, following the same
"data loading is separate from math" split as league_data.py.

Four signals feed the score, each converted to a 0-100 scale so they combine
on equal footing:

  record          - win pct this season (a tie counts as half a win)
  points_for      - percentile rank of total points scored, across the league
  strength_of_schedule - percentile rank of the average win pct of opponents
                    actually played so far (tougher schedule = higher score)
  roster_talent   - how good a team's roster is at the positions that
                    actually decide games (see "Player evaluation" below)

Player evaluation
------------------
Three things shape how much a rostered player counts toward roster_talent:

1. POSITION_WEIGHTS - RB and WR are weighted highest (the positions that
   most reliably decide who wins a week), then QB, then TE. K is weighted
   low (a mostly-noise position nobody drafts for). D/ST is excluded
   entirely - nobody's evaluating a roster by its defense.

2. Magnitude, not just rank - the gap between the best QB or TE and the
   replacement-level ones at that position is much bigger than the gap
   between, say, the 6th- and 12th-best at the position (there's a small
   handful of true difference-makers, then a long flat tail). A plain
   1st/2nd/3rd-place rank can't tell an enormous gap from a trivial one,
   so instead each player is scored by how many standard deviations their
   season point total is above the mean at their position
   (_position_value_z) - the same shape as the real scoring spread, so an
   elite QB/TE's positional advantage shows up as a much bigger number
   than a middling one's, automatically.

3. Draft-slot confidence, fading over the season - a player's current
   z-score is blended with the z-score their *draft slot* would imply
   (see _expected_position_value), and how much that blend trusts the
   draft slot over the actual results decays from DRAFT_CONFIDENCE_MAX in
   week 1 to 0 by the final regular season week (draft_confidence_weight).

   This is deliberately not "reward outperforming your ADP." A 1.1 RB and
   a 12th-round RB who are BOTH the current RB1 are not equally believable
   in week 2: the 1.1 pick's draft capital says the league's talent
   evaluators expected exactly this, so their z-score is trusted almost
   fully. The 12th-rounder's hot start has much weaker priors behind it -
   a two-game sample from a player nobody rated is more likely to regress,
   so it initially counts less toward roster_talent than the same current
   z-score coming from a 1.1 would. As real results accumulate, that
   discount fades - a 12th-round WR who is still the WR1 in week 14 has
   proven it, and gets full credit for the actual performance rather than
   a shrunk version of it.
"""

import pandas as pd

RECORD_WEIGHT = 25
POINTS_WEIGHT = 20
SOS_WEIGHT = 15
ROSTER_WEIGHT = 40

# Nobody evaluates a roster by its defense - drop it before any player-level
# math happens, so it can't influence roster_talent or the "best player" /
# "best value" highlights.
EXCLUDED_POSITIONS = {"D/ST"}

# How much each position counts toward roster_talent: RB/WR most valuable
# (they decide the most games), then QB, then TE, then K (mostly noise, but
# not excluded outright like D/ST). Anything unrecognized falls back to
# DEFAULT_POSITION_WEIGHT.
POSITION_WEIGHTS = {
    "RB": 1.0,
    "WR": 1.0,
    "QB": 0.75,
    "TE": 0.65,
    "K": 0.35,
}
DEFAULT_POSITION_WEIGHT = 0.5

# Standard-deviations-above-position-mean is unbounded in principle; clip so
# one early-season fluke week can't single-handedly swing a team's score.
Z_SCORE_CLIP = 3.0

# In week 1, a player's score is DRAFT_CONFIDENCE_MAX draft-slot-expectation
# and (1 - DRAFT_CONFIDENCE_MAX) actual results; decays linearly to 0 (pure
# actual results) by the final regular season week.
DRAFT_CONFIDENCE_MAX = 0.6


def _percentile(series: pd.Series) -> pd.Series:
    """0-100 percentile rank within the series, best value = 100.

    Ties share the average rank. A series with no spread (everyone tied,
    e.g. week 1 before any games) returns 50 for everyone rather than an
    arbitrary ranking of identical values.
    """
    if series.nunique(dropna=True) <= 1:
        return pd.Series(50.0, index=series.index)
    return series.rank(pct=True, method="average") * 100


def _position_value_z(roster_df: pd.DataFrame) -> pd.Series:
    """Standard deviations above the position's mean total_points.

    Magnitude-aware by construction: if this season's QBs really do have a
    huge gap from QB1 to QB6 and almost none from QB6 to QB12, that shape
    shows up directly in the z-scores instead of being flattened into
    evenly-spaced ranks."""
    grouped = roster_df.groupby("position")["total_points"]
    mean = grouped.transform("mean")
    std = grouped.transform("std")
    z = (roster_df["total_points"] - mean) / std
    return z.replace([float("inf"), float("-inf")], 0).fillna(0).clip(-Z_SCORE_CLIP, Z_SCORE_CLIP)


def _expected_position_value(roster: pd.DataFrame) -> pd.Series:
    """What each player's position_value z-score "should" be if the draft
    had perfectly predicted this season's actual point spread at the
    position - i.e. the z-score belonging to their draft rank at the
    position, read off this season's real distribution of z-scores rather
    than an invented curve. The 1.1 pick at a position is expected to be
    that position's actual top z-score; the last pick at the position is
    expected to be its actual bottom one.

    Vectorized on purpose: a per-group groupby().apply() returning a Series
    is ambiguous in pandas when only one position group is present (as in a
    single-position test roster) - it collapses into a DataFrame instead of
    concatenating back per-row, so this builds an explicit
    (position, performance_rank) -> z-score lookup and maps draft rank
    through it instead."""
    performance_rank = roster.groupby("position")["position_value"].rank(ascending=False, method="first").astype(int)
    draft_rank = roster.groupby("position")["draft_pick"].rank(method="first").astype(int)
    max_rank = performance_rank.groupby(roster["position"]).transform("max")
    lookup_rank = draft_rank.clip(upper=max_rank)

    lookup = roster["position_value"].groupby([roster["position"], performance_rank]).first()
    keys = pd.MultiIndex.from_arrays([roster["position"], lookup_rank])
    return pd.Series(lookup.reindex(keys).to_numpy(), index=roster.index)


def draft_confidence_weight(current_week: int, reg_season_weeks: int) -> float:
    """How much of a player's score still leans on draft-slot expectation
    (0..DRAFT_CONFIDENCE_MAX), decaying linearly from full weight in week 1
    to zero by the last regular season week."""
    if reg_season_weeks <= 1:
        return 0.0
    decay = 1 - (current_week - 1) / (reg_season_weeks - 1)
    return DRAFT_CONFIDENCE_MAX * max(0.0, min(1.0, decay))


def _prep_roster(rosters: list[dict]) -> pd.DataFrame:
    """Roster rows as a DataFrame, with excluded positions (defense) dropped."""
    roster_df = pd.DataFrame(
        rosters, columns=["espn_team_id", "player_id", "player_name", "position", "total_points", "avg_points"]
    )
    if roster_df.empty:
        return roster_df
    return roster_df[~roster_df["position"].isin(EXCLUDED_POSITIONS)].copy()


def _score_rosters(
    roster_df: pd.DataFrame, draft_pick_by_player: dict, total_picks: int, draft_confidence: float
) -> pd.DataFrame:
    """Adds per-player position_percentile, position_value (z-score),
    expected_position_value, adjusted_value (the two blended by
    draft_confidence), position_weight, weighted_value, draft_percentile
    and value_over_adp columns to a copy of roster_df. Assumes excluded
    positions have already been dropped."""
    roster = roster_df.copy()
    roster["position_percentile"] = roster.groupby("position")["total_points"].transform(_percentile)
    roster["position_rank"] = roster.groupby("position")["total_points"].rank(
        ascending=False, method="min"
    ).astype(int)
    roster["position_value"] = _position_value_z(roster)
    roster["position_weight"] = roster["position"].map(POSITION_WEIGHTS).fillna(DEFAULT_POSITION_WEIGHT)

    total_picks = max(total_picks, 1)
    roster["draft_pick"] = roster["player_id"].map(draft_pick_by_player).fillna(total_picks + 1)
    # 1st overall -> 100 (highest draft capital); undrafted -> 0 (no expectations at all).
    roster["draft_percentile"] = ((1 - (roster["draft_pick"] - 1) / total_picks) * 100).clip(0, 100)
    roster["value_over_adp"] = roster["position_percentile"] - roster["draft_percentile"]

    roster["expected_position_value"] = _expected_position_value(roster)
    roster["adjusted_value"] = (
        draft_confidence * roster["expected_position_value"] + (1 - draft_confidence) * roster["position_value"]
    )
    roster["weighted_value"] = roster["adjusted_value"] * roster["position_weight"]
    return roster


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
        avg_points - one row per currently-rostered player (D/ST rows are
        ignored - see EXCLUDED_POSITIONS)
    draft_picks: player_id, overall_pick - this season's draft, in pick order
    """
    teams_df = pd.DataFrame(teams)
    if teams_df.empty:
        return teams_df, {"roster_weight": ROSTER_WEIGHT, "draft_confidence": DRAFT_CONFIDENCE_MAX}

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

    draft_confidence = draft_confidence_weight(current_week, reg_season_weeks)
    draft_pick_by_player = {d["player_id"]: d["overall_pick"] for d in draft_picks}
    total_picks = max((d["overall_pick"] for d in draft_picks), default=0)
    roster_df = _prep_roster(rosters)
    if not roster_df.empty:
        roster_df = _score_rosters(roster_df, draft_pick_by_player, total_picks, draft_confidence)
        # Summed (not averaged) so a team stacked with valuable talent at
        # RB/WR/QB/TE outscores one that's merely average across the board -
        # depth at the positions that matter is itself a real advantage.
        roster_talent_raw = roster_df.groupby("espn_team_id")["weighted_value"].sum()
    else:
        roster_talent_raw = pd.Series(dtype=float)

    teams_df["roster_talent_raw"] = teams_df["espn_team_id"].map(roster_talent_raw).fillna(0.0)
    teams_df["roster_talent_score"] = _percentile(teams_df["roster_talent_raw"])

    teams_df["power_score"] = (
        teams_df["record_score"] * RECORD_WEIGHT
        + teams_df["points_score"] * POINTS_WEIGHT
        + teams_df["sos_score"] * SOS_WEIGHT
        + teams_df["roster_talent_score"] * ROSTER_WEIGHT
    ) / 100.0

    teams_df = teams_df.sort_values("power_score", ascending=False).reset_index(drop=True)
    teams_df["rank"] = teams_df.index + 1
    weights = {
        "record_weight": RECORD_WEIGHT,
        "points_weight": POINTS_WEIGHT,
        "sos_weight": SOS_WEIGHT,
        "roster_weight": ROSTER_WEIGHT,
        "draft_confidence": draft_confidence,
    }
    return teams_df, weights


def team_highlights(
    rosters: list[dict], draft_picks: list[dict], current_week: int, reg_season_weeks: int
) -> pd.DataFrame:
    """Per team: best player (by the same draft-confidence-adjusted value
    the score uses), and best value-over-ADP pick (a plain rank comparison,
    shown for color - "your league's biggest steal so far").

    Backs a "why this ranking" readout under the leaderboard - the
    user-facing version of the 1.1-RB-vs-12th-round-RB example. Defense is
    excluded (see EXCLUDED_POSITIONS), same as the score itself.
    """
    roster_df = _prep_roster(rosters)
    if roster_df.empty:
        return pd.DataFrame(
            columns=[
                "espn_team_id", "best_player_name", "best_player_position", "best_player_rank",
                "value_player_name", "value_player_position", "value_player_pick", "value_over_adp",
            ]
        )

    draft_pick_by_player = {d["player_id"]: d["overall_pick"] for d in draft_picks}
    total_picks = max((d["overall_pick"] for d in draft_picks), default=0)
    draft_confidence = draft_confidence_weight(current_week, reg_season_weeks)
    roster_df = _score_rosters(roster_df, draft_pick_by_player, total_picks, draft_confidence)

    rows = []
    for team_id, group in roster_df.groupby("espn_team_id"):
        best = group.loc[group["adjusted_value"].idxmax()]
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
