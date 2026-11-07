import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
from collections import defaultdict
import unittest
import pygame
from Street_Fighter.src.arena import Arena, decode_action
from Street_Fighter.src.main import build_parser, keyboard_action
from Street_Fighter.src.scripted_demo import scripted_actions


class GameplayTests(unittest.TestCase):
    def test_keyboard_players_still_move_independently(self):
        arena = Arena()
        before = [f.x for f in arena.fighters]
        keys = defaultdict(bool, {pygame.K_a: True, pygame.K_RIGHT: True})
        arena.step([keyboard_action(keys, 1), keyboard_action(keys, 2)])
        self.assertEqual([f.x for f in arena.fighters], [before[0] - 10, before[1] + 10])

    def test_demo_is_opt_in_and_composes_with_streaming(self):
        self.assertFalse(build_parser().parse_args([]).demo)
        args = build_parser().parse_args(['--demo', '--headless', '--stream', 'rtsp://localhost:8554/match-1'])
        self.assertTrue(args.demo and args.headless)
        self.assertEqual(args.stream_fps, 30)

    def test_scripted_routine_moves_attacks_jumps_and_terminates(self):
        first, second = Arena(), Arena()
        saw_jump = saw_attack = False
        for _ in range(first.max_steps):
            actions = scripted_actions(first)
            self.assertEqual(actions, scripted_actions(second))
            for action in actions:
                _, jump, attack = decode_action(action)
                saw_jump |= jump
                saw_attack |= bool(attack)
            result = first.step(actions)
            second.step(actions)
            self.assertEqual(first.state(), second.state())
            if result['done']:
                break
        self.assertTrue(first.done and saw_jump and saw_attack)
        self.assertTrue(any(f.health < 100 for f in first.fighters))
        first.reset()
        self.assertEqual(scripted_actions(first), scripted_actions(Arena()))


if __name__ == '__main__':
    unittest.main()
