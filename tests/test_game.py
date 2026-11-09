import copy
import json
from pathlib import Path
import tempfile
import unittest

from Street_Fighter.src.arena import Arena, ACTIONS, OBSERVATION_NAMES, encode_action, specification, ATTACK_BALANCE
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
        arena.step([attack, 0])
        for _ in range(11):
            result = arena.step([0, 0])
        self.assertEqual(result["rewards"], [0.1, -0.1])
        self.assertEqual(arena.fighters[1].health, 90)
        for _ in range(10):
            arena.step([attack, 0])
        self.assertEqual(arena.fighters[1].health, 90)
        for _ in range(40):
            arena.step([attack, 0])
        self.assertLess(arena.fighters[1].health, 90)

    def test_grounded_bodies_cannot_cross(self):
        from Street_Fighter.src.arena import body_box
        arena = Arena()
        for _ in range(60):
            arena.step([encode_action(move=1), encode_action(move=-1)])
            a, b = arena.fighters
            self.assertLess(a.x, b.x)
            self.assertLessEqual(body_box(a)[2], body_box(b)[0])

    def test_grimes_can_jump_over_and_shoggoth_turn_is_delayed(self):
        from Street_Fighter.src.arena import body_box, SHOGGOTH_TURN_DELAY
        for reverse in (False, True):
            arena = Arena()
            a, b = arena.fighters
            a.x, b.x = (650, 400) if reverse else (225, 400)
            a.flip, b.flip = reverse, not reverse
            move = -1 if reverse else 1
            crossed = False
            for tick in range(50):
                old_side, old_flip = a.x < b.x, b.flip
                arena.step([encode_action(move=move, jump=tick == 0), 0])
                if old_side != (a.x < b.x):
                    crossed = True
                    self.assertEqual(b.flip, old_flip)
                    self.assertEqual(b.turn_wait, SHOGGOTH_TURN_DELAY)
            self.assertTrue(crossed)
            self.assertFalse(a.jump)
            self.assertEqual(b.flip, a.x < b.x)
            self.assertTrue(body_box(a)[2] <= body_box(b)[0] or body_box(b)[2] <= body_box(a)[0])

    def test_body_separation_at_walls_and_on_landing(self):
        from Street_Fighter.src.arena import body_box
        for x1, x2 in [(0, 80), (920, 840), (400, 400)]:
            arena = Arena()
            a, b = arena.fighters
            a.x, b.x = x1, x2
            a.y, a.vel_y, a.jump = arena.floor_y - 2, 8, True
            arena.step([0, 0])
            boxes = [body_box(a), body_box(b)]
            self.assertTrue(boxes[0][2] <= boxes[1][0] or boxes[1][2] <= boxes[0][0])
            for f in arena.fighters:
                self.assertTrue(0 <= f.x <= arena.width - 80)

    def test_shoggoth_waits_full_turn_delay_and_does_not_turn_mid_attack(self):
        from Street_Fighter.src.arena import SHOGGOTH_TURN_DELAY
        arena = Arena()
        a, b = arena.fighters
        a.x, b.x = 700, 400
        arena.step([0, encode_action(attack=1)])
        for _ in range(SHOGGOTH_TURN_DELAY):
            arena.step([0, 0])
            self.assertTrue(b.flip)
        while b.attacking:
            arena.step([0, 0])
            self.assertTrue(b.flip)
        arena.step([0, 0])
        self.assertFalse(b.flip)

    def test_punch_knocks_back_once_and_stays_inside_walls(self):
        for grimes_x, shoggoth_x in [(400, 650), (650, 400), (0, 250)]:
            arena, _ = self.shoggoth_attack(grimes_x, shoggoth_x)
            a = arena.fighters[0]
            self.assertEqual(a.health, 86)
            self.assertGreaterEqual(a.x, 0)
            self.assertLessEqual(a.x, arena.width - 80)
            if grimes_x > shoggoth_x:
                self.assertGreater(a.x, grimes_x)
            elif grimes_x:
                self.assertLess(a.x, grimes_x)

    def test_jump_avoids_hit_only_after_vertical_clearance(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        arena.step([encode_action(attack=1), encode_action(jump=True)])
        self.assertEqual(arena.fighters[1].health, 100)  # Windup has no damage.
        arena.reset()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        arena.step([0, encode_action(jump=True)])
        for _ in range(9):
            arena.step([0, 0])
        self.assertLessEqual(arena.fighters[1].y + 180, arena.fighters[0].y)
        arena.step([encode_action(attack=1), encode_action(move=-1)])
        self.assertEqual(arena.fighters[1].health, 100)
        self.assertEqual(arena.fighters[1].x, 527)

    def test_grimes_can_hit_an_opponent_entering_during_swing(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 700
        arena.step([encode_action(attack=1), 0])
        for _ in range(15):
            arena.step([0, encode_action(move=-1)])
        self.assertTrue(arena.fighters[0].attacking)
        self.assertEqual(arena.fighters[1].health, 90)

    def test_simultaneous_knockout_has_no_first_player_advantage(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        for fighter in arena.fighters:
            fighter.health = 10
        for fighter in arena.fighters:
            fighter.attacking, fighter.attack_type = True, 2
            fighter.action, fighter.frame_index, fighter.animation_tick = 4, 3, 2
        result = arena.step([0, 0])
        self.assertTrue(result["terminated"])
        self.assertFalse(result["truncated"])
        self.assertIsNone(result["winner"])
        self.assertEqual([f.health for f in arena.fighters], [0, 0])
        self.assertEqual(result["rewards"], [0, 0])
        with self.assertRaises(ValueError):
            arena.step([0, 0])

    def shoggoth_attack(self, grimes_x, shoggoth_x, steps=24):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = grimes_x, shoggoth_x
        arena.fighters[1].flip = grimes_x < shoggoth_x
        health = []
        for step in range(steps):
            arena.step([0, encode_action(attack=1) if step == 0 else 0])
            health.append(arena.fighters[0].health)
        return arena, health

    def test_shoggoth_arm_hits_during_extension_once_both_directions(self):
        for grimes_x, shoggoth_x in [(400, 650), (650, 400)]:
            with self.subTest(grimes_x=grimes_x):
                arena, health = self.shoggoth_attack(grimes_x, shoggoth_x)
                self.assertEqual(health[:8], [100]*8)  # Windup cannot hit.
                self.assertEqual(health[8], 86)  # First extended frame makes solid contact.
                self.assertEqual(health[-1], 86)  # No repeated damage on active frames.

    def test_shoggoth_tip_requires_overlap_not_grazing(self):
        # Max extension ends at x=769; Grimes body begins at x+8.
        _, health = self.shoggoth_attack(750, 400)
        self.assertEqual(health[-1], 100)  # 11px overlap is only a graze.
        _, health = self.shoggoth_attack(749, 400)
        self.assertEqual(health[-1], 86)  # 12px is a solid hit.
        _, health = self.shoggoth_attack(780, 400)
        self.assertEqual(health[-1], 100)

    def test_shoggoth_arm_can_be_avoided_with_jump(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 650
        for step in range(24):
            arena.step([encode_action(jump=True) if step == 0 else 0,
                        encode_action(attack=1) if step == 0 else 0])
        self.assertEqual(arena.fighters[0].health, 100)

    def test_slam_and_grimes_react_on_contact_frame_in_both_directions(self):
        for player, attack in [(2, 2), (1, 1), (1, 2)]:
            for reversed_sides in (False, True):
                with self.subTest(player=player, attack=attack, reversed=reversed_sides):
                    arena = Arena()
                    arena.fighters[0].x, arena.fighters[1].x = ((500, 400) if reversed_sides else (400, 500))
                    arena.fighters[1].flip = not reversed_sides
                    actions = [0, 0]; actions[player-1] = encode_action(attack=attack)
                    arena.step(actions)
                    target = arena.fighters[2-player]
                    for _ in range(10):
                        arena.step([0, 0])
                    self.assertEqual(target.health, 100)  # All windup frames.
                    arena.step([0, 0])
                    self.assertEqual(target.health, 100 - ATTACK_BALANCE[(player, attack)][0])
                    self.assertEqual(target.action, 5)  # Reaction on the same rendered frame.
                    self.assertEqual(arena.fighters[player-1].frame_index, 4)
                    for _ in range(14): arena.step([0, 0])
                    self.assertEqual(target.health, 100 - ATTACK_BALANCE[(player, attack)][0])

    def test_grimes_does_not_hit_empty_space_or_raised_tentacles(self):
        for attack in (1, 2):
            arena = Arena()
            arena.fighters[0].x, arena.fighters[1].x = 200, 700
            arena.step([encode_action(attack=attack), 0])
            for _ in range(24): arena.step([0, 0])
            self.assertEqual(arena.fighters[1].health, 100)

    def test_grimes_blade_accepts_shallow_contact_but_not_a_graze(self):
        for attack, grazing_x in [(1, 701), (2, 625)]:
            for overlap, expected in [(0, 100), (1, 100 - ATTACK_BALANCE[(1, attack)][0])]:
                arena = Arena()
                arena.fighters[0].x, arena.fighters[1].x = 400, grazing_x - overlap
                arena.step([encode_action(attack=attack), 0])
                for _ in range(23): arena.step([0, 0])
                self.assertEqual(arena.fighters[1].health, expected)

    def test_grimes_old_near_misses_now_connect(self):
        for attack, target_x in [(1, 695), (2, 620)]:
            arena = Arena()
            arena.fighters[0].x, arena.fighters[1].x = 400, target_x
            arena.step([encode_action(attack=attack), 0])
            for _ in range(23): arena.step([0, 0])
            self.assertEqual(arena.fighters[1].health, 100 - ATTACK_BALANCE[(1, attack)][0])

    def test_grimes_shallow_contact_also_works_facing_left(self):
        for attack, just_outside in [(1, 393), (2, 469)]:
            for adjustment, expected in [(0, 100), (1, 100 - ATTACK_BALANCE[(1, attack)][0])]:
                arena = Arena()
                arena.fighters[0].x, arena.fighters[1].x = 700, just_outside + adjustment
                arena.step([encode_action(attack=attack), 0])
                for _ in range(23): arena.step([0, 0])
                self.assertEqual(arena.fighters[1].health, expected)

    def test_raised_tentacle_is_not_a_hurtbox(self):
        arena = Arena()
        grimes, shoggoth = arena.fighters
        grimes.x, shoggoth.x = 400, 500
        grimes.y = 100
        grimes.attacking, grimes.attack_type = True, 1
        grimes.action, grimes.frame_index, grimes.animation_tick = 3, 3, 2
        shoggoth.attacking, shoggoth.attack_type = True, 2
        shoggoth.action, shoggoth.frame_index = 4, 2
        arena.step([0, 0])
        self.assertEqual(shoggoth.health, 100)

    def test_hit_interrupts_slam_before_contact(self):
        arena = Arena()
        grimes, shoggoth = arena.fighters
        grimes.x, shoggoth.x = 400, 500
        grimes.attacking, grimes.attack_type = True, 1
        grimes.action, grimes.frame_index, grimes.animation_tick = 3, 3, 2
        shoggoth.attacking, shoggoth.attack_type = True, 2
        shoggoth.action, shoggoth.frame_index = 4, 2
        arena.step([0, 0])
        self.assertFalse(shoggoth.attacking)
        for _ in range(24): arena.step([0, 0])
        self.assertEqual(grimes.health, 100)

    def test_attack_balance_values_and_full_recovery_lock(self):
        for (player, attack), (damage, recovery) in {
                (1, 1): (10, 12), (1, 2): (12, 18), (2, 1): (14, 30), (2, 2): (18, 42)}.items():
            with self.subTest(player=player, attack=attack):
                self.assertEqual(ATTACK_BALANCE[(player, attack)], (damage, recovery))
                arena = Arena()
                fighter = arena.fighters[player - 1]
                actions = [0, 0]; actions[player - 1] = encode_action(attack=attack)
                arena.step(actions)
                while fighter.attacking: arena.step([0, 0])
                self.assertEqual(fighter.attack_cooldown, recovery)
                start_x, start_y = fighter.x, fighter.y
                actions[player - 1] = encode_action(move=1, jump=True, attack=attack)
                for remaining in range(recovery - 1, -1, -1):
                    arena.step(actions)
                    self.assertEqual(fighter.attack_cooldown, remaining)
                    self.assertEqual((fighter.x, fighter.y), (start_x, start_y))
                    self.assertFalse(fighter.attacking or fighter.jump)
                arena.step(actions)
                self.assertEqual(fighter.x, start_x + (14 if player == 1 else 10))
                self.assertTrue(fighter.jump and fighter.attacking)

    def test_interruption_and_hit_reaction_do_not_erase_recovery(self):
        arena = Arena()
        grimes, shoggoth = arena.fighters
        grimes.x, shoggoth.x = 400, 500
        grimes.attacking, grimes.attack_type = True, 1
        grimes.action, grimes.frame_index, grimes.animation_tick = 3, 3, 2
        shoggoth.attacking, shoggoth.attack_type = True, 2
        shoggoth.action, shoggoth.frame_index = 4, 2
        arena.step([0, 0])
        self.assertEqual(shoggoth.attack_cooldown, 42)
        for _ in range(10): arena.step([0, encode_action(move=1, jump=True, attack=2)])
        self.assertEqual(shoggoth.attack_cooldown, 32)
        self.assertEqual(shoggoth.x, 537)
        self.assertFalse(shoggoth.attacking or shoggoth.jump)

    def test_recovery_keeps_gravity_active(self):
        arena = Arena()
        fighter = arena.fighters[1]
        fighter.y -= 100
        fighter.jump = True
        fighter.attack_cooldown = 42
        arena.step([0, encode_action(move=1, jump=True)])
        self.assertEqual(fighter.y, arena.floor_y - 98)
        self.assertEqual(fighter.x, 700)

    def test_knockout_and_time_limit(self):
        arena = Arena()
        arena.fighters[0].x, arena.fighters[1].x = 400, 500
        arena.fighters[1].health = 10
        arena.step([encode_action(attack=2), 0])
        for _ in range(11):
            result = arena.step([0, 0])
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
