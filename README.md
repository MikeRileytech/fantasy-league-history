# ESPN Fantasy Football History Importer

This is Stage 1 of a fantasy football league history project. It does **not**
build a dashboard yet — it just connects to your ESPN league, downloads one
historical season, and saves the data to files on your computer so we can
build a dashboard from it later.

This guide assumes you have never used Python, a terminal, or GitHub before.
Follow the steps in order.

---

## 1. Install Python

1. Go to https://www.python.org/downloads/ and download the latest Python 3
   installer for Windows.
2. Run the installer. **On the very first screen, check the box that says
   "Add python.exe to PATH"** before clicking Install. This step is easy to
   miss and if you skip it, none of the commands below will work.
3. When it finishes, open a terminal. In this project we use **PowerShell**
   (search "PowerShell" in the Windows Start menu).
4. Check Python installed correctly by typing:
   ```powershell
   python --version
   ```
   You should see something like `Python 3.12.x`. If you instead see an error
   or a Microsoft Store popup, Python isn't on your PATH yet — reinstall and
   make sure to check that box in step 2.

## 2. Open the project folder in your terminal

In PowerShell, navigate to this project folder (adjust the path if you moved
it):
```powershell
cd "C:\Claude\Projects\FantasyApp"
```
Every command in the rest of this guide assumes your terminal is sitting in
this folder.

## 3. Create and activate a virtual environment

A "virtual environment" is a private, isolated copy of Python just for this
project, so the packages we install don't interfere with anything else on
your computer. Create one once:
```powershell
python -m venv .venv
```
This creates a `.venv` folder inside the project. Every time you open a new
terminal to work on this project, activate it first:
```powershell
.venv\Scripts\Activate.ps1
```
You'll know it worked because your prompt line now starts with `(.venv)`.

> If PowerShell blocks the activation script with a message about "running
> scripts is disabled on this system," run this once, then try activating
> again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

## 4. Install the project's dependencies

With `.venv` activated, install everything this project needs:
```powershell
pip install -r requirements.txt
```
This reads `requirements.txt` and installs `espn_api` (talks to ESPN),
`python-dotenv` (loads your secret credentials), and `pandas` (writes clean
CSV files).

## 5. Set up your `.env` file (your private credentials)

Credentials should never be typed directly into code or committed to GitHub,
so this project keeps them in a separate file named `.env` that is listed in
`.gitignore` (meaning Git will always ignore it).

1. In the project folder, make a copy of `.env.example` and name the copy
   exactly `.env`. In PowerShell:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Open `.env` in any text editor (Notepad works fine).
3. Fill in `LEAGUE_ID`. You can find it in your league's URL on
   fantasy.espn.com, e.g.:
   ```
   https://fantasy.espn.com/football/league?leagueId=1234567
   ```
   means `LEAGUE_ID=1234567`.
4. **If your league is public**, leave `SWID` and `ESPN_S2` blank and skip to
   step 6.
5. **If your league is private**, you also need `SWID` and `ESPN_S2`, which
   are two values ESPN stores in your browser after you log in:
   - Log in to fantasy.espn.com in Chrome or Edge.
   - Press `F12` to open Developer Tools, then click the **Application** tab
     (Chrome) or **Application/Storage** tab (Edge).
   - In the left sidebar, expand **Cookies** and click
     `https://fantasy.espn.com`.
   - Find the row named `SWID` and copy its Value (it looks like
     `{ABC12345-...}`, curly braces included) into `.env`.
   - Find the row named `espn_s2` and copy its Value (a long string of
     letters/numbers) into `.env`.
   - These values expire periodically (typically once a year or when you log
     out). If the importer later says access was denied, come back and
     re-copy fresh values.

Your finished `.env` should look like:
```
LEAGUE_ID=1234567
SWID={ABC12345-1234-1234-1234-123456789ABC}
ESPN_S2=AEA1abcdEFGH...
```

## 6. Run the importer

With `.venv` still activated, run the script and tell it which season
(year) to retrieve:
```powershell
python espn_history_importer.py 2019
```
Replace `2019` with any season you actually want. Run it again with a
different year any time you want another season — nothing is deleted or
overwritten between seasons, since each season's files are named with the
year.

### What you'll see

- A short summary printed to the terminal: each team, its owner(s), record,
  points for/against, and standing.
- New files under `data/raw/` — the original JSON exactly as ESPN sent it,
  untouched, for that league and season.
- New files under `data/processed/` — clean, flat files ready for analysis:
  - `*_teams.csv` / `.json` — one row per team: ESPN team ID, team name,
    owner(s), wins/losses/ties, points for/against, regular-season standing,
    final standing.
  - `*_matchups.csv` / `.json` — one row per team per week: opponent, both
    scores, and the outcome (win/loss/tie).
  - `*_draft.csv` / `.json` — one row per draft pick: round, pick number,
    which team picked, and which player.

## Troubleshooting

The script tries to explain problems in plain language, but here's what each
one means:

- **"LEAGUE_ID is missing"** — you haven't created `.env` yet, or forgot to
  fill in `LEAGUE_ID`. Revisit step 5.
- **"ESPN denied access to this league"** — your league is private and
  `SWID`/`ESPN_S2` are missing, wrong, or expired. Revisit step 5.5 and
  re-copy fresh values.
- **"ESPN could not find league ... for the ... season"** — either
  `LEAGUE_ID` is wrong, or that league didn't exist / you weren't in it that
  year. Double check the league ID and the season number.
- **"Could not reach ESPN's servers"** — a network problem; check your
  internet connection and try again.
- **"ESPN's response ... was missing expected field"** — very old seasons
  are sometimes stored by ESPN in a format the underlying `espn_api` library
  doesn't understand. There's no fix on our end for this; try a more recent
  season.

## Important note for later: teams vs. managers

ESPN's "team" records are tied to a team slot in the league, not to a person.
Over the years, people leave a league and a new manager can take over their
existing ESPN team, and ESPN's history keeps crediting all of that team's
seasons to one team ID — real ownership changes are not reflected. This
importer only pulls ESPN's own team-centric data as-is (including the owner
ID/name ESPN reports for that season). Do **not** assume `espn_team_id` is a
consistent proxy for "manager" across seasons. A later stage of this project
will add a manual mapping file that assigns each ESPN team, for each season
or date range, to the correct real-life manager — you'll build that once
you've imported the seasons you care about.

## Running the dashboard

Once you've imported your seasons and filled in `manager_mapping.csv`, start
the dashboard with:
```powershell
streamlit run app.py
```
**Breakdown:**
- **`streamlit`** — the dashboard program (installed by requirements.txt)
- **`run`** — command: run an app
- **`app.py`** — the dashboard script to run

Your browser opens automatically at http://localhost:8501. The dashboard has
four tabs:
- **All-Time Standings** — career records per real manager (championships,
  win %, points), using your manager mapping
- **Season Browser** — final standings for any single season
- **Head-to-Head** — every manager's all-time record vs. every other manager
- **Draft History** — all draft picks, filterable by season, searchable by
  player or manager

To stop the dashboard, go back to PowerShell and press `Ctrl+C`.

### Setting up "Ask the League" (optional, costs a little money)

The fifth tab lets you ask questions in plain English ("what year did the
ties happen?"). It uses Anthropic's Claude API, which is pay-per-use — a
question costs a few cents at most, and a whole season of league usage is
typically a few dollars. To enable it:

1. Go to https://console.anthropic.com and create an account.
2. Add a small amount of credit (e.g. $5) under **Billing**.
3. Under **API Keys**, click **Create Key**, and copy the key (it starts
   with `sk-ant-`). It is only shown once.
4. Open your `.env` file and paste it in:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
5. Restart the dashboard (`Ctrl+C`, then `streamlit run app.py` again).

The key is a secret, just like your ESPN credentials — it lives only in
`.env`, which Git never commits. If the tab shows an authentication error,
re-copy the key and restart.

## Project files

```
espn_history_importer.py   the importer script you run
requirements.txt           Python packages this project needs
.env.example                template for your local .env (safe to commit)
.env                        your real credentials (never committed; see .gitignore)
data/raw/                   untouched JSON exactly as ESPN returned it
data/processed/             clean CSV/JSON files, one set per league/season
```
