import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

import league_data
import live_data
import power_history
import season_refresh

TEAMS = {1: SimpleNamespace(team_id=1, team_name="Team 1"),
         2: SimpleNamespace(team_id=2, team_name="Team 2")}
# ESPN player id -> (name, position). Gamma Receiver is a free agent until
# team 2 picks him up for week 3.
PLAYERS = {11: ("Alpha Back", "RB"), 12: ("Alpha Defense", "D/ST"),
           21: ("Beta Back", "RB"), 22: ("Beta Receiver", "WR"), 23: ("Gamma Receiver", "WR")}
POINTS = {1: {11: 20.0, 12: 5.0, 21: 10.0, 22: 0.0, 23: 6.0},
          2: {11: 30.0, 12: 7.0, 21: 12.0, 22: 9.0, 23: 14.0},
          3: {11: 25.0, 12: 1.0, 21: 8.0, 22: 15.0, 23: 11.0}}
DRAFT = [SimpleNamespace(playerId=pid) for pid in (11, 21, 22, 12)]


def lineup(ids, week, bench=(), scored=True):
    return [SimpleNamespace(playerId=pid, name=PLAYERS[pid][0], position=PLAYERS[pid][1],
                            slot_position="BE" if pid in bench else PLAYERS[pid][1],
                            points=POINTS[week][pid] if scored else 0)
            for pid in ids]


def box(week, home_score, away_score, away_ids=(21, 22), bench=(), scored=True):
    return SimpleNamespace(
        home_team=TEAMS[1], away_team=TEAMS[2], home_score=home_score, away_score=away_score,
        home_lineup=lineup((11, 12), week, bench, scored),
        away_lineup=lineup(away_ids, week, bench, scored),
    )


class FakeLeague:
    """Two teams' box scores and player cards by week, shaped as espn_api
    returns them."""

    def __init__(self, unscored=(), reg_season_count=14, draft=DRAFT):
        self.unscored = set(unscored)
        self.teams = list(TEAMS.values())
        self.settings = SimpleNamespace(reg_season_count=reg_season_count)
        self.draft = draft
        self.card_calls = []

    def box_scores(self, week):
        if week in self.unscored:
            return [box(week, 0.0, 0.0, scored=False)]
        scores = {1: (120.0, 90.0), 2: (80.0, 130.0), 3: (100.0, 100.0)}[week]
        return [box(week, *scores, away_ids=(21, 22, 23) if week >= 3 else (21, 22))]

    def player_info(self, playerId):
        self.card_calls.append(list(playerId))
        found = [SimpleNamespace(playerId=pid, stats={
            0: {"points": sum(POINTS[w][pid] for w in POINTS)},
            **{w: {"points": POINTS[w][pid]} for w in POINTS},
            4: {"projected_points": 12.0},
        }) for pid in playerId]
        # As espn_api: a lone player comes back bare, none as None.
        if len(found) == 1:
            return found[0]
        return found or None


class ScoreboardTests(unittest.TestCase):
    def test_unfinalized_week_is_scored_from_the_starters(self):
        rows = power_history.scoreboard([box(1, 0.0, 0.0, bench={12})])
        self.assertEqual((rows[0]["home_score"], rows[0]["away_score"]), (20.0, 10.0))

    def test_byes_are_left_out(self):
        bye = SimpleNamespace(home_team=TEAMS[1], away_team=None, home_score=50.0,
                              away_score=0, home_lineup=[], away_lineup=[])
        self.assertEqual(power_history.scoreboard([bye]), [])


class RecordsThroughTests(unittest.TestCase):
    def test_counts_wins_points_and_opponents(self):
        teams, schedule = power_history.records_through({
            1: power_history.scoreboard([box(1, 110.5, 90.0)]),
            2: power_history.scoreboard([box(2, 100.0, 100.0)]),
        })
        by_id = {t["espn_team_id"]: t for t in teams}
        self.assertEqual((by_id[1]["wins"], by_id[1]["losses"], by_id[1]["ties"]), (1, 0, 1))
        self.assertEqual((by_id[2]["wins"], by_id[2]["losses"], by_id[2]["ties"]), (0, 1, 1))
        self.assertEqual(by_id[1]["points_for"], 210.5)
        self.assertEqual(by_id[2]["points_against"], 210.5)
        self.assertEqual(len(schedule), 4)
        self.assertIn({"espn_team_id": 2, "week": 1, "opponent_espn_team_id": 1}, schedule)


class RostersAsOfTests(unittest.TestCase):
    def rows(self, league, week, points):
        rows = power_history.rosters_as_of(league, league.box_scores(week), week, points)
        return {r["player_name"]: r for r in rows}

    def test_points_stop_at_the_week(self):
        by_name = self.rows(FakeLeague(), 2, {})
        self.assertEqual(by_name["Alpha Back"]["total_points"], 50.0)
        self.assertEqual(by_name["Alpha Back"]["avg_points"], 25.0)
        self.assertEqual(by_name["Alpha Defense"]["position"], "D/ST")
        # A week with no points (a bye) doesn't drag the average down.
        self.assertEqual(by_name["Beta Receiver"]["total_points"], 9.0)
        self.assertEqual(by_name["Beta Receiver"]["avg_points"], 9.0)
        self.assertNotIn("Gamma Receiver", by_name)

    def test_points_scored_as_a_free_agent_count(self):
        by_name = self.rows(FakeLeague(), 3, {})
        self.assertEqual(by_name["Gamma Receiver"]["espn_team_id"], 2)
        self.assertEqual(by_name["Gamma Receiver"]["total_points"], 31.0)

    def test_rows_follow_the_leagues_team_order(self):
        # As the live table's rosters do: ties are broken by row order.
        league = FakeLeague()
        league.teams.reverse()
        rows = power_history.rosters_as_of(league, league.box_scores(1), 1, {})
        self.assertEqual([r["espn_team_id"] for r in rows], [2, 2, 1, 1])

    def test_players_are_fetched_once_in_batches(self):
        league, points = FakeLeague(), {}
        with patch.object(power_history, "PLAYER_BATCH", 2):
            self.rows(league, 2, points)
            self.rows(league, 3, points)
        self.assertEqual(league.card_calls, [[11, 12], [21, 22], [23]])


class SaveWeeksTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(league_data, "PROCESSED_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_saves_each_week_and_skips_unfinished_ones(self):
        saved, notes = power_history.save_weeks(FakeLeague(unscored={3}), 2026, [1, 2, 3])
        self.assertEqual(saved, [1, 2])
        self.assertEqual(len(notes), 1)
        self.assertIn("week 3", notes[0])

        history = power_history.load_history(2026)
        self.assertEqual(sorted(history["week"].unique()), [1, 2])
        self.assertEqual(len(history), 4)
        week1 = history[history["week"] == 1].set_index("espn_team_id")
        self.assertEqual(week1.loc[1, "rank"], 1)
        self.assertEqual(power_history.missing_weeks(2026, 3), [3])

    def test_playoff_weeks_are_not_saved(self):
        saved, notes = power_history.save_weeks(FakeLeague(reg_season_count=1), 2026, [1, 2])
        self.assertEqual((saved, notes), ([1], []))

    def test_nothing_is_saved_without_the_draft(self):
        saved, notes = power_history.save_weeks(FakeLeague(draft=[]), 2026, [1])
        self.assertEqual(saved, [])
        self.assertIn("draft", notes[0])
        self.assertEqual(power_history.missing_weeks(2026, 1), [1])


class ChartRowsTests(unittest.TestCase):
    HISTORY = pd.DataFrame({"week": [10, 2, 9], "espn_team_id": [1, 1, 1], "team_name": "Team 1",
                            "rank": [1, 2, 3], "power_score": [50.0, 40.0, 30.0]})

    def test_weeks_in_order_then_the_live_table(self):
        live = pd.DataFrame({"espn_team_id": [1], "team_name": ["Team 1"], "rank": [4],
                             "power_score": [20.0], "wins": [3]})
        rows, order = power_history.chart_rows(self.HISTORY, live)
        self.assertEqual(order, ["2", "9", "10", "Now"])
        now = rows[rows["week"] == "Now"]
        self.assertEqual((now["rank"].tolist(), now["power_score"].tolist()), ([4], [20.0]))
        self.assertNotIn("wins", rows.columns)

    def test_no_now_without_the_live_table(self):
        for live in (None, pd.DataFrame()):
            rows, order = power_history.chart_rows(self.HISTORY, live)
            self.assertEqual(order, ["2", "9", "10"])
            self.assertEqual(sorted(rows["week"]), ["10", "2", "9"])


class RefreshOnceTests(unittest.TestCase):
    """season_refresh.refresh_once() with ESPN, GitHub and the importer
    stubbed: which commit it makes, given what is due."""

    POWER_FILE = season_refresh.PROCESSED_DIR / "power_rankings_2026.csv"
    SEASON_FILE = season_refresh.PROCESSED_DIR / "league_1_season_2026_matchups.csv"

    def setUp(self):
        self.commits = []
        league = SimpleNamespace(teams=[SimpleNamespace(wins=2, losses=1, ties=0)])
        patches = [
            patch.object(season_refresh, "_pushed", set()),
            patch.object(season_refresh, "_ranked", set()),
            patch.object(league_data, "season_in_progress", lambda: 2026),
            patch.object(live_data, "espn_credentials", lambda: (1, None, None)),
            patch.object(live_data, "fetch_live_league", lambda *args: league),
            patch.object(season_refresh, "finished_week", lambda league, counted: 3),
            patch.object(season_refresh, "saved_games", lambda league_id, season: 3),
            patch.object(season_refresh, "_secret", lambda name: "token"),
            patch.object(season_refresh, "_put_back", lambda before: None),
            patch.object(season_refresh, "fill_scores", lambda *args: None),
            patch.object(season_refresh, "decide_from_scores", lambda *args: None),
            patch.object(power_history, "missing_weeks", lambda season, finished: [1, 2, 3]),
            patch("espn_history_importer.import_season", lambda *args: None),
            patch("generate_manager_mapping.main", lambda: None),
            patch("propagate_manager_names.main", lambda: None),
            patch("github_store.put_files",
                  lambda token, repo, files, message: self.commits.append((files, message))),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_refresh(self, import_due, save_weeks, rankings_written, runs=1):
        before = {self.POWER_FILE: b"old", self.SEASON_FILE: b"old"}
        after = {self.POWER_FILE: b"new" if rankings_written else b"old",
                 self.SEASON_FILE: b"new" if import_due else b"old"}
        # Saved through week 2 before an import and 3 after it; 3 all along without one.
        saved = [2, 3] if import_due else [3] * runs
        with patch.object(season_refresh, "saved_through_week", side_effect=saved), \
                patch.object(season_refresh, "_tracked_files", side_effect=[before, after]), \
                patch.object(power_history, "save_weeks", save_weeks):
            return [season_refresh.refresh_once() for _ in range(runs)][-1]

    def test_rankings_alone_get_their_own_commit(self):
        self.run_refresh(False, lambda league, season, weeks: (weeks, []), True)
        self.assertEqual(len(self.commits), 1)
        files, message = self.commits[0]
        self.assertEqual(list(files), ["data/processed/power_rankings_2026.csv"])
        self.assertEqual(message, "Save 2026 power rankings for weeks 1, 2, 3")

    def test_failed_rankings_never_hold_back_the_season_data(self):
        def broken(*args):
            raise RuntimeError("ESPN fell over")

        result = self.run_refresh(True, broken, False)
        self.assertEqual(len(self.commits), 1)
        files, message = self.commits[0]
        self.assertEqual(list(files), ["data/processed/league_1_season_2026_matchups.csv"])
        self.assertEqual(message, "Update 2026 season data through week 3")
        self.assertIn("ESPN fell over", result)

    def test_rankings_are_not_committed_twice_before_the_pull(self):
        # The folder is put back after a commit, so until Streamlit Cloud
        # pulls it, the same weeks still look missing here.
        calls = []

        def save_weeks(league, season, weeks):
            calls.append(weeks)
            return weeks, []

        result = self.run_refresh(False, save_weeks, True, runs=2)
        self.assertEqual(len(self.commits), 1)
        self.assertEqual(calls, [[1, 2, 3]])
        self.assertIn("nothing to do", result)


if __name__ == "__main__":
    unittest.main()
