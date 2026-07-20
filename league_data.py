"""
Data loading and statistics for the league history dashboard.

Everything in this file is plain pandas - no Streamlit. app.py imports these
functions to display results, and any future tool (a bot, a report script)
can reuse them the same way.

All stats are grouped by REAL manager using manager_mapping.csv, never by
ESPN team ID, because teams changed hands over the years.
"""

import hashlib
import json
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
RAW_DIR = PROJECT_DIR / "data" / "raw"
MAPPING_FILE = PROJECT_DIR / "manager_mapping.csv"


def data_fingerprint() -> str:
    """Hash of every data file's path and modification time.

    Used as the cache key for the app's data loads, so any change to
    manager_mapping.csv or the processed CSVs automatically invalidates
    Streamlit's cache - no manual version bumping.
    """
    digest = hashlib.md5()
    paths = [MAPPING_FILE] + sorted(PROCESSED_DIR.glob("*.csv"))
    for path in paths:
        if path.exists():
            digest.update(str(path).encode())
            digest.update(str(path.stat().st_mtime_ns).encode())
    return digest.hexdigest()


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


def load_transactions() -> pd.DataFrame:
    """One row per player moved (or event), with the acting manager attached.

    Covers 2018+ only - ESPN retains no transaction logs for this league's
    earlier seasons.
    """
    tx = _load_concat("*_transactions.csv")
    # Some 2018 events have a missing acting team id (ESPN's int-min
    # sentinel). The item itself still knows the team: ADDs go to a team,
    # DROPs come from one. Everything goes through nullable Int64 so the
    # float fallback columns never fight the int id column over dtype.
    team = tx["espn_team_id"].astype("Int64")
    fallback = (
        tx["to_team_id"]
        .where(tx["item_type"] == "ADD", tx["from_team_id"])
        .astype("Int64")
    )
    tx["espn_team_id"] = team.mask((team <= 0) | team.isna(), fallback)
    mapping = load_mapping()
    mapping["espn_team_id"] = mapping["espn_team_id"].astype("Int64")
    return tx.merge(mapping, on=["season", "espn_team_id"], how="left")


def executed_trades(transactions: pd.DataFrame) -> pd.DataFrame:
    """One row per completed trade, with the players each side received.

    ESPN stores trade player detail inconsistently across eras (sometimes on
    the accept event, sometimes on the upheld proposal), so this collects
    every executed trade that has player detail anywhere. A few old trades
    may be missing entirely - ESPN's log, not ours.
    """
    mapping = load_mapping().set_index(["season", "espn_team_id"])["manager"]

    upheld_refs = set(
        transactions.loc[
            transactions["transaction_type"] == "TRADE_UPHOLD",
            "related_transaction_id",
        ].dropna()
    )
    items = transactions[transactions["item_type"] == "TRADE"]
    executed_ids = set(
        items.loc[items["transaction_type"] == "TRADE_ACCEPT", "transaction_id"]
    )
    executed_ids |= set(
        items.loc[items["transaction_type"] == "TRADE_UPHOLD", "transaction_id"]
    )
    executed_ids |= set(items["transaction_id"]) & upheld_refs

    rows = []
    for trade_id in executed_ids:
        trade_items = items[items["transaction_id"] == trade_id]
        first = trade_items.iloc[0]
        season = int(first["season"])
        # Group players by the team receiving them.
        sides = {}
        for _, item in trade_items.iterrows():
            to_team = int(item["to_team_id"])
            sides.setdefault(to_team, []).append(item["player_name"] or "?")
        if len(sides) < 2:
            continue  # one-sided/corrupt entry, not a real trade
        team_ids = sorted(sides)
        managers = [mapping.get((season, tid), f"team {tid}") for tid in team_ids]
        rows.append(
            {
                "season": season,
                "week": int(first["week"]),
                "date": first["date"],
                "manager_a": managers[0],
                "received_a": ", ".join(sorted(sides[team_ids[0]])),
                "manager_b": managers[1],
                "received_b": ", ".join(sorted(sides[team_ids[1]])),
            }
        )
    # The same trade can be recorded under both its accept event and its
    # upheld proposal - identical players/teams/week means one trade.
    return (
        pd.DataFrame(rows)
        .drop_duplicates(
            ["season", "week", "manager_a", "received_a", "manager_b", "received_b"]
        )
        .sort_values(["season", "week"], ascending=False)
        .reset_index(drop=True)
    )


def faab_bids(transactions: pd.DataFrame) -> pd.DataFrame:
    """Every winning FAAB bid: who paid what for which player."""
    waivers = transactions[
        (transactions["transaction_type"] == "WAIVER")
        & (transactions["status"] == "EXECUTED")
        & (transactions["item_type"] == "ADD")
    ]
    bids = waivers[["season", "week", "date", "manager", "player_name", "bid_amount"]]
    return bids.sort_values("bid_amount", ascending=False).reset_index(drop=True)


# NOTE: a per-manager "trade negotiations" table (proposals sent, declines
# issued) was built and removed: ESPN's mTransactions2 view personalizes
# trade proposal/accept detail to the logged-in account, so with one login
# the counts are complete for that manager and badly undercounted for
# everyone else. Revisit if multiple managers' credentials are collected.


def transaction_log(transactions: pd.DataFrame) -> pd.DataFrame:
    """Every executed roster move as one readable row.

    action is one of:
      Waiver claim       - added off waivers (bid_amount = FAAB paid)
      Free agent pickup  - added as a free agent
      Drop               - dropped to waivers/free agency
    """
    executed = transactions[transactions["status"] == "EXECUTED"]

    adds = executed[
        executed["transaction_type"].isin(["WAIVER", "FREEAGENT"])
        & (executed["item_type"] == "ADD")
    ].copy()
    adds["action"] = adds["transaction_type"].map(
        {"WAIVER": "Waiver claim", "FREEAGENT": "Free agent pickup"}
    )

    drops = executed[
        executed["transaction_type"].isin(["WAIVER", "FREEAGENT", "ROSTER"])
        & (executed["item_type"] == "DROP")
    ].copy()
    drops["action"] = "Drop"
    drops["bid_amount"] = 0  # a bid belongs to the claim, not the drop

    log = pd.concat([adds, drops], ignore_index=True)
    log = log[["season", "week", "date", "manager", "action", "player_name", "bid_amount"]]
    return log.sort_values(
        ["season", "week", "date"], ascending=False
    ).reset_index(drop=True)


def transaction_activity(transactions: pd.DataFrame) -> pd.DataFrame:
    """Career transaction counts per manager (2018+): adds, drops, FAAB spent."""
    executed = transactions[transactions["status"] == "EXECUTED"]
    adds = executed[
        executed["transaction_type"].isin(["WAIVER", "FREEAGENT"])
        & (executed["item_type"] == "ADD")
    ]
    drops = executed[
        executed["transaction_type"].isin(["WAIVER", "FREEAGENT", "ROSTER"])
        & (executed["item_type"] == "DROP")
    ]
    waiver_adds = adds[adds["transaction_type"] == "WAIVER"]

    result = pd.DataFrame(
        {
            "adds": adds.groupby("manager").size(),
            "drops": drops.groupby("manager").size(),
            "waiver_claims": waiver_adds.groupby("manager").size(),
            "faab_spent": waiver_adds.groupby("manager")["bid_amount"].sum(),
        }
    ).fillna(0).astype(int)
    return (
        result.sort_values("adds", ascending=False)
        .reset_index()
        .rename(columns={"index": "manager"})
    )


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
