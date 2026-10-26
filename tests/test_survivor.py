import unittest

import pandas as pd

import survivor


def games(weeks, season=2026, game_type="regular"):
    """weeks: list of {team_id: score}, one per week from week 1."""
    rows = []
    for week, scores in enumerate(weeks, start=1):
        for team, score in scores.items():
            rows.append({"season": season, "week": week, "espn_team_id": team,
                         "team_name": f"Team {team}", "manager": f"M{team}",
                         "team_score": score, "game_type": game_type})
    return pd.DataFrame(rows)


class StandingsTest(unittest.TestCase):
    def test_lowest_score_goes_out_each_week(self):
        contest = survivor.standings(games([
            {1: 100, 2: 90, 3: 80, 4: 70},
            {1: 60, 2: 95, 3: 99, 4: 200},
        ]), 2026)
        self.assertEqual([w["out"] for w in contest["weeks"]], [["M4"], ["M1"]])
        self.assertEqual(set(contest["alive"]), {"M2", "M3"})
        self.assertIsNone(contest["winner"])
        self.assertEqual(contest["through"], 2)

    def test_a_tie_for_lowest_eliminates_both(self):
        contest = survivor.standings(games([{1: 100, 2: 80.0, 3: 80.001, 4: 90}]), 2026)
        self.assertEqual(contest["weeks"][0]["out"], ["M2", "M3"])

    def test_last_one_standing_wins_and_later_weeks_are_ignored(self):
        contest = survivor.standings(games([
            {1: 100, 2: 90, 3: 80},
            {1: 100, 2: 90, 3: 300},
            {1: 1, 2: 1, 3: 1},
        ]), 2026)
        self.assertEqual(contest["winner"], "M1")
        self.assertEqual(contest["through"], 2)

    def test_no_one_goes_out_when_everyone_left_ties(self):
        contest = survivor.standings(games([{1: 100, 2: 90, 3: 80}, {1: 50, 2: 50}]), 2026)
        self.assertEqual(contest["weeks"][1]["out"], [])
        self.assertEqual(set(contest["alive"]), {"M1", "M2"})

    def test_a_week_missing_a_survivor_is_not_counted(self):
        contest = survivor.standings(games([{1: 100, 2: 90, 3: 80}, {1: 50}]), 2026)
        self.assertEqual(contest["through"], 1)

    def test_playoffs_and_other_seasons_do_not_count(self):
        frame = pd.concat([games([{1: 100, 2: 90}]),
                           games([{1: 10, 2: 90}], season=2025),
                           games([{1: 1, 2: 2}], game_type="playoff")])
        contest = survivor.standings(frame, 2026)
        self.assertEqual(contest["winner"], "M1")
        self.assertEqual(len(contest["weeks"]), 1)

    def test_card_names_the_eliminated_and_is_empty_before_week_one(self):
        self.assertEqual(survivor.card_html(survivor.standings(games([]).reindex(
            columns=["season", "week", "espn_team_id", "team_name", "manager",
                     "team_score", "game_type"]), 2026), 2026), "")
        card = survivor.card_html(survivor.standings(games([{1: 100, 2: 90, 3: 80}]), 2026), 2026)
        self.assertIn("<b>M3</b> is out", card)
        self.assertIn('data-stamp="2026-1"', card)


if __name__ == "__main__":
    unittest.main()
