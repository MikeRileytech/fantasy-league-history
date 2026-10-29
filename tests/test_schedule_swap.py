import re
import unittest

import pandas as pd

import schedule_swap

# Four teams, three weeks. Week 1: 1 v 2, 3 v 4. Week 2: 1 v 3, 2 v 4.
# Week 3: 1 v 4, 2 v 3. Teams 3 and 4 both score 95 in week 2, when they
# don't play each other.
SCHEDULE = {1: [(1, 2), (3, 4)], 2: [(1, 3), (2, 4)], 3: [(1, 4), (2, 3)]}
SCORES = {1: {1: 100.0, 2: 90.0, 3: 80.0, 4: 110.0},
          2: {1: 70.0, 2: 120.0, 3: 95.0, 4: 95.0},
          3: {1: 60.0, 2: 85.0, 3: 105.0, 4: 100.0}}
MANAGERS = {3: "Cat", 4: "Dan", 1: "Ann", 2: "Bob"}  # standings order


def games(scores=SCORES, outcomes=None, drop=()):
    """One row per team per week, as league_data.load_matchups() gives
    them. outcomes overrides ESPN's recorded result for a (team, week);
    drop leaves out (team, week) rows."""
    outcomes = outcomes or {}
    rows = []
    for week, pairs in SCHEDULE.items():
        for a, b in pairs:
            for team, rival in ((a, b), (b, a)):
                if (team, week) in drop:
                    continue
                mine, theirs = scores[week][team], scores[week][rival]
                result = "W" if mine > theirs else "L" if mine < theirs else "T"
                rows.append({"week": week, "espn_team_id": team,
                             "opponent_espn_team_id": float(rival), "team_score": mine,
                             "opponent_score": theirs,
                             "outcome": outcomes.get((team, week), result)})
    return pd.DataFrame(rows)


class SwapRecordsTests(unittest.TestCase):
    def setUp(self):
        self.records = schedule_swap.swap_records(games())

    def test_every_team_with_every_schedule(self):
        # Worked out by hand: row = team, column = whose schedule it plays.
        expected = {
            1: {1: (1, 2, 0), 2: (1, 2, 0), 3: (0, 3, 0), 4: (1, 2, 0)},
            2: {1: (1, 2, 0), 2: (1, 2, 0), 3: (1, 2, 0), 4: (3, 0, 0)},
            3: {1: (2, 1, 0), 2: (1, 1, 1), 3: (2, 1, 0), 4: (1, 2, 0)},
            4: {1: (2, 0, 1), 2: (1, 2, 0), 3: (3, 0, 0), 4: (2, 1, 0)},
        }
        self.assertEqual(self.records, {(team, schedule): record
                                        for team, row in expected.items()
                                        for schedule, record in row.items()})

    def test_own_schedule_is_the_real_record(self):
        self.assertEqual(self.records[(3, 3)], (2, 1, 0))
        self.assertEqual(self.records[(1, 1)], (1, 2, 0))

    def test_the_week_a_schedule_meets_the_team_itself_it_plays_that_schedules_team(self):
        # Team 2 with team 4's schedule: week 2's opponent would be team 2
        # itself, so it plays team 4 - and beat it, 120 to 95.
        self.assertEqual(self.records[(2, 4)], (3, 0, 0))
        # Lose that week instead, and so does the swap.
        scores = {week: dict(row) for week, row in SCORES.items()}
        scores[2][2] = 90.0
        self.assertEqual(schedule_swap.swap_records(games(scores))[(2, 4)], (2, 1, 0))

    def test_equal_scores_tie(self):
        # Team 3 with team 2's schedule meets team 4 in week 2: 95 to 95.
        self.assertEqual(self.records[(3, 2)], (1, 1, 1))
        self.assertEqual(self.records[(4, 1)], (2, 0, 1))

    def test_scores_are_compared_to_the_hundredth(self):
        scores = {week: dict(row) for week, row in SCORES.items()}
        scores[2][4] = 95.00000000000001  # float noise from a CSV sum
        self.assertEqual(schedule_swap.swap_records(games(scores))[(3, 2)], (1, 1, 1))

    def test_a_game_that_really_happened_keeps_its_real_result(self):
        # Week 1, 1 v 2 at 100 apiece, recorded as a win for team 1: the
        # diagonal and the swap that replays that game both keep it.
        scores = {week: dict(row) for week, row in SCORES.items()}
        scores[1][2] = 100.0
        records = schedule_swap.swap_records(games(scores, outcomes={(1, 1): "W", (2, 1): "L"}))
        self.assertEqual(records[(1, 1)], (1, 2, 0))
        self.assertEqual(records[(2, 2)], (1, 2, 0))
        # Each team playing the other's schedule replays that week's game.
        self.assertEqual(records[(1, 2)], (1, 2, 0))
        self.assertEqual(records[(2, 1)], (1, 2, 0))

    def test_a_week_a_team_has_no_game_is_left_out(self):
        # Team 4's week 3 isn't saved: its own row loses that week, and so
        # does anyone playing its schedule.
        records = schedule_swap.swap_records(games(drop={(4, 3)}))
        self.assertEqual(records[(4, 4)], (1, 1, 0))
        self.assertEqual(records[(2, 4)], (2, 0, 0))
        # Team 1's week-3 opponent (team 4) has no score: that week is out too.
        self.assertEqual(records[(3, 1)], (1, 1, 0))

    def test_no_games(self):
        self.assertEqual(schedule_swap.swap_records(games().iloc[0:0]), {})


class AllPlayTests(unittest.TestCase):
    def setUp(self):
        self.table = schedule_swap.all_play(games()).set_index("espn_team_id")

    def test_every_score_against_every_other_score_that_week(self):
        # Week 2: teams 3 and 4 both score 95 - a tie here, though they
        # didn't play each other.
        self.assertEqual(self.table["all_play"].to_dict(),
                         {1: "2-7", 2: "5-4", 3: "4-4-1", 4: "6-2-1"})

    def test_expected_wins_and_luck(self):
        # Team 3 wins 4.5 of its 9 all-play games - 1.5 of its 3 real
        # games - but really won 2.
        expected = {1: 2 / 3, 2: 5 / 3, 3: 1.5, 4: 6.5 / 3}
        real = {1: 1, 2: 1, 3: 2, 4: 2}
        for team, wins in expected.items():
            self.assertAlmostEqual(self.table.loc[team, "expected_wins"], wins)
            self.assertAlmostEqual(self.table.loc[team, "luck"], real[team] - wins)

    def test_luckiest_first(self):
        self.assertEqual(list(self.table.index), [3, 1, 4, 2])

    def test_real_records_and_points_against(self):
        self.assertEqual(self.table["record"].to_dict(), {1: "1-2", 2: "1-2", 3: "2-1", 4: "2-1"})
        self.assertEqual(self.table["points_against"].to_dict(),
                         {1: 285.0, 2: 300.0, 3: 265.0, 4: 260.0})

    def test_a_real_tie_counts_half(self):
        scores = {week: dict(row) for week, row in SCORES.items()}
        scores[1][2] = 100.0  # week 1: 1 v 2 ties at 100
        table = schedule_swap.all_play(games(scores)).set_index("espn_team_id")
        self.assertEqual(table.loc[1, "record"], "0-2-1")
        self.assertEqual(table.loc[1, "all_play"], "1-7-1")
        self.assertAlmostEqual(table.loc[1, "luck"], 0.0)

    def test_scores_are_compared_to_the_hundredth(self):
        scores = {week: dict(row) for week, row in SCORES.items()}
        scores[2][4] = 95.00000000000001
        table = schedule_swap.all_play(games(scores)).set_index("espn_team_id")
        self.assertEqual(table.loc[3, "all_play"], "4-4-1")

    def test_no_games(self):
        table = schedule_swap.all_play(games().iloc[0:0])
        self.assertTrue(table.empty)
        self.assertEqual(list(table.columns), schedule_swap.ALL_PLAY_COLUMNS)


class FormattingTests(unittest.TestCase):
    def test_record_text(self):
        self.assertEqual(schedule_swap.record_text((5, 2, 0)), "5-2")
        self.assertEqual(schedule_swap.record_text((3, 3, 1)), "3-3-1")

    def test_steps(self):
        steps = {delta: schedule_swap.step(delta) for delta in
                 (0, 0.5, 1, 1.5, 2, 2.5, 3, 6, -0.5, -1, -2, -2.5, -5)}
        self.assertEqual(steps, {0: 0, 0.5: 1, 1: 1, 1.5: 2, 2: 2, 2.5: 3, 3: 3, 6: 3,
                                 -0.5: -1, -1: -1, -2: -2, -2.5: -3, -5: -3})

    def test_short_names(self):
        names = {1: "Mike Riley", 2: "Mike Linker", 3: "Kyle Schwartz", 4: "Brian Schwartz",
                 5: "Bill Schwartz", 6: "Joe Smith", 7: "Joe Stone", 8: "Unknown"}
        self.assertEqual(schedule_swap.short_names(names), {
            1: "Mike R.", 2: "Mike L.", 3: "Kyle", 4: "Brian", 5: "Bill",
            6: "Joe Smith", 7: "Joe Stone", 8: "Unknown"})


class MatrixHtmlTests(unittest.TestCase):
    def setUp(self):
        self.html = schedule_swap.matrix_html(schedule_swap.swap_records(games()), MANAGERS)
        body = self.html.split("<tbody>")[1]
        self.rows = [re.findall(r'<div class="([^"]*)" title="([^"]*)">([^<]*)</div>', row)
                     for row in body.split("<tr>")[1:]]

    def cell(self, team, schedule):
        order = list(MANAGERS)
        return self.rows[order.index(team)][order.index(schedule)]

    def test_rows_and_columns_in_standings_order(self):
        head = self.html.split("<thead>")[1].split("</thead>")[0]
        self.assertEqual(re.findall(r'<th class="ss-k\d+" title="[^"]*"><span>([^<]*)</span>', head),
                         ["Cat", "Dan", "Ann", "Bob"])
        names = re.findall(r'<span class="ss-full">([^<]*)</span>', self.html)
        self.assertEqual(names, ["Cat", "Dan", "Ann", "Bob"])
        self.assertEqual([record for _, _, record in self.rows[0]], ["2-1", "1-2", "2-1", "1-1-1"])

    def test_the_real_records_are_the_diagonal(self):
        for team in MANAGERS:
            css, _, _ = self.cell(team, team)
            self.assertIn("ss-real", css)
        self.assertEqual(self.html.split("<tbody>")[1].count("ss-real"), 4)

    def test_fills_say_how_many_wins_better_or_worse(self):
        self.assertEqual(self.cell(2, 4)[0], "ss-c ss-m2")        # 3-0 for a 1-2 team
        self.assertEqual(self.cell(4, 3)[0], "ss-c ss-m1")        # 3-0 for a 2-1 team
        self.assertEqual(self.cell(4, 1)[0], "ss-c ss-m1 ss-longer")  # half a win better
        self.assertEqual(self.cell(3, 2)[0], "ss-c ss-f1 ss-longer")  # half a win worse
        self.assertEqual(self.cell(1, 3)[0], "ss-c ss-f1")        # 0-3 for a 1-2 team
        self.assertEqual(self.cell(1, 2)[0], "ss-c")              # the same record

    def test_longer_records_are_marked_to_shrink_on_a_phone(self):
        records = {(1, 1): (10, 3, 0), (1, 2): (9, 3, 1), (2, 1): (3, 10, 0), (2, 2): (1, 12, 0)}
        html = schedule_swap.matrix_html(records, {1: "Ann", 2: "Bob"})
        cells = re.findall(r'<div class="([^"]*)" title="[^"]*">([^<]*)</div>', html)
        self.assertEqual(cells, [("ss-c ss-real ss-long", "10-3"), ("ss-c ss-f1 ss-longer", "9-3-1"),
                                 ("ss-c ss-m2 ss-long", "3-10"), ("ss-c ss-real ss-long", "1-12")])

    def test_cells_say_whose_schedule_and_by_how_much(self):
        self.assertEqual(self.cell(2, 4)[1],
                         "Bob with Dan&#x27;s schedule: 3-0 · real record 1-2, +2 wins")
        self.assertEqual(self.cell(3, 2)[1],
                         "Cat with Bob&#x27;s schedule: 1-1-1 · real record 2-1, −0.5 wins")
        self.assertEqual(self.cell(1, 2)[1],
                         "Ann with Bob&#x27;s schedule: 1-2 · real record 1-2, the same")
        self.assertEqual(self.cell(1, 1)[1], "Ann&#x27;s real record: 1-2")

    def test_each_schedule_lights_up_with_its_records(self):
        self.assertIn(".ss:has(td.ss-k3:hover) th.ss-k3", self.html)
        self.assertNotIn("ss-k4", self.html)

    def test_names_are_escaped(self):
        html = schedule_swap.matrix_html(schedule_swap.swap_records(games()),
                                         {**MANAGERS, 1: "<b>Ann</b> & Co"})
        self.assertNotIn("<b>Ann", html)
        self.assertIn("&lt;b&gt;Ann&lt;/b&gt; &amp; Co", html)

    def test_teams_without_games_are_left_out(self):
        html = schedule_swap.matrix_html(schedule_swap.swap_records(games()),
                                         {**MANAGERS, 9: "Zed"})
        self.assertNotIn("Zed", html)
        self.assertEqual(schedule_swap.matrix_html({}, MANAGERS), "")


if __name__ == "__main__":
    unittest.main()
