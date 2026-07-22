"""
Backfill player positions for the draft history.

The draft CSVs (from espn_history_importer.py) never captured player
position, because ESPN's draft endpoint doesn't return it - only the
player's name and id. This script collects every unique player_id ever
drafted, batch-resolves position via ESPN's player card endpoint, and
saves a lookup table that league_data.py merges into the draft data and
the Ask the League context.

Position is a fixed fact about a player (RB, WR, etc.) - it doesn't
change season to season - so one lookup per player covers every pick.

Run it with:
    python build_player_positions.py
"""

import glob
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from espn_api.football import League

PROJECT_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
OUTPUT_FILE = PROCESSED_DIR / "player_positions.csv"
BATCH_SIZE = 300


def main():
    load_dotenv(PROJECT_DIR / ".env")
    league_id = os.getenv("LEAGUE_ID")
    swid = os.getenv("SWID") or None
    espn_s2 = os.getenv("ESPN_S2") or None
    if not league_id:
        sys.exit("ERROR: LEAGUE_ID missing from .env (see README.md).")

    draft_files = sorted(PROCESSED_DIR.glob("*_draft.csv"))
    if not draft_files:
        sys.exit("ERROR: no *_draft.csv files found. Run espn_history_importer.py first.")
    draft = pd.concat([pd.read_csv(f) for f in draft_files], ignore_index=True)
    seasons_by_player = draft.groupby("player_id")["season"].apply(set).to_dict()
    all_ids = set(draft["player_id"].dropna().astype(int).unique().tolist())
    print(f"{len(all_ids)} unique drafted players to resolve.")

    # ESPN's player-card endpoint only returns players it considers relevant
    # to the requesting League object's season (e.g. rostered/had stats that
    # year) - a long-retired player looked up via a 2025 League often comes
    # back empty. Position never changes, so fall back through each season
    # that player was actually drafted in, newest first, until resolved.
    rows = {}
    unresolved = set(all_ids)
    seasons_present = sorted(draft["season"].unique(), reverse=True)
    for season in seasons_present:
        if not unresolved:
            break
        candidates = sorted(
            pid for pid in unresolved if season in seasons_by_player.get(pid, set())
        )
        if not candidates:
            continue
        league = League(league_id=int(league_id), year=int(season), espn_s2=espn_s2, swid=swid)
        for i in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[i : i + BATCH_SIZE]
            result = league.player_info(playerId=batch)
            if result is None:
                players = []
            elif isinstance(result, list):
                players = result
            else:
                players = [result]
            for p in players:
                if p.playerId in unresolved:
                    rows[p.playerId] = {"player_id": p.playerId, "position": p.position}
                    unresolved.discard(p.playerId)
        print(f"  season {season}: {len(all_ids) - len(unresolved)}/{len(all_ids)} resolved so far")

    if unresolved:
        print(f"WARNING: {len(unresolved)} player ids never resolved: {sorted(unresolved)[:10]}...")

    pd.DataFrame(rows.values()).to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved {len(rows)} positions to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
