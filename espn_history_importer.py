"""
ESPN Fantasy Football history importer.

Connects to one ESPN fantasy football league for one season, and saves:
  - the raw JSON ESPN returned (data/raw/)
  - clean, flat CSV and JSON files ready for analysis (data/processed/)

Run it with:
    python espn_history_importer.py 2019

See README.md for full setup instructions.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from espn_api.football import League
from espn_api.requests.espn_requests import (
    ESPNAccessDenied,
    ESPNInvalidLeague,
    ESPNUnknownError,
)

PROJECT_DIR = Path(__file__).resolve().parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download one historical season of an ESPN fantasy football league."
    )
    parser.add_argument(
        "season",
        type=int,
        help="The season (year) to retrieve, e.g. 2019",
    )
    return parser.parse_args()


def load_credentials():
    """Read LEAGUE_ID, SWID, and ESPN_S2 out of the local .env file."""
    load_dotenv(PROJECT_DIR / ".env")

    league_id_raw = os.getenv("LEAGUE_ID")
    if not league_id_raw:
        sys.exit(
            "ERROR: LEAGUE_ID is missing.\n"
            "Create a file named '.env' in the project folder (copy .env.example to .env)\n"
            "and set LEAGUE_ID=<your league id>. See README.md for details."
        )
    try:
        league_id = int(league_id_raw)
    except ValueError:
        sys.exit(
            f"ERROR: LEAGUE_ID in your .env file must be a number, got '{league_id_raw}'."
        )

    # SWID/ESPN_S2 are only required for private leagues. Empty strings are
    # treated the same as "not provided" so public leagues can leave them blank.
    swid = os.getenv("SWID") or None
    espn_s2 = os.getenv("ESPN_S2") or None

    return league_id, espn_s2, swid


def connect_to_league(league_id, season, espn_s2, swid):
    """Create the espn_api League object, translating errors into plain English."""
    try:
        return League(
            league_id=league_id,
            year=season,
            espn_s2=espn_s2,
            swid=swid,
        )
    except ESPNAccessDenied:
        sys.exit(
            "ERROR: ESPN denied access to this league.\n"
            "This usually means the league is private and your SWID/ESPN_S2 values\n"
            "in .env are missing, incorrect, or expired. See README.md for how to\n"
            "find fresh values in your browser cookies, then try again."
        )
    except ESPNInvalidLeague:
        sys.exit(
            f"ERROR: ESPN could not find league {league_id} for the {season} season.\n"
            "Double-check the LEAGUE_ID in your .env file, and confirm this league\n"
            f"existed (or that you were a member of it) during the {season} season."
        )
    except ESPNUnknownError as exc:
        sys.exit(f"ERROR: ESPN returned an unexpected response: {exc}")
    except requests.exceptions.RequestException as exc:
        sys.exit(
            "ERROR: Could not reach ESPN's servers. Check your internet connection\n"
            f"and try again. Details: {exc}"
        )
    except KeyError as exc:
        sys.exit(
            f"ERROR: ESPN's response for the {season} season was missing expected\n"
            f"field {exc}. Very old seasons are sometimes stored in a format this\n"
            "tool (and the espn_api library) does not understand."
        )


def owner_display_name(owner: dict) -> str:
    display_name = owner.get("displayName")
    if display_name:
        return display_name
    full_name = f"{owner.get('firstName', '')} {owner.get('lastName', '')}".strip()
    return full_name or "Unknown"


def build_team_records(league) -> list:
    """One row per ESPN team: identity, owners, record, points, standings."""
    rows = []
    for team in league.teams:
        owners = team.owners or []
        rows.append(
            {
                "season": league.year,
                "espn_team_id": team.team_id,
                "team_name": team.team_name,
                "division_name": team.division_name,
                # Owner IDs are stable ESPN member GUIDs. Keep them alongside the
                # display name so a future manual manager-mapping step has a
                # reliable key to join on, since display names can change and
                # a team_id can be inherited by a different real-life manager.
                "owner_names": "; ".join(owner_display_name(o) for o in owners) or None,
                "owner_ids": "; ".join(o.get("id", "") for o in owners) or None,
                "wins": team.wins,
                "losses": team.losses,
                "ties": team.ties,
                "points_for": team.points_for,
                "points_against": team.points_against,
                "regular_season_standing": team.standing,
                "final_standing": team.final_standing,
            }
        )
    return rows


def build_weekly_matchups(league) -> list:
    """One row per team per week: opponent, both scores, and win/loss/tie outcome."""
    rows = []
    reg_season_weeks = league.settings.reg_season_count
    for team in league.teams:
        for week_index, opponent in enumerate(team.schedule):
            week = week_index + 1
            team_score = team.scores[week_index] if week_index < len(team.scores) else None
            outcome = team.outcomes[week_index] if week_index < len(team.outcomes) else None

            if opponent is None:
                opponent_id, opponent_name, opponent_score = None, "BYE", None
            else:
                opponent_id = opponent.team_id
                opponent_name = opponent.team_name
                opponent_score = (
                    opponent.scores[week_index] if week_index < len(opponent.scores) else None
                )

            rows.append(
                {
                    "season": league.year,
                    "week": week,
                    "is_playoff_week": week > reg_season_weeks,
                    "espn_team_id": team.team_id,
                    "team_name": team.team_name,
                    "opponent_espn_team_id": opponent_id,
                    "opponent_team_name": opponent_name,
                    "team_score": team_score,
                    "opponent_score": opponent_score,
                    "outcome": outcome,
                }
            )
    return rows


def build_draft_rows(league) -> list:
    """One row per draft pick, in the order the draft actually happened."""
    rows = []
    for overall_pick, pick in enumerate(league.draft, start=1):
        rows.append(
            {
                "season": league.year,
                "overall_pick": overall_pick,
                "round": pick.round_num,
                "pick_in_round": pick.round_pick,
                "espn_team_id": pick.team.team_id if pick.team else None,
                "team_name": pick.team.team_name if pick.team else None,
                "player_id": pick.playerId,
                "player_name": pick.playerName,
                "is_keeper": pick.keeper_status,
                "bid_amount": pick.bid_amount,
            }
        )
    return rows


def fetch_raw_payloads(league) -> dict:
    """Re-request the raw JSON ESPN sent, so we keep an untouched copy on disk."""
    raw = {"league": None, "draft": None}
    try:
        raw["league"] = league.espn_request.get_league()
    except Exception as exc:  # pragma: no cover - defensive, network dependent
        print(f"WARNING: could not save raw league JSON: {exc}")
    try:
        raw["draft"] = league.espn_request.get_league_draft()
    except Exception as exc:  # pragma: no cover - defensive, network dependent
        print(f"WARNING: could not save raw draft JSON: {exc}")
    return raw


def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def save_csv(rows: list, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def print_summary(team_rows, matchup_rows, draft_rows):
    print("\nTeams (regular_season_standing / final_standing):")
    for row in sorted(team_rows, key=lambda r: (r["final_standing"] or 999)):
        print(
            f"  #{row['final_standing']:>2} {row['team_name']:<25} "
            f"({row['owner_names'] or 'no owner listed'}) "
            f"{row['wins']}-{row['losses']}-{row['ties']}  "
            f"PF {row['points_for']:.1f} / PA {row['points_against']:.1f}"
        )
    print(f"\nSaved {len(matchup_rows)} weekly matchup rows.")
    if draft_rows:
        print(f"Saved {len(draft_rows)} draft picks.")
    else:
        print("No draft data was found for this season (draft may not have used ESPN's draft tool).")


def main():
    args = parse_args()
    season = args.season

    league_id, espn_s2, swid = load_credentials()
    league = connect_to_league(league_id, season, espn_s2, swid)

    if not league.teams:
        sys.exit(
            f"ERROR: League {league_id} returned no teams for the {season} season.\n"
            "This usually means the season had not started yet, or the league\n"
            "did not exist for that year."
        )

    season_tag = f"league_{league_id}_season_{season}"

    raw_payloads = fetch_raw_payloads(league)
    save_json(raw_payloads["league"], RAW_DIR / f"{season_tag}_raw_league.json")
    if raw_payloads["draft"] is not None:
        save_json(raw_payloads["draft"], RAW_DIR / f"{season_tag}_raw_draft.json")

    team_rows = build_team_records(league)
    matchup_rows = build_weekly_matchups(league)
    draft_rows = build_draft_rows(league)

    save_json(team_rows, PROCESSED_DIR / f"{season_tag}_teams.json")
    save_csv(team_rows, PROCESSED_DIR / f"{season_tag}_teams.csv")

    save_json(matchup_rows, PROCESSED_DIR / f"{season_tag}_matchups.json")
    save_csv(matchup_rows, PROCESSED_DIR / f"{season_tag}_matchups.csv")

    save_json(draft_rows, PROCESSED_DIR / f"{season_tag}_draft.json")
    save_csv(draft_rows, PROCESSED_DIR / f"{season_tag}_draft.csv")

    print(f"Connected to '{league.settings.name}' - {season} season.")
    print_summary(team_rows, matchup_rows, draft_rows)
    print(f"\nRaw JSON saved to:       {RAW_DIR}")
    print(f"Clean CSV/JSON saved to: {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
