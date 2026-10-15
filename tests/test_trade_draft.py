import unittest
from types import SimpleNamespace

import live_data
import trade_draft
import trade_grid


def player(team, name, position, total=0.0, avg=None, **extra):
    return {"espn_team_id": team, "player_id": name, "player_name": name,
            "position": position, "total_points": total, "avg_points": avg, **extra}


ROSTERS = [
    player(1, "Josh Allen", "QB", 80.0, 26.7, nfl_team="BUF", slot="QB"),
    player(1, "Bijan Robinson", "RB", 70.0, 23.3, nfl_team="ATL", slot="RB"),
    player(1, "Saquon Barkley", "RB", 60.0, 20.0, nfl_team="PHI", slot="IR"),
    player(2, "Lamar Jackson", "QB", 90.0, 30.0, nfl_team="BAL", slot="QB"),
    player(2, "Ja'Marr Chase", "WR", 85.0, 28.3, nfl_team="CIN", slot="WR"),
]
# Week 7: BUF and CIN on bye. Week 8: everyone plays.
SCHEDULES = {
    "BUF": {6: "@KC", 8: "NYJ"},
    "ATL": {6: "TB", 7: "@NO", 8: "CAR"},
    "PHI": {6: "DAL", 7: "@NYG", 8: "WSH"},
    "BAL": {6: "CLE", 7: "PIT", 8: "@CIN"},
    "CIN": {6: "@PIT", 8: "BAL"},
}


class ApplyTradeTests(unittest.TestCase):
    def setUp(self):
        self.traded = trade_draft.apply_trade(ROSTERS, 1, 2, ["Bijan Robinson", "Saquon Barkley"],
                                              ["Ja'Marr Chase"])

    def test_players_change_teams_and_are_marked(self):
        teams = {p["player_name"]: (p["espn_team_id"], p.get("moved", False)) for p in self.traded}
        self.assertEqual(teams, {"Josh Allen": (1, False), "Bijan Robinson": (2, True),
                                 "Saquon Barkley": (2, True), "Lamar Jackson": (2, False),
                                 "Ja'Marr Chase": (1, True)})

    def test_moved_players_land_on_the_bench_unless_on_ir(self):
        slots = {p["player_name"]: p["slot"] for p in self.traded}
        self.assertEqual((slots["Bijan Robinson"], slots["Saquon Barkley"], slots["Ja'Marr Chase"]),
                         ("BE", "IR", "BE"))

    def test_rosters_are_left_alone(self):
        self.assertEqual(ROSTERS[1]["espn_team_id"], 1)
        self.assertNotIn("moved", ROSTERS[1])

    def test_a_player_only_moves_from_his_own_team(self):
        # Lamar is on team 2, so listing him as sent by team 1 does nothing.
        traded = trade_draft.apply_trade(ROSTERS, 1, 2, ["Lamar Jackson"], [])
        self.assertEqual(traded, ROSTERS)

    def test_depth_change(self):
        self.assertEqual(trade_draft.depth_change(ROSTERS, self.traded, 1), "RB 2 → 0 · WR 0 → 1")
        self.assertEqual(trade_draft.depth_change(ROSTERS, self.traded, 2), "RB 0 → 2 · WR 1 → 0")
        self.assertEqual(trade_draft.depth_change(ROSTERS, ROSTERS, 1), "")

    def test_team_players_in_grid_order(self):
        names = [p["player_name"] for p in trade_draft.team_players(self.traded, 2)]
        self.assertEqual(names, ["Lamar Jackson", "Bijan Robinson", "Saquon Barkley"])


class ByeTests(unittest.TestCase):
    def test_game(self):
        allen = ROSTERS[0]
        self.assertEqual(trade_draft.game(allen, 6, SCHEDULES), "@KC")
        self.assertEqual(trade_draft.game(allen, 7, SCHEDULES), "BYE")
        self.assertIsNone(trade_draft.game(player(1, "FA", "WR", nfl_team=None), 7, SCHEDULES))

    def test_unfilled_slots(self):
        slots = {"QB": 1, "RB": 1, "WR": 1, "RB/WR/TE": 1, "BE": 5, "IR": 1}
        team_one = [p for p in ROSTERS if p["espn_team_id"] == 1]
        # Week 7: Allen's on bye and Barkley's on IR - no QB, no WR, and
        # Bijan can fill RB but nobody's left for FLEX.
        self.assertEqual(trade_draft.unfilled_slots(team_one, 7, slots, SCHEDULES),
                         ["QB", "WR", "FLEX"])
        team_two = [p for p in ROSTERS if p["espn_team_id"] == 2]
        self.assertEqual(trade_draft.unfilled_slots(team_two, 8, {"QB": 1, "WR": 1}, SCHEDULES), [])
        self.assertEqual(trade_draft.unfilled_slots(team_two, 7, {"QB": 1, "WR": 1}, SCHEDULES), ["WR"])

    def test_flex_takes_whatever_is_spare(self):
        players = [player(1, "A", "RB", nfl_team="ATL"), player(1, "B", "RB", nfl_team="PHI"),
                   player(1, "C", "TE", nfl_team="ATL")]
        slots = {"RB": 1, "TE": 1, "RB/WR/TE": 1}
        self.assertEqual(trade_draft.unfilled_slots(players, 7, slots, SCHEDULES), [])
        self.assertEqual(trade_draft.unfilled_slots(players, 7, {**slots, "RB/WR/TE": 2},
                                                    SCHEDULES), ["FLEX"])


class ScheduleHtmlTests(unittest.TestCase):
    def setUp(self):
        traded = trade_draft.apply_trade(ROSTERS, 1, 2, [], ["Ja'Marr Chase"])
        self.html = trade_draft.schedule_html(
            [("Mike", "after the trade (you)", trade_draft.team_players(traded, 1))],
            range(6, 9), reg_season_weeks=7, schedules=SCHEDULES, slots={"QB": 1, "WR": 1})

    def test_byes_are_highlighted(self):
        body = self.html.split("<tbody>")[1]
        # Allen (BUF) and Chase (CIN) are both off in week 7.
        self.assertEqual(body.count('class="ros-g ros-bye"'), 2)
        self.assertIn('title="Week 7: bye">BYE<', body)

    def test_road_games_and_playoff_weeks(self):
        self.assertIn('title="Week 6: at KC">@KC<', self.html)
        self.assertIn('title="Week 8: vs NYJ">NYJ<', self.html)
        self.assertIn('<th colspan="2">Regular season</th>', self.html)
        self.assertIn('<th colspan="1" class="ros-po">🏆 Playoffs</th>', self.html)
        self.assertIn("Wk 6<small>this week</small>", self.html)

    def test_traded_players_are_tagged(self):
        self.assertEqual(self.html.split("</style>")[1].count('<b class="ros-tag">NEW</b>'), 1)

    def test_bye_row_flags_empty_starting_spots(self):
        foot = self.html.split('<tr class="ros-foot">')[1]
        # Week 7: two on bye and neither QB nor WR can be filled.
        self.assertIn("2<small>no QB/WR</small>", foot)
        self.assertEqual(foot.count("ros-short"), 1)
        # The tooltip names who's off.
        self.assertIn("Week 7: 2 on bye (J. Allen, J. Chase)", foot)

    def test_no_weeks_left(self):
        self.assertIn("over", trade_draft.schedule_html([], [], 14, SCHEDULES))


class GridMarkTests(unittest.TestCase):
    def test_moved_tiles_are_marked(self):
        traded = trade_draft.apply_trade(ROSTERS, 1, 2, ["Josh Allen"], [])
        teams = [{"espn_team_id": 1, "team_name": "A"}, {"espn_team_id": 2, "team_name": "B"}]
        html = trade_grid.grid_html(trade_grid.team_columns(traded, teams, {}, {}, me=1), fit=True)
        self.assertEqual(html.split("</style>")[1].count("tt-new"), 1)
        self.assertIn("comes over in the trade", html)


class ProScheduleTests(unittest.TestCase):
    def test_home_away_and_byes(self):
        games = {"1": [{"homeProTeamId": 2, "awayProTeamId": 12}],
                 "2": [{"homeProTeamId": 33, "awayProTeamId": 2}],
                 "3": []}
        data = {"settings": {"proTeams": [
            {"id": 0, "proGamesByScoringPeriod": {}},
            {"id": 2, "abbrev": "Buf", "proGamesByScoringPeriod": games},
        ]}}
        league = SimpleNamespace(espn_request=SimpleNamespace(get_pro_schedule=lambda: data))
        self.assertEqual(live_data._pro_schedules(league), {"BUF": {1: "KC", 2: "@BAL"}})

    def test_espn_failure_gives_nothing(self):
        def fail():
            raise RuntimeError("no")
        league = SimpleNamespace(espn_request=SimpleNamespace(get_pro_schedule=fail))
        self.assertEqual(live_data._pro_schedules(league), {})


if __name__ == "__main__":
    unittest.main()
