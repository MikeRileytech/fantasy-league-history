"""
Refresh the in-progress season's imported data and push the update.

Meant to run on a recurring schedule (see README.md for how the schedule is
set up). Does nothing until the season's week 2 is in the books - a
manager's record is too noisy to bother publishing after just one week, and
this also protects future seasons from getting imported mid-week-1 if the
schedule is simply left running year-round.

Run it with:
    python update_current_season.py
"""

import subprocess
import sys
from pathlib import Path

import league_data
import live_data

PROJECT_DIR = Path(__file__).resolve().parent


def run(cmd: list) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=PROJECT_DIR)


def main():
    season = league_data.season_in_progress()
    if season is None:
        print("No season is currently in progress - nothing to update.")
        return

    league_id, espn_s2, swid = live_data.espn_credentials()
    if league_id is None:
        sys.exit("ERROR: LEAGUE_ID is not set in .env.")

    league = live_data.fetch_live_league(league_id, season, espn_s2, swid)
    if league.current_week < 3:
        print(
            f"{season} season is only in week {league.current_week} - "
            "waiting until week 2 is complete before importing."
        )
        return

    run([sys.executable, "espn_history_importer.py", str(season)])
    run([sys.executable, "generate_manager_mapping.py"])
    run([sys.executable, "propagate_manager_names.py"])

    status = subprocess.run(
        ["git", "status", "--porcelain", "data/processed", "manager_mapping.csv"],
        cwd=PROJECT_DIR, capture_output=True, text=True, check=True,
    )
    if not status.stdout.strip():
        print("No changes to commit - data was already up to date.")
        return

    run(["git", "add", "data/processed", "manager_mapping.csv"])
    run([
        "git", "commit", "-m",
        f"Update {season} season data through week {league.current_week - 1}",
    ])
    run(["git", "push"])
    print("Pushed - Streamlit Community Cloud will redeploy with the update.")


if __name__ == "__main__":
    main()
