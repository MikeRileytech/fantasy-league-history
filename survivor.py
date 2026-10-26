"""
The league's survivor contest: each regular-season week, the lowest-scoring
team still alive is eliminated - every team tied for lowest goes out - and
the last one standing wins the pot.

Standings come from the saved season data (league_data.load_matchups), which
only holds weeks that are over: season_refresh saves a week once ESPN has
every NFL game of it final, so the standings move on after Monday night's
game ends.

card_html() draws them as a card floating over the home page. It can be
swiped away in any direction or closed with its Dismiss button, and stays
closed for the rest of the visit until a new week's results come in.
"""

import html

import pandas as pd


def _who(row) -> str:
    manager = row.get("manager")
    return manager if isinstance(manager, str) and manager else row["team_name"]


def standings(matchups: pd.DataFrame, season: int) -> dict:
    """The contest for `season`, week by week.

    Returns {"weeks": [{"week", "low", "out": [names]}], "alive": {name:
    last score}, "out": [{"name", "week", "score"}], "winner": name or None,
    "through": last week counted}. A week only counts once every team still
    alive has a result in it. If everyone left ties for lowest, no one goes
    out that week - eliminating them all would leave no winner.
    """
    games = matchups[(matchups["season"] == season) & (matchups["game_type"] == "regular")]
    names = {row["espn_team_id"]: _who(row) for _, row in games.iterrows()}
    alive = set(names)
    last = {}
    weeks, out = [], []
    for week, rows in games.groupby("week", sort=True):
        if len(alive) <= 1:
            break
        scores = {
            team: round(float(score), 2)
            for team, score in zip(rows["espn_team_id"], rows["team_score"])
            if team in alive
        }
        if set(scores) != alive:
            break  # someone still alive has no result yet
        low = min(scores.values())
        losers = {team for team, score in scores.items() if score == low}
        if losers == alive:
            losers = set()
        for team in sorted(losers, key=lambda t: names[t]):
            out.append({"name": names[team], "week": int(week), "score": low})
        alive -= losers
        last = scores
        weeks.append({"week": int(week), "low": low,
                      "out": sorted(names[t] for t in losers)})
    return {
        "weeks": weeks,
        "alive": dict(sorted(((names[t], last.get(t)) for t in alive),
                             key=lambda item: -(item[1] or 0))),
        "out": out,
        "winner": names[next(iter(alive))] if len(alive) == 1 and weeks else None,
        "through": weeks[-1]["week"] if weeks else 0,
    }


CSS = """
.sv-backdrop { position: fixed; inset: 0; z-index: 999990; background: rgba(8, 12, 20, 0.45);
  transition: opacity 0.25s; }
.sv-card { position: fixed; z-index: 999991; left: 50%; top: 50%;
  width: min(420px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow-y: auto;
  transform: translate(-50%, -50%); box-sizing: border-box; padding: 18px 18px 14px;
  background: #151b26; color: #fff; border: 1px solid #2c3546; border-radius: 16px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.5); font-family: inherit;
  touch-action: none; user-select: none; -webkit-user-select: none;
  transition: transform 0.25s, opacity 0.25s; }
.sv-card.sv-dragging { transition: none; }
.sv-gone { opacity: 0; pointer-events: none; }
.sv-hidden { display: none; }
.sv-title { font-size: 1.15rem; font-weight: 700; margin: 0 0 2px; }
.sv-sub { font-size: 0.78rem; color: #aab3c2; margin: 0 0 12px; }
.sv-news { background: #2a1d24; border: 1px solid #5c2b3b; border-radius: 10px;
  padding: 8px 10px; font-size: 0.86rem; margin-bottom: 12px; }
.sv-news b { color: #ff8fa3; }
.sv-win { background: #2a2410; border-color: #6b5714; }
.sv-win b { color: #ffd166; }
.sv-head { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  color: #7fd3c4; margin: 0 0 6px; }
.sv-alive { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.sv-chip { background: #1d3a33; border: 1px solid #2f6155; border-radius: 999px;
  padding: 3px 10px; font-size: 0.82rem; white-space: nowrap; }
.sv-chip span { color: #aab3c2; font-size: 0.74rem; margin-left: 4px; }
.sv-out { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-bottom: 12px; }
.sv-out td { padding: 3px 0; border-top: 1px solid #222a38; color: #c6cdd8; }
.sv-out td:first-child { color: #7d8799; width: 3.2em; }
.sv-out td:last-child { text-align: right; color: #7d8799; }
.sv-out s { text-decoration-color: #ff8fa3; }
.sv-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.sv-hint { font-size: 0.72rem; color: #7d8799; }
.sv-dismiss { background: #2c3546; color: #fff; border: 0; border-radius: 8px;
  padding: 7px 16px; font-size: 0.86rem; font-weight: 600; cursor: pointer; }
.sv-dismiss:hover { background: #3a4659; }
"""

# Follows the finger (or mouse) and flies off in the direction it was swiped
# once dragged far enough; a short drag springs back. Dismissing is
# remembered for this browser tab until a later week's standings arrive.
SCRIPT = """
(() => {
  const root = document.getElementById("sv-root");
  if (!root || root.dataset.ready) return;
  root.dataset.ready = "1";
  const key = "survivor-dismissed", stamp = root.dataset.stamp;
  const card = root.querySelector(".sv-card"), backdrop = root.querySelector(".sv-backdrop");
  try { if (sessionStorage.getItem(key) === stamp) { root.classList.add("sv-hidden"); return; } }
  catch (e) {}
  const center = "translate(-50%, -50%)";
  const close = (dx, dy) => {
    try { sessionStorage.setItem(key, stamp); } catch (e) {}
    const far = Math.max(window.innerWidth, window.innerHeight);
    const len = Math.hypot(dx, dy) || 1;
    card.style.transform = `${center} translate(${dx / len * far}px, ${dy / len * far}px)`;
    if (!dx && !dy) card.style.transform = `${center} scale(0.9)`;
    card.classList.add("sv-gone");
    backdrop.classList.add("sv-gone");
    setTimeout(() => root.classList.add("sv-hidden"), 260);
  };
  root.querySelector(".sv-dismiss").addEventListener("click", () => close(0, 0));
  backdrop.addEventListener("click", () => close(0, 0));
  let start = null;
  card.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".sv-dismiss")) return;
    start = { x: e.clientX, y: e.clientY };
    card.classList.add("sv-dragging");
    card.setPointerCapture(e.pointerId);
  });
  card.addEventListener("pointermove", (e) => {
    if (!start) return;
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    card.style.transform = `${center} translate(${dx}px, ${dy}px) rotate(${dx / 25}deg)`;
    card.style.opacity = String(Math.max(0.35, 1 - Math.hypot(dx, dy) / 400));
  });
  const release = (e) => {
    if (!start) return;
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    start = null;
    card.classList.remove("sv-dragging");
    card.style.opacity = "";
    if (Math.hypot(dx, dy) > 80) close(dx, dy);
    else card.style.transform = center;
  };
  card.addEventListener("pointerup", release);
  card.addEventListener("pointercancel", release);
})();
"""


def card_html(contest: dict, season: int) -> str:
    """The floating survivor card, or "" before any week is in."""
    if not contest["weeks"]:
        return ""
    esc = html.escape
    latest = contest["weeks"][-1]
    if contest["winner"]:
        news = (f'<div class="sv-news sv-win">🏆 <b>{esc(contest["winner"])}</b> '
                f'is the last survivor and wins the pot!</div>')
    elif latest["out"]:
        who = " and ".join(f"<b>{esc(n)}</b>" for n in latest["out"])
        tie = " (tied for the low score)" if len(latest["out"]) > 1 else ""
        news = (f'<div class="sv-news">Week {latest["week"]}: {who} '
                f'{"are" if len(latest["out"]) > 1 else "is"} out with '
                f'{latest["low"]:.2f}{tie}.</div>')
    else:
        news = (f'<div class="sv-news">Week {latest["week"]}: everyone left tied at '
                f'{latest["low"]:.2f} - no one is out.</div>')

    chips = "".join(
        f'<div class="sv-chip">{esc(name)}'
        + (f"<span>{score:.1f}</span>" if score is not None else "") + "</div>"
        for name, score in contest["alive"].items()
    )
    out_rows = "".join(
        f'<tr><td>Wk {o["week"]}</td><td><s>{esc(o["name"])}</s></td>'
        f'<td>{o["score"]:.2f}</td></tr>'
        for o in reversed(contest["out"])
    )
    alive_head = "Winner" if contest["winner"] else f'Still alive · {len(contest["alive"])}'
    out_block = (f'<div class="sv-head">Eliminated · {len(contest["out"])}</div>'
                 f'<table class="sv-out">{out_rows}</table>') if out_rows else ""
    stamp = f'{season}-{contest["through"]}'
    return (
        f'<style>{CSS}</style>'
        f'<div id="sv-root" data-stamp="{stamp}">'
        f'<div class="sv-backdrop"></div>'
        f'<div class="sv-card" role="dialog" aria-label="Survivor standings">'
        f'<div class="sv-title">🏝️ Survivor standings</div>'
        f'<div class="sv-sub">{season} · through week {contest["through"]} · '
        f'updates after Monday night\'s game</div>'
        f'{news}'
        f'<div class="sv-head">{alive_head}</div><div class="sv-alive">{chips}</div>'
        f'{out_block}'
        f'<div class="sv-foot"><span class="sv-hint">Swipe away or</span>'
        f'<button class="sv-dismiss" type="button">Dismiss</button></div>'
        f'</div></div>'
        f'<script>{SCRIPT}</script>'
    )
