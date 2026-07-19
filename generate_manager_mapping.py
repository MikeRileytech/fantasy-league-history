"""
Build (or update) manager_mapping.csv from the imported season data.

The mapping file has one row per ESPN team per season. The "manager" column
starts out pre-filled with the owner name ESPN recorded, and YOU edit it to
the real-life manager's name wherever ESPN's record is wrong (for example,
when someone left the league and a new manager inherited their ESPN team).

Safe to re-run: if manager_mapping.csv already exists, any manager names you
typed in are kept. Only new team-seasons (e.g. after importing another year)
are added.

Run it with:
    python generate_manager_mapping.py
"""

from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
MAPPING_FILE = PROJECT_DIR / "manager_mapping.csv"


def load_all_team_seasons() -> pd.DataFrame:
    files = sorted(PROCESSED_DIR.glob("*_teams.csv"))
    if not files:
        raise SystemExit(
            "ERROR: no *_teams.csv files found in data/processed/.\n"
            "Run espn_history_importer.py for at least one season first."
        )
    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df = df[["season", "espn_team_id", "team_name", "owner_names", "owner_ids"]]
    return df.sort_values(["season", "espn_team_id"]).reset_index(drop=True)


def main():
    teams = load_all_team_seasons()

    # Start every row's manager as the ESPN owner name; you will correct
    # the rows where the real manager was someone else.
    teams["manager"] = teams["owner_names"]

    if MAPPING_FILE.exists():
        existing = pd.read_csv(MAPPING_FILE)
        # Keep the manager values you already entered for known team-seasons.
        merged = teams.merge(
            existing[["season", "espn_team_id", "manager"]],
            on=["season", "espn_team_id"],
            how="left",
            suffixes=("_default", ""),
        )
        merged["manager"] = merged["manager"].fillna(merged["manager_default"])
        teams = merged.drop(columns=["manager_default"])
        print(f"Updated existing {MAPPING_FILE.name} (your edits were kept).")
    else:
        print(f"Created new {MAPPING_FILE.name}.")

    teams.to_csv(MAPPING_FILE, index=False)

    seasons = teams["season"].nunique()
    print(f"{len(teams)} team-season rows across {seasons} seasons.")
    print(
        "\nNext step: open manager_mapping.csv in LibreOffice and fix the\n"
        "'manager' column wherever the real manager differs from ESPN's\n"
        "recorded owner. Use the same exact spelling for a manager across\n"
        "all their seasons so their history links up correctly."
    )


if __name__ == "__main__":
    main()
