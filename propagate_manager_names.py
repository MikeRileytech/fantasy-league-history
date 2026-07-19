"""
Copy your manager-name edits to all matching rows in manager_mapping.csv.

How it works:
  - A row counts as "edited" if its manager value differs from its
    owner_names value (meaning you typed a real name there).
  - For each edited row, we learn "ESPN username X = real name Y".
  - Every UNedited row with the same ESPN username gets filled in with
    that real name.
  - Rows you already edited are never changed, so it is safe to re-run.

Run it with:
    python propagate_manager_names.py
"""

from pathlib import Path

import pandas as pd

MAPPING_FILE = Path(__file__).resolve().parent / "manager_mapping.csv"


def main():
    df = pd.read_csv(MAPPING_FILE)

    edited = df[
        df["manager"].notna()
        & df["owner_names"].notna()
        & (df["manager"] != df["owner_names"])
    ]

    # Learn username -> real name from the rows you edited.
    username_to_manager = {}
    conflicts = []
    for _, row in edited.iterrows():
        username = row["owner_names"]
        name = row["manager"]
        if username in username_to_manager and username_to_manager[username] != name:
            conflicts.append(
                f"  '{username}' is mapped to both "
                f"'{username_to_manager[username]}' and '{name}'"
            )
        username_to_manager[username] = name

    if conflicts:
        print("WARNING: the same ESPN username has different manager names in")
        print("different rows. Fix these in manager_mapping.csv, save, and re-run:")
        print("\n".join(conflicts))
        print("Nothing was changed.")
        return

    if not username_to_manager:
        print("No edited rows found - fill in at least one manager name first.")
        return

    # Fill unedited rows whose username we now know.
    untouched = df["manager"].isna() | (df["manager"] == df["owner_names"])
    fillable = untouched & df["owner_names"].isin(username_to_manager)
    df.loc[fillable, "manager"] = df.loc[fillable, "owner_names"].map(
        username_to_manager
    )

    df.to_csv(MAPPING_FILE, index=False)

    print(f"Learned {len(username_to_manager)} username -> name mappings:")
    for username, name in sorted(username_to_manager.items()):
        print(f"  {username} -> {name}")
    print(f"\nFilled in {int(fillable.sum())} rows.")

    remaining = df[df["manager"].isna() | (df["manager"] == df["owner_names"])]
    if len(remaining):
        print(f"\n{len(remaining)} rows still need your attention")
        print("(usernames you have not named yet, or blank owners):")
        print(
            remaining[["season", "espn_team_id", "team_name", "owner_names"]]
            .to_string(index=False)
        )
    else:
        print("\nAll rows are filled in!")


if __name__ == "__main__":
    main()
