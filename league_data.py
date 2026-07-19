"""
Data loading and statistics for the league history dashboard.

Everything in this file is plain pandas - no Streamlit. app.py imports these
functions to display results, and any future tool (a bot, a report script)
can reuse them the same way.

All stats are grouped by REAL manager using manager_mapping.csv, never by
ESPN team ID, because teams changed hands over the years.
"""

import json
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
RAW_DIR = PROJECT_DIR / "data" / "raw"
MAPPING_FILE = PROJECT_DIR / "manager_mapping.csv"


def _load_concat(pattern: str) -> pd.DataFrame:
    files = sorted(PROCESSED_DIR.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"No files matching {pattern} in {PROCESSED_DIR}. "
            "Run espn_history_importer.py first."
        )
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def load_mapping() -> pd.DataFrame:
    if not MAPPING_FILE.exists():
        raise FileNotFoundError(
            "manager_mapping.csv not found. Run generate_manager_mapping.py first."
        )
    mapping = pd.read_csv(MAPPING_FILE)
    # Fall back to the ESPN username (or a placeholder) for unmapped rows so
    # they still show up in every screen instead of disappearing.
    mapping["manager"] = (
        mapping["manager"].fillna(mapping["owner_names"]).fillna("Unknown")
    )
    return mapping[["season", "espn_team_id", "manager"]]


def load_teams() -> pd.DataFrame:
    """One row per team-season, with the real manager attached.

    Applies playoff rule: top 6 (by regular season) use playoff placement as final_standing;
    those finishing outside top 6 keep regular_season_standing as their final_standing.
    """
    teams = _load_concat("*_teams.csv")
    teams = teams.merge(load_mapping(), on=["season", "espn_team_id"], how="left")

    # Apply the playoff rule to final_standing
    teams["final_standing"] = teams.apply(
        lambda row: row["final_standing"]
        if row["regular_season_standing"] <= 6
        else row["regular_season_standing"],
        axis=1,
    )
    return teams


def _playoff_team_counts() -> dict:
    """Season -> number of playoff teams, read from the saved raw ESPN JSON."""
    counts = {}
    for f in RAW_DIR.glob("*_raw_league.json"):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            season = data["seasonId"]
            counts[season] = data["settings"]["scheduleSettings"]["playoffTeamCount"]
        except (KeyError, json.JSONDecodeError):
            continue
    return counts


def load_matchups() -> pd.DataFrame:
    """One row per team per week, with manager names and game type attached.

    game_type is one of:
      regular      - a regular season game
      playoff      - playoff weeks, both teams qualified (winners bracket)
      consolation  - playoff weeks, at least one team missed the playoffs
    """
    matchups = _load_concat("*_matchups.csv")
    mapping = load_mapping()
    matchups = matchups.merge(mapping, on=["season", "espn_team_id"], how="left")
    matchups = matchups.merge(
        mapping.rename(
            columns={"espn_team_id": "opponent_espn_team_id", "manager": "opponent_manager"}
        ),
        on=["season", "opponent_espn_team_id"],
        how="left",
    )
    # Drop byes and undecided/unplayed weeks - they aren't real results.
    played = matchups["outcome"].isin(["W", "L", "T"])
    has_opponent = matchups["opponent_espn_team_id"].notna()
    matchups = matchups[played & has_opponent].copy()

    # Classify playoff-week games. League rule: a game is only a "playoff"
    # game if BOTH teams can still win the championship. That means both
    # qualified for the playoffs AND have not lost a playoff game yet this
    # postseason. Everything else in the playoff weeks (non-qualifiers,
    # 3rd-place games, losers bracket) is a consolation game.
    teams = _load_concat("*_teams.csv")
    seeds = teams.set_index(["season", "espn_team_id"])["regular_season_standing"]
    cutoffs = _playoff_team_counts()

    matchups["game_type"] = "regular"
    playoff_rows = matchups[matchups["is_playoff_week"]]
    for season in playoff_rows["season"].unique():
        cutoff = cutoffs.get(season)
        season_rows = playoff_rows[playoff_rows["season"] == season]
        if cutoff is None:
            # No saved settings for this season; count everything as playoff.
            matchups.loc[season_rows.index, "game_type"] = "playoff"
            continue
        # Start with the playoff qualifiers, then knock out each round's losers.
        alive = {
            team_id
            for (s, team_id), seed in seeds.items()
            if s == season and seed <= cutoff
        }
        for week in sorted(season_rows["week"].unique()):
            week_rows = season_rows[season_rows["week"] == week]
            eliminated = set()
            for idx, row in week_rows.iterrows():
                opponent_id = int(row["opponent_espn_team_id"])
                if row["espn_team_id"] in alive and opponent_id in alive:
                    matchups.loc[idx, "game_type"] = "playoff"
                    if row["outcome"] == "L":
                        eliminated.add(row["espn_team_id"])
                else:
                    matchups.loc[idx, "game_type"] = "consolation"
            alive -= eliminated
    return matchups


def load_draft() -> pd.DataFrame:
    draft = _load_concat("*_draft.csv")
    return draft.merge(load_mapping(), on=["season", "espn_team_id"], how="left")


def manager_career_standings(
    teams: pd.DataFrame, matchups: pd.DataFrame, game_types: list = None
) -> pd.DataFrame:
    """All-time record per real manager, computed game by game.

    game_types picks which games count toward W/L/T and points, e.g.
    ["regular", "playoff"]. Defaults to regular season + real playoff games
    (no consolation). Seasons and championships always come from the
    season-level data regardless of the filter.
    """
    if game_types is None:
        game_types = ["regular", "playoff"]
    games = matchups[matchups["game_type"].isin(game_types)]

    records = (
        games.groupby("manager")
        .agg(
            wins=("outcome", lambda s: int((s == "W").sum())),
            losses=("outcome", lambda s: int((s == "L").sum())),
            ties=("outcome", lambda s: int((s == "T").sum())),
            points_for=("team_score", "sum"),
            points_against=("opponent_score", "sum"),
        )
        .reset_index()
    )

    seasons_info = (
        teams.groupby("manager")
        .agg(
            seasons=("season", "nunique"),
            first_season=("season", "min"),
            last_season=("season", "max"),
            championships=("final_standing", lambda s: int((s == 1).sum())),
        )
        .reset_index()
    )

    per_manager = seasons_info.merge(records, on="manager", how="left")
    for col in ["wins", "losses", "ties"]:
        per_manager[col] = per_manager[col].fillna(0).astype(int)
    for col in ["points_for", "points_against"]:
        per_manager[col] = per_manager[col].fillna(0.0)

    total = per_manager["wins"] + per_manager["losses"] + per_manager["ties"]
    per_manager["win_pct"] = (
        ((per_manager["wins"] + 0.5 * per_manager["ties"]) / total.where(total > 0))
        .fillna(0)
        .round(3)
    )
    return per_manager.sort_values(
        ["championships", "win_pct"], ascending=False
    ).reset_index(drop=True)


def season_standings(teams: pd.DataFrame, season: int) -> pd.DataFrame:
    """Final standings for one season."""
    one = teams[teams["season"] == season].copy()
    one = one.sort_values("final_standing")
    return one[
        [
            "final_standing",
            "regular_season_standing",
            "team_name",
            "manager",
            "wins",
            "losses",
            "ties",
            "points_for",
            "points_against",
        ]
    ].reset_index(drop=True)


def head_to_head(matchups: pd.DataFrame, game_types: list = None) -> pd.DataFrame:
    """Grid of win-loss-tie records: row manager vs column manager.

    game_types picks which games count, e.g. ["regular", "playoff"].
    Defaults to regular season + real playoff games (no consolation).
    """
    if game_types is None:
        game_types = ["regular", "playoff"]
    games = matchups[matchups["game_type"].isin(game_types)]
    managers = sorted(set(games["manager"].dropna()) | set(games["opponent_manager"].dropna()))
    grid = pd.DataFrame(index=managers, columns=managers, dtype=object)
    for row_mgr in managers:
        vs = games[games["manager"] == row_mgr]
        for col_mgr in managers:
            if row_mgr == col_mgr:
                grid.loc[row_mgr, col_mgr] = "-"
                continue
            h2h = vs[vs["opponent_manager"] == col_mgr]
            if h2h.empty:
                grid.loc[row_mgr, col_mgr] = ""
                continue
            w = int((h2h["outcome"] == "W").sum())
            l = int((h2h["outcome"] == "L").sum())
            t = int((h2h["outcome"] == "T").sum())
            grid.loc[row_mgr, col_mgr] = f"{w}-{l}-{t}" if t else f"{w}-{l}"
    return grid


def build_ask_context(teams: pd.DataFrame, matchups: pd.DataFrame, draft: pd.DataFrame) -> str:
    """Condense all league history into one compact text block for the LLM.

    Kept deliberately terse (one line per game/pick) to hold down API token
    costs while still letting the model answer any history question.
    """
    lines = ["# LEAGUE SEASONS (final standings)"]
    lines.append("season|final_standing|manager|team_name|W-L-T|PF|PA")
    for _, r in teams.sort_values(["season", "final_standing"]).iterrows():
        lines.append(
            f"{r.season}|{r.final_standing}|{r.manager}|{r.team_name}|"
            f"{r.wins}-{r.losses}-{r.ties}|{r.points_for:.1f}|{r.points_against:.1f}"
        )

    lines.append("\n# GAMES (one line per game; winner listed first except ties)")
    lines.append("season|week|type|winner|winner_pts|loser|loser_pts (type: R=regular P=playoff C=consolation)")
    type_code = {"regular": "R", "playoff": "P", "consolation": "C"}
    # Each game appears twice (once per team); keep the winner's row, or one
    # side of a tie, so every game is listed exactly once.
    games = matchups[
        (matchups["outcome"] == "W")
        | ((matchups["outcome"] == "T") & (matchups["espn_team_id"] < matchups["opponent_espn_team_id"]))
    ]
    for _, r in games.sort_values(["season", "week"]).iterrows():
        tie_marker = " TIE" if r.outcome == "T" else ""
        lines.append(
            f"{r.season}|{r.week}|{type_code[r.game_type]}|{r.manager}|{r.team_score}|"
            f"{r.opponent_manager}|{r.opponent_score}{tie_marker}"
        )

    lines.append("\n# DRAFT PICKS")
    lines.append("season|round.pick|player|manager")
    for _, r in draft.sort_values(["season", "overall_pick"]).iterrows():
        keeper = " (keeper)" if r.is_keeper else ""
        lines.append(f"{r.season}|{r['round']}.{r.pick_in_round}|{r.player_name}|{r.manager}{keeper}")

    return "\n".join(lines)


def cumulative_wins(matchups: pd.DataFrame, game_types: list = None) -> pd.DataFrame:
    """Career wins accumulated season by season, per manager.

    One row per manager per season they played, with running total wins.
    """
    if game_types is None:
        game_types = ["regular", "playoff"]
    games = matchups[matchups["game_type"].isin(game_types)]
    wins = (
        games[games["outcome"] == "W"]
        .groupby(["manager", "season"])
        .size()
        .rename("wins")
        .reset_index()
    )
    # Include seasons with zero wins so lines don't skip years.
    played = games.groupby(["manager", "season"]).size().rename("games").reset_index()
    wins = played.merge(wins, on=["manager", "season"], how="left").fillna({"wins": 0})
    wins = wins.sort_values(["manager", "season"])
    wins["cumulative_wins"] = wins.groupby("manager")["wins"].cumsum().astype(int)
    return wins[["manager", "season", "cumulative_wins"]]


def season_trophies(teams: pd.DataFrame, matchups: pd.DataFrame) -> pd.DataFrame:
    """One row per season with the three league awards.

    champion             - final_standing 1 (playoff bracket winner)
    regular_season_winner - regular_season_standing 1
    points_leader        - most total points in regular season games only
    best_week            - biggest single-week score of the season (the season's
                           standout weekly high; every week's winner is in
                           weekly_high_winners)
    """
    reg = matchups[matchups["game_type"] == "regular"]
    points = (
        reg.groupby(["season", "manager"])["team_score"].sum().reset_index()
    )

    rows = []
    for season in sorted(teams["season"].unique()):
        one = teams[teams["season"] == season]
        champ = one[one["final_standing"] == 1].iloc[0]
        reg_winner = one[one["regular_season_standing"] == 1].iloc[0]
        season_pts = points[points["season"] == season]
        leader = season_pts.loc[season_pts["team_score"].idxmax()]
        season_games = reg[reg["season"] == season]
        big_week = season_games.loc[season_games["team_score"].idxmax()]
        rows.append(
            {
                "season": season,
                "champion": champ["manager"],
                "champion_team": champ["team_name"],
                "regular_season_winner": reg_winner["manager"],
                "regular_season_record": f"{reg_winner['wins']}-{reg_winner['losses']}"
                + (f"-{reg_winner['ties']}" if reg_winner["ties"] else ""),
                "points_leader": leader["manager"],
                "points": round(leader["team_score"], 1),
                "best_week": big_week["manager"],
                "best_week_score": round(big_week["team_score"], 1),
                "best_week_number": int(big_week["week"]),
            }
        )
    return pd.DataFrame(rows)


def weekly_high_winners(matchups: pd.DataFrame) -> pd.DataFrame:
    """One row per regular season week: who scored the most points that week.

    Every regular season week hands out this award (13 weeks per season
    before the NFL's 18th week, 14 after). If two teams tie for the top
    score in a week, both get a row.
    """
    reg = matchups[matchups["game_type"] == "regular"]
    week_max = reg.groupby(["season", "week"])["team_score"].transform("max")
    winners = reg[reg["team_score"] == week_max]
    winners = winners[["season", "week", "manager", "team_score"]].copy()
    winners = winners.rename(columns={"team_score": "score"})
    winners["score"] = winners["score"].round(1)
    return winners.sort_values(["season", "week"]).reset_index(drop=True)


def trophy_case(trophies: pd.DataFrame, weekly_winners: pd.DataFrame) -> pd.DataFrame:
    """Career trophy counts per manager, sorted by championships."""
    managers = sorted(
        set(trophies["champion"])
        | set(trophies["regular_season_winner"])
        | set(trophies["points_leader"])
        | set(weekly_winners["manager"])
    )
    rows = []
    for manager in managers:
        rows.append(
            {
                "manager": manager,
                "championships": int((trophies["champion"] == manager).sum()),
                "regular_season_titles": int(
                    (trophies["regular_season_winner"] == manager).sum()
                ),
                "points_titles": int((trophies["points_leader"] == manager).sum()),
                "weekly_highs": int((weekly_winners["manager"] == manager).sum()),
            }
        )
    result = pd.DataFrame(rows)
    result["total"] = (
        result["championships"]
        + result["regular_season_titles"]
        + result["points_titles"]
        + result["weekly_highs"]
    )
    return result.sort_values(
        ["championships", "total"], ascending=False
    ).reset_index(drop=True)


def draft_table(draft: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "season",
        "round",
        "pick_in_round",
        "overall_pick",
        "player_name",
        "manager",
        "team_name",
        "is_keeper",
    ]
    return draft[cols].sort_values(["season", "overall_pick"]).reset_index(drop=True)
