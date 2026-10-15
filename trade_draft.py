"""
The Trade Tool's drafted trades: pick players from your roster and another
team's, see both rosters as they'd stand if the trade went through, and
slide out every player's rest-of-season NFL schedule with the bye weeks
marked. Nothing is sent to ESPN - the app only reads from it.

Plain data in, HTML out, like trade_grid.py, so it can be tested. app.py
draws it: the rosters with trade_grid.grid_html, the schedule in a drawer
(a Streamlit container keyed "ros_drawer", which DRAWER_CSS pins to the
right edge of the window and slides in).
"""

from collections import Counter
from html import escape

from trade_grid import POSITIONS, short_name

# Lineup slots that start no one, and the flex ones whose names aren't a
# list of positions ("RB/WR/TE" is; "D/ST" is a position, not a flex).
BENCH_SLOTS = {"BE", "IR"}
SLOT_POSITIONS = {"OP": {"QB", "RB", "WR", "TE"}}
SLOT_LABELS = {"RB/WR/TE": "FLEX", "OP": "SUPERFLEX"}


def apply_trade(rosters, me, partner, send, get) -> list[dict]:
    """The league's rosters with the trade made: the players in send (ids)
    go from me to partner, the ones in get come from partner to me. Moved
    players are marked moved=True and land on the bench (or stay on IR), as
    on ESPN. The rows are copies; rosters is left alone."""
    send, get = set(send), set(get)
    traded = []
    for player in rosters:
        team = int(player["espn_team_id"])
        if (team == me and player["player_id"] in send) or (
                team == partner and player["player_id"] in get):
            player = {**player, "espn_team_id": partner if team == me else me,
                      "moved": True, "slot": "IR" if player.get("slot") == "IR" else "BE"}
        traded.append(player)
    return traded


def team_players(rosters, team_id) -> list[dict]:
    """team_id's players, in the grid's order: by position, best first."""
    order = {position: i for i, position in enumerate(POSITIONS)}
    players = [p for p in rosters if int(p["espn_team_id"]) == team_id]
    return sorted(players, key=lambda p: (order.get(p.get("position"), len(order)),
                                          -(p.get("total_points") or 0.0)))


def depth_change(before, after, team_id) -> str:
    """'RB 4 → 5 · WR 6 → 5' - the positions whose head count the trade
    changes for team_id, in the grid's order."""
    old = Counter(p.get("position") for p in before if int(p["espn_team_id"]) == team_id)
    new = Counter(p.get("position") for p in after if int(p["espn_team_id"]) == team_id)
    changed = [p for p in POSITIONS if old[p] != new[p]]
    changed += sorted(p for p in set(old) | set(new) if p not in POSITIONS and old[p] != new[p])
    return " · ".join(f"{p} {old[p]} → {new[p]}" for p in changed)


def game(player, week, schedules) -> str | None:
    """The player's NFL game in `week` - 'KC' at home, '@KC' away - or 'BYE'.
    None when ESPN has no schedule for his team (a free agent, or no data)."""
    games = schedules.get(player.get("nfl_team"))
    if not games:
        return None
    return games.get(week, "BYE")


def _slot_positions(slot) -> set:
    if slot in SLOT_POSITIONS:
        return SLOT_POSITIONS[slot]
    if slot in POSITIONS or "/" not in slot:
        return {slot}
    return set(slot.split("/"))


def unfilled_slots(players, week, slots, schedules) -> list[str]:
    """The starting spots `players` couldn't fill in `week` because of
    byes - ['QB'], ['RB', 'FLEX']... - each named once. Players on IR don't
    count, nor do ones with no NFL game. slots is the league's lineup,
    {"QB": 1, "RB": 2, "RB/WR/TE": 2, "BE": 5, ...}."""
    free = Counter(p.get("position") for p in players
                   if p.get("slot") != "IR" and game(p, week, schedules) not in (None, "BYE"))
    starters = [slot for slot, count in slots.items() if slot not in BENCH_SLOTS and count]
    short = []
    # One-position slots first, then the flex ones, narrowest first, each
    # flex taking from whichever eligible position has the most to spare.
    for slot in sorted(starters, key=lambda s: len(_slot_positions(s))):
        for _ in range(slots[slot]):
            spare = max(_slot_positions(slot), key=lambda position: free[position])
            if free[spare] > 0:
                free[spare] -= 1
            elif SLOT_LABELS.get(slot, slot) not in short:
                short.append(SLOT_LABELS.get(slot, slot))
    return short


DRAWER_CSS = """
<style>
/* The Streamlit container keyed "ros_drawer", pinned below the top bar on
   the right and slid in from off-screen. Its own dark colors, like the
   roster grid, whatever Streamlit's theme. */
.stApp div.st-key-ros_drawer { position: fixed; top: 3.75rem; right: 0; bottom: 0;
  width: min(800px, 100vw); z-index: 1000; box-sizing: border-box;
  padding: 12px 16px 16px; gap: 8px; background: #1b2029; color: #fff;
  border-left: 1px solid #333b4a; box-shadow: -14px 0 36px rgba(0,0,0,0.45);
  overflow-y: auto; animation: ros-slide 0.32s cubic-bezier(.2,.8,.2,1); }
@keyframes ros-slide { from { transform: translateX(100%); } to { transform: none; } }
@media (prefers-reduced-motion: reduce) { .stApp div.st-key-ros_drawer { animation: none; } }
.st-key-ros_drawer button { background: #2b3342; color: #fff; border-color: #3f4859; }
.st-key-ros_drawer button:hover { border-color: #7fd3c4; color: #7fd3c4; }
.ros-title { font-size: 1.15rem; font-weight: 700; color: #fff; }
.ros-legend { font-size: 0.74rem; color: #aab3c2; line-height: 1.6; }
.ros-legend b { display: inline-block; padding: 0 5px; border-radius: 3px;
  font-size: 0.66rem; line-height: 1.5; }
/* The table scrolls inside itself, so the week headers and player names
   stay pinned while it does. */
.ros-scroll { overflow: auto; max-height: calc(100dvh - 11.5rem); border-radius: 10px;
  background: #222834; }
.ros-t { border-collapse: separate; border-spacing: 0; font-size: 0.72rem; color: #fff; }
.ros-t th, .ros-t td { padding: 0; text-align: center; white-space: nowrap; }
.ros-t thead th { position: sticky; z-index: 2; background: #222834; }
.ros-t thead tr:first-child th { top: 0; height: 20px; font-size: 0.62rem;
  font-weight: 600; color: #aab3c2; text-transform: uppercase; letter-spacing: .04em; }
.ros-t thead tr:nth-child(2) th { top: 20px; padding: 2px 0 6px; font-weight: 700; }
.ros-t thead th.ros-po { color: #e9c46a; }
.ros-t .ros-wk { width: 48px; min-width: 48px; }
.ros-t .ros-wk small { display: block; font-size: 0.56rem; font-weight: 500; color: #7fd3c4; }
.ros-t thead .ros-po.ros-wk { background: #2c2a3a; }
.ros-t th:first-child, .ros-t td:first-child { position: sticky; left: 0; z-index: 1;
  background: #222834; text-align: left; }
.ros-t thead th:first-child { z-index: 3; }
.ros-t td { padding: 2px; }
.ros-g { height: 30px; border-radius: 5px; display: flex; align-items: center;
  justify-content: center; background: #2c3342; }
.ros-po > .ros-g { background: #2f2c40; }
.ros-g.ros-bye { background: #f2b33d; color: #261900; font-weight: 800;
  letter-spacing: .03em; box-shadow: 0 0 0 1px #ffd27a; }
.ros-g.ros-none { background: transparent; color: #6d7586; }
.ros-p { width: 150px; min-width: 150px; max-width: 150px; height: 30px; box-sizing: border-box;
  border-left: 4px solid #4b5263; border-radius: 5px; background: #2c3342; padding: 2px 6px;
  display: flex; flex-direction: column; justify-content: center; position: relative;
  line-height: 1.2; }
.ros-p .ros-n { font-weight: 700; font-size: 0.74rem; overflow: hidden; text-overflow: ellipsis; }
.ros-p.ros-new .ros-n { padding-right: 30px; }
.ros-p .ros-s { font-size: 0.6rem; color: #aab3c2; }
.ros-p.ros-QB { border-left-color: #c9405a; } .ros-p.ros-RB { border-left-color: #0f8f7c; }
.ros-p.ros-WR { border-left-color: #2f72c0; } .ros-p.ros-TE { border-left-color: #c87420; }
.ros-p.ros-K { border-left-color: #8257bd; } .ros-p.ros-DST { border-left-color: #5f6472; }
.ros-p.ros-new { box-shadow: inset 0 0 0 2px #6fdc9a; }
.ros-p .ros-tag { position: absolute; top: 3px; right: 4px; font-size: 0.54rem; font-weight: 800;
  border-radius: 3px; padding: 0 3px; background: #6fdc9a; color: #0b2a17; }
.ros-out .ros-n, .ros-out .ros-s { opacity: 0.55; }
.ros-team td { padding: 12px 6px 4px; font-weight: 700; font-size: 0.82rem; text-align: left; }
.ros-team td span { font-weight: 400; color: #aab3c2; font-size: 0.7rem; }
.ros-foot .ros-g { height: 34px; flex-direction: column; background: transparent;
  color: #aab3c2; border: 1px dashed #3f4859; box-sizing: border-box; line-height: 1.15; }
.ros-foot .ros-g.ros-label { align-items: flex-start; padding-left: 8px; border: 0;
  font-weight: 600; }
.ros-foot .ros-g.ros-heavy { color: #f2b33d; border-color: #f2b33d; font-weight: 700; }
.ros-foot .ros-g.ros-short { background: #a8323e; color: #fff; border: 0; font-weight: 700; }
.ros-foot small { font-size: 0.54rem; font-weight: 600; }
.legend-bye { background: #f2b33d; color: #261900; }
.legend-new { background: #6fdc9a; color: #0b2a17; }
.legend-heavy { color: #f2b33d; border: 1px dashed #f2b33d; }
.legend-short { background: #a8323e; color: #fff; }
@media (max-width: 640px) {
  .ros-p { width: 112px; min-width: 112px; max-width: 112px; }
  .ros-t .ros-wk { width: 44px; min-width: 44px; }
}
</style>
"""

# Out for the long haul: dimmed in the schedule (a week-to-week OUT isn't).
STATUS_OUT = {"INJURY_RESERVE", "IR"}


def _player_row(player, weeks, reg_season_weeks, schedules) -> str:
    position = player.get("position") or ""
    css = {"D/ST": "DST"}.get(position, position if position in POSITIONS else "OTHER")
    nfl = (player.get("nfl_team") or "").upper()
    new = " ros-new" if player.get("moved") else ""
    out = " ros-out" if (player.get("slot") == "IR"
                         or (player.get("status") or "") in STATUS_OUT) else ""
    tag = '<b class="ros-tag">NEW</b>' if player.get("moved") else ""
    name = (f'<td><div class="ros-p ros-{css}{new}{out}" title="{escape(player.get("player_name") or "")}">'
            f'{tag}<span class="ros-n">{escape(short_name(player.get("player_name"), position))}</span>'
            f'<span class="ros-s">{escape(" · ".join(filter(None, [position, nfl])))}</span></div></td>')
    cells = []
    for week in weeks:
        po = ' class="ros-po"' if week > reg_season_weeks else ""
        opponent = game(player, week, schedules)
        if opponent is None:
            cell = '<div class="ros-g ros-none" title="No NFL schedule">–</div>'
        elif opponent == "BYE":
            cell = f'<div class="ros-g ros-bye" title="Week {week}: bye">BYE</div>'
        else:
            where = f"at {opponent[1:]}" if opponent.startswith("@") else f"vs {opponent}"
            cell = f'<div class="ros-g" title="Week {week}: {escape(where)}">{escape(opponent)}</div>'
        cells.append(f"<td{po}>{cell}</td>")
    return "<tr>" + name + "".join(cells) + "</tr>"


def _bye_row(players, weeks, reg_season_weeks, slots, schedules) -> str:
    """Each week's count of players on bye (not counting IR), amber at two
    or more, red when the roster can't fill a starting spot that week."""
    cells = ['<td><div class="ros-g ros-label">On bye</div></td>']
    for week in weeks:
        po = ' class="ros-po"' if week > reg_season_weeks else ""
        away = [p for p in players
                if p.get("slot") != "IR" and game(p, week, schedules) == "BYE"]
        short = unfilled_slots(players, week, slots, schedules) if slots else []
        names = ", ".join(short_name(p.get("player_name"), p.get("position")) for p in away)
        title = f"Week {week}: " + (f"{len(away)} on bye ({names})" if away else "no one on bye")
        if short:
            title += f" - not enough left to start at {', '.join(short)}"
            cell = (f'<div class="ros-g ros-short" title="{escape(title)}">{len(away)}'
                    f'<small>no {escape("/".join(short))}</small></div>')
        else:
            heavy = " ros-heavy" if len(away) >= 2 else ""
            cell = f'<div class="ros-g{heavy}" title="{escape(title)}">{len(away) or "–"}</div>'
        cells.append(f"<td{po}>{cell}</td>")
    return '<tr class="ros-foot">' + "".join(cells) + "</tr>"


def schedule_html(teams, weeks, reg_season_weeks, schedules, slots=None) -> str:
    """Every player's NFL game, week by week, one block of rows per team.

    teams: [(heading, sub, players)] - players in display order (see
        team_players), each a roster row (player_name, position, nfl_team,
        slot, status, moved)
    weeks: the weeks to show, e.g. range(current_week, final_week + 1)
    reg_season_weeks: the last regular-season week; later ones are playoffs
    schedules: live_data._pro_schedules - NFL team -> {week: opponent}
    slots: the league's lineup slots, to flag weeks the byes leave a
        starting spot empty
    """
    weeks = list(weeks)
    if not weeks:
        return DRAWER_CSS + '<div class="ros-legend">The fantasy season is over.</div>'
    regular = [w for w in weeks if w <= reg_season_weeks]
    playoffs = [w for w in weeks if w > reg_season_weeks]
    phases = ["<th></th>"]
    if regular:
        phases.append(f'<th colspan="{len(regular)}">Regular season</th>')
    if playoffs:
        phases.append(f'<th colspan="{len(playoffs)}" class="ros-po">🏆 Playoffs</th>')
    week_heads = ['<th style="text-align:left;padding-left:8px">Player</th>']
    for i, week in enumerate(weeks):
        po = " ros-po" if week > reg_season_weeks else ""
        now = "<small>this week</small>" if i == 0 else ""
        week_heads.append(f'<th class="ros-wk{po}">Wk {week}{now}</th>')

    span = len(weeks) + 1
    body = []
    for heading, sub, players in teams:
        body.append(f'<tr class="ros-team"><td colspan="{span}">{escape(heading)} '
                    f'<span>{escape(sub)}</span></td></tr>')
        body.extend(_player_row(p, weeks, reg_season_weeks, schedules) for p in players)
        body.append(_bye_row(players, weeks, reg_season_weeks, slots or {}, schedules))

    legend = (
        '<div class="ros-legend"><b class="legend-bye">BYE</b> no NFL game that week · '
        '<b>@KC</b> on the road, <b>KC</b> at home · '
        '<b class="legend-new">NEW</b> comes over in the trade · bottom row, players on bye: '
        '<b class="legend-heavy">2+</b> stacked byes, '
        '<b class="legend-short">no QB</b> not enough left to fill your starting lineup</div>'
    )
    return (
        DRAWER_CSS + legend + '<div class="ros-scroll"><table class="ros-t"><thead>'
        + "<tr>" + "".join(phases) + "</tr><tr>" + "".join(week_heads) + "</tr></thead><tbody>"
        + "".join(body) + "</tbody></table></div>"
    )
