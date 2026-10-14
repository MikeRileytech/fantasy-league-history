import re
import unittest
from types import SimpleNamespace

import live_data
import trade_grid


def player(team, name, position, total, avg=None, **extra):
    return {"espn_team_id": team, "player_id": name, "player_name": name,
            "position": position, "total_points": total, "avg_points": avg, **extra}


TEAMS = [
    {"espn_team_id": 1, "team_name": "Laces Out", "wins": 2, "losses": 1, "ties": 0},
    {"espn_team_id": 2, "team_name": "Riley", "wins": 3, "losses": 0, "ties": 0},
    {"espn_team_id": 3, "team_name": "RG3sus", "wins": 0, "losses": 2, "ties": 1},
]
MANAGERS = {1: "Lance", 2: "Mike", 3: "Alex"}
ROSTERS = [
    player(1, "Josh Allen", "QB", 80.0, 26.7, nfl_team="Buf", bye=7),
    player(1, "Saquon Barkley", "RB", 60.0, 20.0, nfl_team="Phi"),
    player(1, "Bijan Robinson", "RB", 70.0, 23.3, nfl_team="Atl", bye=5, status="QUESTIONABLE"),
    player(2, "Jalen Hurts", "QB", 75.0, 25.0),
    player(2, "Lamar Jackson", "QB", 90.0, 30.0),
    player(2, "Seahawks D/ST", "D/ST", 20.0),
    player(3, "Kenneth Walker III", "RB", 40.0, 13.3, slot="IR", status="ACTIVE"),
]


class ShortNameTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(trade_grid.short_name("Kenneth Walker III", "RB"), "K. Walker III")
        self.assertEqual(trade_grid.short_name("D.J. Moore", "WR"), "D.J. Moore")
        self.assertEqual(trade_grid.short_name("Seahawks D/ST", "D/ST"), "Seahawks D/ST")
        self.assertEqual(trade_grid.short_name(None, "QB"), "")


class TeamColumnsTests(unittest.TestCase):
    def setUp(self):
        self.columns = trade_grid.team_columns(ROSTERS, TEAMS, MANAGERS, {2: 1, 1: 2, 3: 3}, me=2)

    def test_yours_first_then_by_manager(self):
        self.assertEqual([c["manager"] for c in self.columns], ["Mike", "Alex", "Lance"])
        self.assertTrue(self.columns[0]["me"])
        self.assertEqual(self.columns[1]["record"], "0-2-1")

    def test_players_grouped_best_first(self):
        lance = self.columns[2]
        self.assertEqual([p["player_name"] for p in lance["groups"]["RB"]],
                         ["Bijan Robinson", "Saquon Barkley"])


class GridHtmlTests(unittest.TestCase):
    def setUp(self):
        self.columns = trade_grid.team_columns(ROSTERS, TEAMS, MANAGERS, {2: 1}, me=2)
        self.html = trade_grid.grid_html(self.columns, trade_grid.roster_ranks(ROSTERS))

    def test_each_column_stacks_its_positions_without_gaps(self):
        body = self.html.split("<tbody>")[1]
        rows = [re.findall(r'class="tt-name">([^<]*)<', row) for row in body.split("<tr>")[1:]]
        self.assertEqual(rows, [["L. Jackson", "K. Walker III", "J. Allen"],
                                ["J. Hurts", "B. Robinson"],
                                ["Seahawks D/ST", "S. Barkley"]])
        self.assertEqual(body.count("<td></td>"), 2)

    def test_whole_league_fits_one_screen_with_two_line_tiles(self):
        self.assertIn('class="tt-scroll tt-all" style="--rows:3;--cols:3"', self.html)
        # Josh Allen: second of the three rostered QBs by season points.
        self.assertIn('<div class="tt-name">J. Allen</div><div class="tt-pts">BUF (7) · 26.7 · QB2</div>',
                      self.html)
        self.assertNotIn("tt-top", self.html.split("</style>")[1])
        self.assertIn("PR #1", self.html)

    def test_injuries_are_flagged(self):
        self.assertIn('<b class="tt-st">Q</b>', self.html)
        # On IR by lineup slot: flagged and dimmed. ACTIVE isn't flagged.
        self.assertIn('<b class="tt-st">IR</b>', self.html)
        self.assertIn("tt-out", self.html)
        self.assertEqual(self.html.count('class="tt-st"'), 2)

    def test_phone_shows_two_teams_with_full_tiles(self):
        pair = [c for c in self.columns if c["team_id"] in (2, 1)]
        html = trade_grid.grid_html(pair, trade_grid.roster_ranks(ROSTERS), fit=True)
        self.assertIn('class="tt-scroll tt-fit"', html)
        self.assertEqual(html.count('class="tt-team'), 2)
        self.assertIn("QB · BUF (7)", html)
        self.assertIn("26.7 PPG · QB2", html)
        self.assertIn("DEF1", html)

    def test_text_is_escaped(self):
        columns = trade_grid.team_columns(
            [player(1, "Bad <b>Name", "WR", 1.0)], TEAMS[:1], {1: "A&B"}, {}, me=1)
        html = trade_grid.grid_html(columns)
        self.assertNotIn("<b>Name", html)
        self.assertIn("A&amp;B", html)


class RosterRowsTests(unittest.TestCase):
    def espn_player(self, **extra):
        base = dict(playerId=9, name="Josh Allen", position="QB", total_points=80.123,
                    avg_points=26.71, proTeam="BUF", injuryStatus="ACTIVE",
                    lineupSlot="QB", schedule={str(w): {} for w in range(1, 19) if w != 7})
        return SimpleNamespace(**{**base, **extra})

    def test_rows_carry_the_trade_tool_fields(self):
        league = SimpleNamespace(teams=[SimpleNamespace(team_id=4, roster=[
            self.espn_player(),
            self.espn_player(playerId=10, name="Bills D/ST", position="D/ST",
                             proTeam="None", injuryStatus=None, lineupSlot="BE", schedule={}),
        ])])
        allen, defense = live_data._rosters(league)
        self.assertEqual((allen["espn_team_id"], allen["nfl_team"], allen["bye"],
                          allen["status"], allen["slot"], allen["total_points"]),
                         (4, "BUF", 7, "ACTIVE", "QB", 80.12))
        self.assertEqual((defense["nfl_team"], defense["bye"], defense["status"]),
                         (None, None, None))


if __name__ == "__main__":
    unittest.main()
