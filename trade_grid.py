"""
The Trade Tool's roster grid: every team's roster side by side, the way
Sleeper's trade screen lays them out, for scanning the league for teams
whose needs your roster could fill. The same tool as the Yahoo league's
site (fantasy-league-history-yahoo), fed by ESPN's rosters.

Each team's column runs QB, RB, WR, TE, K, D/ST with no gaps between
positions, best first within each by season points. The tiles' colors and
lines say the position, so the columns don't need to line up by position.

On a computer the whole league fits on one screen: the columns share the
width, the rows share the window's height, and each tile is two lines.
On a phone app.py passes just two columns - yours and the team you are
comparing with - and asks for the fit layout, which splits the screen's
width between them instead of scrolling sideways.

Plain data in, HTML out - no Streamlit or ESPN calls - so it can be
tested. app.py fetches the rosters (live_data.power_ranking_bundle) and
draws the result.
"""

from html import escape

POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]

GRID_CSS = """
<style>
.tt-scroll { overflow: auto; max-height: 78vh; border-radius: 12px;
  background: #222834; padding: 0 0 8px; }
/* No border-spacing: padding makes the gaps, so a pinned cell's background
   covers them and nothing shows through as the grid scrolls under it. */
.tt { border-collapse: separate; border-spacing: 0; color: #fff;
  font-family: inherit; margin: 0 auto; }
.tt th, .tt td { padding: 3px; vertical-align: top; }
.tt thead th { position: sticky; top: 0; z-index: 2; background: #222834;
  padding: 10px 0 6px; font-weight: 600; }
.tt th:first-child, .tt td:first-child { position: sticky; left: 0; z-index: 1;
  background: #222834; }
.tt thead th:first-child { z-index: 3; }
.tt-team { width: 124px; text-align: center; line-height: 1.2; }
.tt-team img { width: 40px; height: 40px; border-radius: 50%; object-fit: cover;
  display: block; margin: 0 auto 4px; background: #3a4252; }
.tt-team .tt-mgr { font-size: 0.85rem; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.tt-team .tt-sub { font-size: 0.68rem; font-weight: 400; color: #aab3c2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tt-team.tt-me .tt-mgr::after { content: " (you)"; color: #7fd3c4; font-weight: 400; }
.tt-tile { width: 124px; height: 60px; box-sizing: border-box; border-radius: 6px;
  padding: 5px 7px; position: relative; overflow: hidden; }
.tt-top { font-size: 0.62rem; font-weight: 600; opacity: 0.92; white-space: nowrap; }
.tt-name { font-size: 0.8rem; font-weight: 700; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; margin-top: 1px; }
.tt-pts { font-size: 0.64rem; opacity: 0.9; white-space: nowrap; }
.tt-st { position: absolute; top: 4px; right: 5px; font-size: 0.6rem; font-weight: 800;
  background: rgba(0,0,0,0.35); border-radius: 3px; padding: 0 3px; }
.tt-out { opacity: 0.55; }
.tt-me .tt-tile { box-shadow: inset 0 0 0 2px rgba(255,255,255,0.55); }
/* A drafted trade's view: the players who change hands. */
.tt .tt-tile.tt-new { box-shadow: inset 0 0 0 2px #6fdc9a; }
.tt-new::after { content: "NEW"; position: absolute; bottom: 4px; right: 5px;
  font-size: 0.54rem; font-weight: 800; background: #6fdc9a; color: #0b2a17;
  border-radius: 3px; padding: 0 3px; }
.tt-QB { background: #c9405a; } .tt-RB { background: #0f8f7c; }
.tt-WR { background: #2f72c0; } .tt-TE { background: #c87420; }
.tt-K { background: #8257bd; } .tt-DST { background: #5f6472; }
.tt-OTHER { background: #4b5263; }
@media (max-width: 640px) {
  .tt-team, .tt-tile { width: 100px; }
  .tt-name { font-size: 0.74rem; }
}
/* Fit: the columns share the full width, with smaller tiles. */
.tt-fit { overflow: visible; max-height: none; }
.tt-fit .tt { width: 100%; table-layout: fixed; }
/* No pinned left column; the names stay pinned to the top. */
.tt-fit .tt td:first-child { position: static; }
.tt-fit .tt thead th:first-child { left: auto; }
.tt-fit .tt-team, .tt-fit .tt-tile { width: auto; }
.tt-fit .tt-tile { height: 54px; padding: 4px 6px; line-height: 1.3; }
/* The page scrolls, not the grid: keep the names below Streamlit's top bar. */
.tt-fit .tt thead th { top: 3.75rem; }
.tt-fit .tt-team img { width: 30px; height: 30px; margin-bottom: 2px; }
.tt-fit .tt-name { font-size: 0.78rem; }
/* All: every team on one screen. The columns share the width (scrolling
   sideways only on a narrow window), and the rows share the window's height
   less the top bar and team names (--rows is the longest roster). The grid
   doesn't scroll on its own. */
.tt-all { max-height: none; overflow-y: hidden; }
.tt-all .tt { width: 100%; min-width: calc(var(--cols) * 98px); table-layout: fixed; }
.tt-all .tt th, .tt-all .tt td { padding: 2px; }
.tt-all .tt thead th { padding: 6px 0 4px; }
.tt-all .tt-team, .tt-all .tt-tile { width: auto; }
.tt-all .tt-team img { width: 26px; height: 26px; margin-bottom: 2px; }
.tt-all .tt-tile { height: clamp(30px, calc((100vh - 10rem) / var(--rows) - 4px), 38px);
  padding: 2px 6px; display: flex; flex-direction: column; justify-content: center; }
.tt-all .tt-name { font-size: 0.76rem; line-height: 1.25; margin-top: 0; }
.tt-all .tt-pts { font-size: 0.6rem; line-height: 1.25; }
.tt-all .tt-st { top: 3px; }
.tt-all .tt-st + .tt-name { padding-right: 16px; }
</style>
"""

# ESPN injury statuses worth flagging on a tile, and the ones that mean the
# player isn't playing (the tile is dimmed).
STATUS_SHORT = {"QUESTIONABLE": "Q", "DOUBTFUL": "D", "OUT": "O",
                "INJURY_RESERVE": "IR", "SUSPENSION": "SUS", "DAY_TO_DAY": "Q",
                "Q": "Q", "D": "D", "O": "O", "IR": "IR", "SSPD": "SUS"}
NOT_PLAYING = {"O", "IR", "SUS"}


def short_name(name: str | None, position: str | None) -> str:
    """'Kenneth Walker III' -> 'K. Walker III'. Defenses and names that
    already start with initials ('D.J. Moore') are left alone."""
    name = (name or "").strip()
    first, _, rest = name.partition(" ")
    if position == "D/ST" or not rest or "." in first:
        return name
    return f"{first[0]}. {rest}"


def team_columns(rosters, teams, managers, ranks, me) -> list[dict]:
    """One column per team, `me` first and the rest by manager name.

    rosters: live_data roster rows for every team (espn_team_id,
        player_name, position, total_points, avg_points, nfl_team, bye,
        status, slot)
    teams: standings rows - espn_team_id, team_name, wins, losses, ties,
        logo_url
    managers / ranks: team id -> manager name / power ranking
    """
    by_team: dict = {}
    for player in rosters:
        by_team.setdefault(int(player["espn_team_id"]), []).append(player)

    columns = []
    for team in teams:
        team_id = int(team["espn_team_id"])
        record = f"{team.get('wins', 0)}-{team.get('losses', 0)}"
        if team.get("ties"):
            record += f"-{team['ties']}"
        groups: dict = {}
        for player in by_team.get(team_id, []):
            groups.setdefault(player.get("position") or "", []).append(player)
        for players in groups.values():
            players.sort(key=lambda p: (p.get("total_points") or 0.0,
                                        p.get("avg_points") or 0.0), reverse=True)
        columns.append({
            "team_id": team_id,
            "manager": managers.get(team_id) or team.get("team_name") or f"Team {team_id}",
            "team_name": team.get("team_name") or "",
            "record": record,
            "rank": ranks.get(team_id),
            "logo_url": team.get("logo_url"),
            "me": team_id == me,
            "groups": groups,
        })
    columns.sort(key=lambda c: (not c["me"], c["manager"].lower()))
    return columns


def rank_label(position: str, rank: int | None) -> str:
    """'RB12' - 'DEF3' for a defense, as on the Yahoo site."""
    if not rank:
        return ""
    return f"{'DEF' if position == 'D/ST' else position}{rank}"


def roster_ranks(rosters) -> dict:
    """player_id -> rank at their position by season points, among the
    league's rostered players."""
    by_position: dict = {}
    for player in rosters:
        by_position.setdefault(player.get("position") or "", []).append(player)
    ranks = {}
    for players in by_position.values():
        players = sorted(players, key=lambda p: p.get("total_points") or 0.0, reverse=True)
        for rank, player in enumerate(players, start=1):
            ranks[player["player_id"]] = rank
    return ranks


def _tile(player: dict, ranks: dict, compact: bool = False) -> str:
    """One player's tile: position, NFL team and bye; name; points per game
    and rank, marked NEW if a drafted trade moves him (trade_draft.py's
    moved). compact is two lines, for the whole league on one screen: the
    name, then NFL team (bye), points per game and rank - the color and the
    rank say the position."""
    position = player.get("position") or ""
    css = {"D/ST": "DST"}.get(position, position if position in POSITIONS else "OTHER")
    nfl = (player.get("nfl_team") or "").upper()
    bye = player.get("bye")
    top = " · ".join(filter(None, [position, f"{nfl} ({bye})" if nfl and bye else nfl]))
    total, avg = player.get("total_points"), player.get("avg_points")
    rank = rank_label(position, ranks.get(player.get("player_id")))
    points = " · ".join(filter(None, [f"{avg:.1f} PPG" if avg is not None else "", rank]))
    status = STATUS_SHORT.get(player.get("status") or "", "")
    if not status and player.get("slot") == "IR":
        status = "IR"
    detail = " · ".join(filter(None, [
        player.get("player_name"), position, nfl, f"bye week {bye}" if bye else "",
        f"{rank} by season points" if rank else "",
        f"{total:.1f} season points" if total is not None else "",
        f"{avg:.1f} per game" if avg is not None else "",
        f"status {player.get('status')}" if status else "",
        f"lineup slot {player.get('slot')}" if player.get("slot") else "",
        "comes over in the trade" if player.get("moved") else "",
    ]))
    dim = " tt-out" if status in NOT_PLAYING else ""
    dim += " tt-new" if player.get("moved") else ""
    badge = f'<b class="tt-st">{escape(status)}</b>' if status else ""
    name = f'<div class="tt-name">{escape(short_name(player.get("player_name"), position))}</div>'
    if compact:
        line = " · ".join(filter(None, [
            f"{nfl} ({bye})" if nfl and bye else nfl,
            f"{avg:.1f}" if avg is not None else "", rank,
        ]))
        lines = name + f'<div class="tt-pts">{escape(line)}</div>'
    else:
        lines = (f'<div class="tt-top">{escape(top)}</div>' + name
                 + f'<div class="tt-pts">{escape(points)}</div>')
    return (
        f'<div class="tt-tile tt-{css}{dim}" title="{escape(detail)}">{badge}'
        f'{lines}</div>'
    )


def grid_html(columns: list[dict], ranks: dict | None = None, fit: bool = False) -> str:
    """The grid as one HTML block, styles included. ranks maps player_id ->
    rank at their position. fit is the phone layout: two columns sharing
    the width, full-size tiles, and the page scrolls. Otherwise every team
    fits on one screen with two-line tiles."""
    ranks = ranks or {}
    if not columns:
        return ""
    present = {position for c in columns for position in c["groups"]}
    order = [p for p in POSITIONS if p in present] + sorted(present - set(POSITIONS))

    head = []
    for c in columns:
        logo = f'<img src="{escape(c["logo_url"])}" alt="">' if c.get("logo_url") else "<img alt=\"\">"
        sub = c["record"] + (f" · PR #{c['rank']}" if c.get("rank") else "")
        me = " tt-me" if c["me"] else ""
        head.append(
            f'<th><div class="tt-team{me}" title="{escape(c["team_name"])}">{logo}'
            f'<div class="tt-mgr">{escape(c["manager"])}</div>'
            f'<div class="tt-sub">{escape(c["team_name"])}</div>'
            f'<div class="tt-sub">{escape(sub)}</div></div></th>'
        )

    # Each column is one unbroken stack, position after position; a shorter
    # roster just ends sooner.
    stacks = [[p for position in order for p in c["groups"].get(position, [])]
              for c in columns]
    rows = max(len(stack) for stack in stacks)
    body = []
    for i in range(rows):
        cells = []
        for c, stack in zip(columns, stacks):
            me = " class=\"tt-me\"" if c["me"] else ""
            cells.append(f"<td{me}>{_tile(stack[i], ranks, compact=not fit)}</td>"
                         if i < len(stack) else "<td></td>")
        body.append("<tr>" + "".join(cells) + "</tr>")

    layout = ('class="tt-scroll tt-fit"' if fit else
              f'class="tt-scroll tt-all" style="--rows:{max(rows, 1)};--cols:{len(columns)}"')
    return (
        GRID_CSS + f'<div {layout}><table class="tt"><thead><tr>'
        + "".join(head) + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )
