"""
The Schedule Matrix tab: what every team's record would be had it played
another team's schedule. Each week the team keeps its own score
and plays whoever the other team played that week, so a row of the matrix
is one team's scores run against each schedule in the league.

The week the other team played this one, the swap would have the team
playing itself, so it plays the other team instead - the game that really
happened. A game that really happened keeps its real result. Any other
pairing goes to the higher score, and equal scores tie: the league breaks
no ties (ESPN's matchupTieRule is NONE).

Plain data in, HTML out, like trade_grid.py, so it can be tested. app.py
draws it for the latest season, from the saved regular-season games.
"""

import math
from collections import Counter
from html import escape


def swap_records(games) -> dict:
    """(team, schedule) -> (wins, losses, ties): the record team would have
    had against schedule's opponents, both ESPN team ids. (team, team) is
    its real record.

    games: one season's regular-season games, one row per team per week, as
    league_data.load_matchups() gives them - espn_team_id, week,
    opponent_espn_team_id, team_score and outcome (W, L or T). A week either
    team has no game in (a bye, or not saved yet) is left out of the pair.
    """
    score, opponent, outcome = {}, {}, {}
    for game in games.itertuples(index=False):
        key = (int(game.espn_team_id), int(game.week))
        score[key] = round(float(game.team_score), 2)
        opponent[key] = int(game.opponent_espn_team_id)
        outcome[key] = game.outcome
    teams = sorted({team for team, _ in score})
    weeks = sorted({week for _, week in score})
    records = {}
    for team in teams:
        for schedule in teams:
            tally = Counter()
            for week in weeks:
                if (team, week) not in score or (schedule, week) not in opponent:
                    continue
                rival = opponent[(schedule, week)]
                if rival == team:
                    rival = schedule
                if rival == opponent[(team, week)]:
                    tally[outcome[(team, week)]] += 1
                elif (rival, week) in score:
                    mine, theirs = score[(team, week)], score[(rival, week)]
                    tally["W" if mine > theirs else "L" if mine < theirs else "T"] += 1
            records[(team, schedule)] = (tally["W"], tally["L"], tally["T"])
    return records


def record_text(record) -> str:
    """'5-2', or '3-3-1' with ties."""
    wins, losses, ties = record
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def win_count(record) -> float:
    """Wins, a tie counting as half."""
    return record[0] + record[2] / 2


def step(delta: float) -> int:
    """The color step for a record that is delta wins better than the real
    one (negative: worse): 1 up to a win, 2 up to two, 3 past that."""
    size = min(3, math.ceil(abs(delta)))
    return size if delta > 0 else -size


def short_names(managers: dict) -> dict:
    """team id -> the shortest name that tells the season's managers apart:
    'Kyle', or 'Mike R.' when two share a first name, or the whole name."""
    def first(name):
        return name.split()[0] if name.split() else name

    def initial(name):
        parts = name.split()
        return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else name

    firsts = Counter(first(name) for name in managers.values())
    initials = Counter(initial(name) for name in managers.values())
    return {team: first(name) if firsts[first(name)] == 1
            else initial(name) if initials[initial(name)] == 1 else name
            for team, name in managers.items()}


# The fills (.ss-f1-3, .ss-m1-3) say how a schedule changes a team's record,
# against the panel (#222834, the Trade Tool's): green for more wins, red for
# fewer, a step per win up to 3. Each arm steps up in lightness from the
# panel by about the same amounts, and every step keeps white text readable.
# The greens lean blue (emerald) and sit a little lighter than the reds, so
# red-green color blind viewers can still tell the two apart. The same record
# is left unfilled, so it reads as nothing - a gray tile didn't, under
# red-green color blindness.
MATRIX_CSS = """
<style>
/* Its own dark colors, like the Trade Tool's grid, whatever Streamlit's
   theme. The panel hugs the matrix, and scrolls sideways on a screen too
   narrow for it, with the names pinned. */
.ss-panel { width: fit-content; max-width: 100%; box-sizing: border-box; overflow-x: auto;
  padding: 10px 12px 12px; border-radius: 12px; background: #222834; color: #fff; }
.ss-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px;
  margin: 0 0 10px; font-size: 0.72rem; color: #aab3c2; }
/* A key wraps as a whole, so its words stay beside its colors. */
.ss-key { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.ss-legend .ss-c { display: inline-flex; min-width: 24px; height: 20px; padding: 0 5px;
  font-size: 0.66rem; }
.ss { border-collapse: separate; border-spacing: 0; font-variant-numeric: tabular-nums; }
.ss th, .ss td { padding: 2px; text-align: center; white-space: nowrap; }
.ss thead th { vertical-align: bottom; padding-bottom: 6px; font-size: 0.72rem;
  font-weight: 600; color: #aab3c2; }
.ss th:first-child { position: sticky; left: 0; z-index: 1; background: #222834;
  text-align: left; padding-right: 10px; }
.ss tbody th { font-size: 0.8rem; font-weight: 600; color: #fff; }
.ss-corner span { display: block; font-size: 0.62rem; font-weight: 500; color: #7d8696; }
.ss-corner span:first-child { text-align: right; }
.ss-short { display: none; }
.ss-c { display: flex; align-items: center; justify-content: center; box-sizing: border-box;
  min-width: 52px; height: 32px; padding: 0 6px; border-radius: 5px; font-size: 0.82rem;
  font-weight: 700; color: #fff; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.10); }
.ss-f1 { background: #892c2a; } .ss-f2 { background: #b13f3c; } .ss-f3 { background: #e34948; }
.ss-m1 { background: #057050; } .ss-m2 { background: #068f67; } .ss-m3 { background: #15ac7d; }
.ss-f1, .ss-f2, .ss-f3, .ss-m1, .ss-m2, .ss-m3 { box-shadow: none; }
.ss-real { box-shadow: inset 0 0 0 2px rgba(255,255,255,0.85); }
/* Pointing at a record - tapping one, on a phone - lights up its team and
   its schedule. */
.ss td { outline: none; }
.ss td:hover .ss-c, .ss td:focus .ss-c { outline: 2px solid #7fd3c4; outline-offset: -2px; }
.ss tbody tr:hover th, .ss tbody tr:focus-within th { color: #7fd3c4; }
/* Narrower than the matrix (phones, tablets, small windows - Streamlit
   leaves it 793px from about 953px wide): it fits the width instead, the
   schedules' names stand on end and the teams' are shortened. */
@media (max-width: 959px) {
  .ss-panel { width: auto; }
  .ss { width: 100%; table-layout: fixed; }
  .ss th:first-child { width: 72px; overflow: hidden; text-overflow: ellipsis; }
  .ss thead th:not(:first-child) span { display: inline-block; writing-mode: vertical-rl;
    transform: rotate(180deg); }
  .ss-full { display: none; }
  .ss-short { display: inline; }
  .ss-c { min-width: 0; padding: 0; }
  /* Longer records ("10-3", ties' "3-3-1") in smaller type, to fit. */
  .ss-c.ss-long { font-size: 0.76rem; }
  .ss-c.ss-longer { font-size: min(0.76rem, 1.7vw); letter-spacing: -0.02em; }
}
/* A phone: smaller still. */
@media (max-width: 640px) {
  .ss-panel { padding: 8px 4px; }
  .ss-legend { gap: 5px 10px; padding: 0 4px; font-size: 0.66rem; }
  .ss-legend .ss-c { min-width: 20px; height: 18px; padding: 0 4px; font-size: 0.6rem; }
  .ss th, .ss td { padding: 1px; }
  .ss th:first-child { width: 46px; padding-right: 3px; }
  .ss thead th { font-size: 0.62rem; }
  .ss-corner span { font-size: 0.5rem; }
  .ss tbody th { font-size: 0.66rem; }
  .ss-c { height: 26px; border-radius: 4px; font-size: min(0.72rem, 2.6vw); }
  .ss-real { box-shadow: inset 0 0 0 1.5px rgba(255,255,255,0.85); }
  .ss-c.ss-long { font-size: min(0.68rem, 2.4vw); }
  .ss-c.ss-longer { font-size: min(0.62rem, 2.15vw); }
}
</style>
"""


def _legend() -> str:
    fewer = "".join(f'<b class="ss-c ss-f{n}">{n}{"+" if n == 3 else ""}</b>' for n in (3, 2, 1))
    more = "".join(f'<b class="ss-c ss-m{n}">{n}{"+" if n == 3 else ""}</b>' for n in (1, 2, 3))
    return (
        '<div class="ss-legend"><span>Wins vs. the real record:</span>'
        f'<span class="ss-key">fewer {fewer}<b class="ss-c">=</b>{more} more</span>'
        '<span class="ss-key"><b class="ss-c ss-real">W-L</b> real record</span></div>'
    )


def _column_css(count: int) -> str:
    """Each record lights up its schedule's name too: one rule per column,
    since CSS can't match a cell to its column's header otherwise."""
    rules = [f".ss:has(td.ss-k{i}:hover) th.ss-k{i}, .ss:has(td.ss-k{i}:focus) th.ss-k{i} "
             "{ color: #7fd3c4; }" for i in range(count)]
    return "<style>" + "\n".join(rules) + "</style>"


def matrix_html(records: dict, managers: dict) -> str:
    """The matrix as one HTML block, styles included: a row per team and a
    column per schedule, both in managers' order (team id -> manager, best
    record first). Each cell is the row's record with the column's schedule,
    filled by how many more (green) or fewer (red) wins it has than the real
    record, which runs down the diagonal, outlined."""
    teams = [team for team in managers if (team, team) in records]
    if not teams:
        return ""
    short = short_names({team: managers[team] for team in teams})

    head = ['<th class="ss-corner"><span>schedule →</span><span>team ↓</span></th>']
    for i, team in enumerate(teams):
        head.append(f'<th class="ss-k{i}" title="{escape(managers[team])}\'s schedule">'
                    f"<span>{escape(short[team])}</span></th>")

    body = []
    for team in teams:
        name = managers[team]
        real = records[(team, team)]
        cells = [f'<th title="{escape(name)}"><span class="ss-full">{escape(name)}</span>'
                 f'<span class="ss-short">{escape(short[team])}</span></th>']
        for i, schedule in enumerate(teams):
            record = records.get((team, schedule), (0, 0, 0))
            delta = win_count(record) - win_count(real)
            css = ["ss-c"]
            if schedule == team:
                css.append("ss-real")
                title = f"{name}'s real record: {record_text(real)}"
            else:
                level = step(delta)
                if level:
                    css.append(f"ss-{'m' if level > 0 else 'f'}{abs(level)}")
                change = ("the same" if not delta else
                          f"{'+' if delta > 0 else '−'}{abs(delta):g} win{'' if abs(delta) == 1 else 's'}")
                title = (f"{name} with {managers[schedule]}'s schedule: {record_text(record)}"
                         f" · real record {record_text(real)}, {change}")
            text = record_text(record)
            if len(text) > 3:
                css.append("ss-long" if len(text) == 4 else "ss-longer")
            cells.append(f'<td class="ss-k{i}" tabindex="-1"><div class="{" ".join(css)}" '
                         f'title="{escape(title)}">{text}</div></td>')
        body.append("<tr>" + "".join(cells) + "</tr>")

    return (
        MATRIX_CSS + _column_css(len(teams)) + '<div class="ss-panel">' + _legend()
        + '<table class="ss"><thead><tr>' + "".join(head) + "</tr></thead><tbody>"
        + "".join(body) + "</tbody></table></div>"
    )
