import unittest

import power_rankings


def player(team, name, total, status="ACTIVE", slot="WR"):
    return {"espn_team_id": team, "player_id": name, "player_name": name, "position": "WR",
            "total_points": total, "avg_points": None, "status": status, "slot": slot}


TEAMS = [{"espn_team_id": team, "team_name": f"Team {team}", "wins": 1, "losses": 1, "ties": 0,
          "points_for": 200.0, "points_against": 200.0} for team in (1, 2, 3)]


def roster_scores(rosters):
    rankings, _ = power_rankings.build_power_rankings(TEAMS, [], rosters, [], 7, 14)
    return rankings.set_index("espn_team_id")["roster_talent_score"].to_dict()


class AvailabilityTests(unittest.TestCase):
    """Players who can't play don't count toward roster talent."""

    def test_who_can_play(self):
        for able in ({"status": "ACTIVE", "slot": "WR"}, {"status": "QUESTIONABLE", "slot": "BE"},
                     {"status": "DOUBTFUL", "slot": "BE"}, {}):
            self.assertTrue(power_rankings.can_play(able), able)
        for unable in ({"status": "OUT", "slot": "BE"}, {"status": "INJURY_RESERVE", "slot": "BE"},
                       {"status": "SUSPENSION", "slot": "BE"}, {"status": "ACTIVE", "slot": "IR"}):
            self.assertFalse(power_rankings.can_play(unable), unable)

    def rosters(self, star_status="ACTIVE"):
        return [
            player(1, "Star Receiver", 120.0, status=star_status, slot="BE"),
            player(1, "Spare Receiver", 40.0),
            player(2, "Good Receiver", 90.0),
            player(2, "Okay Receiver", 60.0),
            player(3, "Fine Receiver", 70.0),
            player(3, "Hurt Receiver", 0.0, status="INJURY_RESERVE", slot="IR"),
        ]

    def test_an_injured_star_stops_propping_his_team_up(self):
        healthy = roster_scores(self.rosters())
        out = roster_scores(self.rosters(star_status="OUT"))
        self.assertGreater(healthy[1], out[1])

    def test_cutting_a_hurt_player_doesnt_move_his_team(self):
        kept = roster_scores(self.rosters())
        cut = roster_scores([p for p in self.rosters() if p["player_name"] != "Hurt Receiver"])
        self.assertEqual(kept, cut)


if __name__ == "__main__":
    unittest.main()
