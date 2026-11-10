import json
from pathlib import Path
import tempfile
import unittest

from Street_Fighter.src.arena import Arena, FighterState, ending_states
from weight_space.lab import WeightLab
from weight_space.network import initialize, save


class DamageScoringTests(unittest.TestCase):
    def strike(self, arena, players):
        # Place real attacks on their contact frames, avoiding animation waits.
        for i, fighter in enumerate(arena.fighters):
            fighter.x, fighter.y = 400 + 100 * i, arena.floor_y
            fighter.flip, fighter.hit = bool(i), False
            fighter.attacking = fighter.player in players
            fighter.attack_type = 1 if fighter.attacking else 0
            fighter.attack_connected = False
            fighter.action, fighter.frame_index = 3, 4
            fighter.animation_tick, fighter.attack_cooldown = 0, 0
            fighter.knockback, fighter.vel_y = 0, 0
        return arena.step([0, 0])

    def test_healing_cannot_reverse_timeout_score_and_points_can_exceed_100(self):
        arena = Arena(max_steps=100)
        grimes, shoggoth = arena.fighters
        for _ in range(6): self.strike(arena, [2])
        self.assertEqual((grimes.health, shoggoth.damage_dealt), (16, 84))
        grimes.x, shoggoth.x = 920, 500
        grimes.knockback = 0
        result = arena.step([0, 0])
        self.assertEqual(result['powerups_collected'], [1])
        self.assertEqual((grimes.health, shoggoth.damage_dealt), (100, 84))
        for _ in range(3): self.strike(arena, [2])
        for _ in range(6): self.strike(arena, [1])
        arena.max_steps = arena.steps + 1
        result = arena.step([0, 0])
        self.assertEqual([f.health for f in arena.fighters], [58, 40])
        self.assertEqual([f.damage_dealt for f in arena.fighters], [60, 126])
        self.assertTrue(arena.powerups[1]['available'])
        self.assertEqual((result['reason'], result['winner']), ('time_limit', 2))
        self.assertEqual(ending_states(result['state']), [])
        arena.reset()
        self.assertEqual([f.damage_dealt for f in arena.fighters], [0, 0])
        self.assertEqual(len(arena.observe(1)), 33)

    def test_simultaneous_hits_on_last_tick_count_before_timeout(self):
        arena = Arena(max_steps=1)
        result = self.strike(arena, [1, 2])
        self.assertEqual([f.damage_dealt for f in arena.fighters], [10, 14])
        self.assertEqual(result['rewards'], [-0.04, 0.04])
        self.assertEqual((result['reason'], result['winner']), ('time_limit', 2))

    def test_equal_damage_is_draw_even_with_different_health(self):
        arena = Arena(max_steps=1)
        arena.fighters[0].health = 20
        result = arena.step([0, 0])
        self.assertEqual(result['reason'], 'time_limit')
        self.assertIsNone(result['winner'])

    def test_knockout_overrides_points_and_caps_overkill(self):
        arena = Arena(max_steps=1)
        arena.fighters[1].health = 3
        arena.fighters[1].damage_dealt = 90
        result = self.strike(arena, [1])
        self.assertEqual(arena.fighters[0].damage_dealt, 3)
        self.assertEqual((result['reason'], result['winner']), ('knockout', 1))
        self.assertEqual(result['rewards'], [0.03, -0.03])
        self.assertEqual(ending_states(result['state'])[-1]['fighters'][0]['damage_dealt'], 3)

    def test_same_tick_damage_and_healing_remain_in_agent_feedback(self):
        arena = Arena()
        # Move Grimes's cube into the contact fixture to collect on the hit tick.
        arena.powerups[0]['x'] = 400
        before = arena.observations()
        result = self.strike(arena, [2])
        self.assertEqual(arena.fighters[0].health, 100)
        self.assertEqual(arena.fighters[1].damage_dealt, 14)
        self.assertEqual(result['rewards'], [-0.14, 0.14])
        self.assertEqual(result['powerups_collected'], [1])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root/'model.json'
            save(model, initialize([33, 8, 18], zero=True))
            (root/'steps.jsonl').write_text(json.dumps({**result, 'actions':[0, 0], 'observations':before})+'\n')
            (root/'result.json').write_text(json.dumps({'winner':2, 'reason':'time_limit',
                'health':[100, 100], 'damage_dealt':[0, 14]}))
            for player in (1, 2):
                summary = WeightLab(model, root, root/f'lab-{player}', player).recording_summary()[0]
                self.assertEqual(summary['damage_dealt_self'], 0 if player == 1 else 14)
                self.assertEqual(summary['damage_dealt_opponent'], 14 if player == 1 else 0)
                self.assertEqual(summary['reason'], 'time_limit')
                self.assertEqual(summary['contact_event_count'], 1)
                event = summary['contact_events'][0]
                self.assertEqual(event['health_lost_self'], 14 if player == 1 else 0)

    def test_old_saved_fighters_load_without_damage_field(self):
        old = Arena().state()['fighters'][0]
        del old['damage_dealt']
        self.assertEqual(FighterState(**old).damage_dealt, 0)
