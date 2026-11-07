import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
from collections import defaultdict
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import pygame
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fighter import Fighter


class GameplayTests(unittest.TestCase):
    def fighter(self, player, x):
        return Fighter(player, x, 310, False, [1, 1, (0, 0)],
                       pygame.Surface((1, 7)), [1] * 7, Mock())

    def test_keyboard_players_still_move_independently(self):
        one, two = self.fighter(1, 200), self.fighter(2, 300)
        keys = defaultdict(bool, {pygame.K_a: True, pygame.K_RIGHT: True})
        with patch('pygame.key.get_pressed', return_value=keys):
            one.move(1280, 720, two, False)
            two.move(1280, 720, one, False)
        self.assertEqual((one.rect.x, two.rect.x), (190, 310))

    def test_attack_animation_keeps_type_after_input_is_released(self):
        one, two = self.fighter(1, 200), self.fighter(2, 290)
        one.move(1280, 720, two, False, defaultdict(bool, {pygame.K_t: True}))
        self.assertTrue(one.attacking)
        one.move(1280, 720, two, False, defaultdict(bool))
        self.assertEqual(one.attack_type, 2)
        self.assertEqual(two.health, 90)
        one.update()
        self.assertEqual(one.action, 4)


if __name__ == '__main__':
    unittest.main()
