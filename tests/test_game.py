import copy
import json
from pathlib import Path
import tempfile
import unittest

from Street_Fighter.src.arena import Arena, ACTIONS, OBSERVATION_NAMES, encode_action, specification
from weight_space.game import DensePolicy, match
from weight_space.network import initialize, save


class ArenaTests(unittest.TestCase):
    def test_observation_and_action_contract(self):
        arena = Arena()
        self.assertEqual(len(ACTIONS), 18)
        self.assertEqual(len(set(ACTIONS)), 18)
        self.assertEqual(encode_action(), 0)
        self.assertEqual(len(OBSERVATION_NAMES), 31)
        self.assertEqual(len(arena.observe(1)), 31)
        self.assertEqual(arena.observe(1)[:14], arena.observe(2)[14:28])
        self.assertEqual(arena.observe(1)[28], -arena.observe(2)[28])
        self.assertEqual(specification()["output_size"], 18)

    def test_repeatable_steps_and_reset(self):
        arena, other = Arena(), Arena()
        initial = copy.deepcopy(arena.state())
        for tick in range(200):
            actions = [tick % 18, (tick * 7) % 18]
            self.assertEqual(arena.step(actions), other.step(actions))
        arena.reset()
        self.assertEqual(arena.state(), initial)

    def test_invalid_actions_do_not_advance_game(self):
        arena = Arena()
        before = arena.state()
        for actions in ([0, 18], [True, 0], [0], [0, -1], [0, 1.0]):
            with self.assertRaises(ValueError):
                arena.step(actions)
            self.assertEqual(arena.state(), before)

    def test_movement_bounds_jump_and_landing(self):
        arena = Arena()
        arena.step([encode_action(jump=True), 0])
        self.assertLess(arena.fighters[0].y, arena.floor_y)
        self.assertTrue(arena.fighters[0].jump)
        for _ in range(100):
            arena.step([encode_action(move=-1), encode_action(move=1)])
        self.assertEqual(arena.fighters[0].x, 0)
        self.assertEqual(arena.fighters[1].x, arena.width - 80)
        self.assertEqual(arena.fighters[0].y, arena.floor_y)
        self.assertFalse(arena.fighters[0].jump)

    def test_hit_damage_and_cooldown(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        attack = encode_action(attack=1)
        result = arena.step([attack, 0])
        self.assertEqual(result["rewards"], [0.1, -0.1])
        self.assertEqual(arena.fighters[1].health, 90)
        for _ in range(10):
            arena.step([attack, 0])
        self.assertEqual(arena.fighters[1].health, 90)
        for _ in range(40):
            arena.step([attack, 0])
        self.assertLess(arena.fighters[1].health, 90)

    def test_crossing_bodies_updates_facing(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 410
        arena.step([encode_action(move=1), encode_action(move=-1)])
        self.assertEqual([f.x for f in arena.fighters], [410, 400])
        self.assertTrue(arena.fighters[0].flip)
        self.assertFalse(arena.fighters[1].flip)

    def test_jump_avoids_hit_only_after_vertical_clearance(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        arena.step([encode_action(attack=1), encode_action(jump=True)])
        self.assertEqual(arena.fighters[1].health, 90)
        arena.reset()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        arena.step([0, encode_action(jump=True)])
        for _ in range(9):
            arena.step([0, 0])
        self.assertLessEqual(arena.fighters[1].y + 180, arena.fighters[0].y)
        arena.step([encode_action(attack=1), encode_action(move=-1)])
        self.assertEqual(arena.fighters[1].health, 100)
        self.assertEqual(arena.fighters[1].x, 490)

    def test_attack_checks_hit_only_at_start(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 700
        arena.step([encode_action(attack=1), 0])
        for _ in range(15):
            arena.step([0, encode_action(move=-1)])
        self.assertTrue(arena.fighters[0].attacking)
        self.assertEqual(arena.fighters[1].x, 550)
        self.assertEqual(arena.fighters[1].health, 100)

    def test_simultaneous_knockout_has_no_first_player_advantage(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        for fighter in arena.fighters:
            fighter.health = 10
        result = arena.step([encode_action(attack=1)] * 2)
        self.assertTrue(result["terminated"])
        self.assertFalse(result["truncated"])
        self.assertIsNone(result["winner"])
        self.assertEqual([f.health for f in arena.fighters], [0, 0])
        self.assertEqual(result["rewards"], [0, 0])
        with self.assertRaises(ValueError):
            arena.step([0, 0])

    def test_knockout_and_time_limit(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        arena.fighters[1].health = 10
        result = arena.step([encode_action(attack=2), 0])
        self.assertEqual(result["winner"], 1)
        self.assertEqual(result["reason"], "knockout")
        arena = Arena(max_steps=1)
        arena.fighters[1].health = 90
        result = arena.step([0, 0])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["winner"], 1)
        arena.reset()
        self.assertIsNone(arena.step([0, 0])["winner"])

    def test_raw_state_is_a_copy(self):
        arena = Arena()
        state = arena.state()
        state["fighters"][0]["health"] = -1
        self.assertEqual(arena.fighters[0].health, 100)


class MatchTests(unittest.TestCase):
    def model(self, action=0):
        model = initialize([31, 18], zero=True)
        model["layers"][0]["bias"][action] = 1
        return model

    def test_policy_freezes_parameters_and_decodes_argmax(self):
        model = self.model(encode_action(attack=1))
        policy = DensePolicy(model)
        model["layers"][0]["bias"] = [0] * 18
        self.assertEqual(policy.act(Arena().observe(1)), encode_action(attack=1))
        self.assertEqual(DensePolicy(self.model()).act(Arena().observe(1)), 0)
        with self.assertRaises(ValueError):
            DensePolicy(initialize())

    def test_match_records_can_replay_exactly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = root / "first.json", root / "second.json"
            save(first, self.model(encode_action(move=1, attack=1)))
            save(second, self.model(encode_action(move=-1, attack=2)))
            before = [first.read_bytes(), second.read_bytes()]
            result = match(first, second, root / "match", max_steps=180)
            self.assertEqual(result["status"], "complete")
            self.assertEqual([first.read_bytes(), second.read_bytes()], before)
            replay = Arena(max_steps=180)
            rows = [json.loads(line) for line in (root / "match/steps.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), result["steps"])
            for row in rows:
                self.assertEqual(row["observations"], replay.observations())
                outcome = replay.step(row["actions"])
                self.assertEqual(row["next_observations"], replay.observations())
                self.assertEqual(outcome["state"], row["state"])
                self.assertEqual(outcome["rewards"], row["rewards"])
            self.assertEqual(replay.winner, result["winner"])
            with self.assertRaises(FileExistsError):
                match(first, second, root / "match", max_steps=180)


if __name__ == "__main__":
    unittest.main()
