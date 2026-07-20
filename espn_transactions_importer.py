"""
ESPN Fantasy Football transactions importer.

Downloads every add, drop, waiver claim (with FAAB bid), and trade event
for one or more seasons, and saves:
  - the raw JSON ESPN returned (data/raw/)
  - a clean, flat CSV ready for analysis (data/processed/)

ESPN only serves transactions one week at a time (scoringPeriodId), so
this script requests each week and stitches the season together. ESPN
retains transaction logs for this league from 2018 onward; earlier
seasons return nothing.

Run it with:
    python espn_transactions_importer.py 2024        # one season
    python espn_transactions_importer.py --all       # 2018 through 2025
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

PROJECT_DIR = Path(__file__).resolve().parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
FIRST_SEASON_WITH_DATA = 2018

# Transaction types we keep. DRAFT is already covered by the draft
# importer; FUTURE_ROSTER is keeper/next-season noise.
KEEP_TYPES = {
    "WAIVER",
    "FREEAGENT",
    "ROSTER",
    "TRADE_PROPOSAL",
    "TRADE_ACCEPT",
    "TRADE_DECLINE",
    "TRADE_UPHOLD",
    "TRADE_VETO",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download transaction history for an ESPN fantasy football league."
    )
    parser.add_argument("season", type=int, nargs="?", help="Season to fetch, e.g. 2024")
    parser.add_argument(
        "--all", action="store_true", help=f"Fetch every season from {FIRST_SEASON_WITH_DATA} on"
    )
    return parser.parse_args()


def load_credentials():
    load_dotenv(PROJECT_DIR / ".env")
    league_id = os.getenv("LEAGUE_ID")
    if not league_id:
        sys.exit("ERROR: LEAGUE_ID missing from .env (see README.md).")
    swid = os.getenv("SWID") or None
    espn_s2 = os.getenv("ESPN_S2") or None
    return league_id, espn_s2, swid


def fetch_week(league_id, season, week, cookies):
    """One week's transactions, raw from ESPN."""
    if season >= 2018:
        url = f"{BASE}/seasons/{season}/segments/0/leagues/{league_id}"
        params = {"view": "mTransactions2", "scoringPeriodId": week}
    else:
        url = f"{BASE}/leagueHistory/{league_id}"
        params = {"seasonId": season, "view": "mTransactions2", "scoringPeriodId": week}
    resp = requests.get(url, params=params, cookies=cookies, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data.get("transactions", []) or []


def build_player_map(league_id, season, espn_s2, swid):
    """playerId -> player name, via the espn_api library."""
    try:
        league = League(league_id=int(league_id), year=season, espn_s2=espn_s2, swid=swid)
        # player_map maps both id->name and name->id; keep only id keys.
        return {k: v for k, v in league.player_map.items() if isinstance(k, int)}
    except Exception as exc:
        print(f"WARNING: could not build {season} player map ({exc}); names will be blank.")
        return {}


def flatten(transactions, season, player_map):
    """One row per player moved (or per transaction if it has no items)."""
    rows = []
    for t in transactions:
        if t.get("type") not in KEEP_TYPES:
            continue
        base = {
            "season": season,
            "week": t.get("scoringPeriodId"),
            "transaction_id": t.get("id"),
            # Links follow-up events (TRADE_UPHOLD, TRADE_VETO) back to the
            # TRADE_ACCEPT that holds the actual players. A trade is executed
            # if an UPHOLD points at it.
            "related_transaction_id": t.get("relatedTransactionId"),
            "transaction_type": t.get("type"),
            "status": t.get("status"),
            "espn_team_id": t.get("teamId"),
            "bid_amount": t.get("bidAmount", 0),
            "date_ms": t.get("proposedDate"),
        }
        items = t.get("items") or []
        if not items:
            rows.append({**base, "item_type": None, "player_id": None,
                         "player_name": None, "from_team_id": None, "to_team_id": None})
            continue
        for item in items:
            player_id = item.get("playerId")
            rows.append(
                {
                    **base,
                    "item_type": item.get("type"),
                    "player_id": player_id,
                    "player_name": player_map.get(player_id),
                    "from_team_id": item.get("fromTeamId"),
                    "to_team_id": item.get("toTeamId"),
                }
            )
    return rows


def import_season(league_id, season, espn_s2, swid):
    cookies = {"SWID": swid, "espn_s2": espn_s2}
    all_raw = []
    seen_ids = set()
    for week in range(0, 20):  # 0 catches preseason moves; 19 covers late playoffs
        try:
            weekly = fetch_week(league_id, season, week, cookies)
        except requests.RequestException as exc:
            print(f"  WARNING: {season} week {week} failed ({exc}); skipping.")
            continue
        for t in weekly:
            # The same transaction can show up under multiple weeks; keep one.
            t_id = t.get("id")
            if t_id in seen_ids:
                continue
            seen_ids.add(t_id)
            all_raw.append(t)

    if not all_raw:
        print(f"{season}: no transaction data (ESPN retains nothing before {FIRST_SEASON_WITH_DATA}).")
        return

    player_map = build_player_map(league_id, season, espn_s2, swid)
    rows = flatten(all_raw, season, player_map)

    season_tag = f"league_{league_id}_season_{season}"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(RAW_DIR / f"{season_tag}_raw_transactions.json", "w", encoding="utf-8") as f:
        json.dump(all_raw, f, indent=2, default=str)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date_ms"], unit="ms").dt.strftime("%Y-%m-%d")
    df = df.drop(columns=["date_ms"])
    df.to_csv(PROCESSED_DIR / f"{season_tag}_transactions.csv", index=False)

    executed = df[df["status"] == "EXECUTED"]
    upheld_ids = set(
        executed[executed["transaction_type"] == "TRADE_UPHOLD"]["related_transaction_id"].dropna()
    )
    n_trades = df[df["transaction_id"].isin(upheld_ids)]["transaction_id"].nunique()
    n_waivers = executed[executed["transaction_type"] == "WAIVER"]["transaction_id"].nunique()
    faab = int(
        executed[executed["transaction_type"] == "WAIVER"]
        .drop_duplicates("transaction_id")["bid_amount"].sum()
    )
    unresolved = df["player_id"].notna() & df["player_name"].isna()
    print(
        f"{season}: {df['transaction_id'].nunique()} transactions "
        f"({n_trades} executed trades, {n_waivers} waiver claims, ${faab} FAAB). "
        f"{int(unresolved.sum())} unresolved player names."
    )


def main():
    args = parse_args()
    league_id, espn_s2, swid = load_credentials()

    if args.all:
        seasons = range(FIRST_SEASON_WITH_DATA, 2026)
    elif args.season:
        seasons = [args.season]
    else:
        sys.exit("ERROR: give a season (e.g. 2024) or --all.")

    for season in seasons:
        import_season(league_id, season, espn_s2, swid)

    print(f"\nRaw JSON saved to:  {RAW_DIR}")
    print(f"Clean CSV saved to: {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
