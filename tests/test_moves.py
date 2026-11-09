import unittest
from Street_Fighter.src.arena import Arena, ACTIONS, encode_action, learning_specification
from weight_space.lab import WeightLab

class MoveAccessTests(unittest.TestCase):
    def test_every_move_combination_is_exposed_and_both_attacks_start(self):
        interface=learning_specification()
        self.assertEqual(len(interface['actions']),18)
        for move in (-1,0,1):
            for jump in (False,True):
                for attack in (0,1,2):
                    action=encode_action(move,jump,attack)
                    self.assertEqual(interface['actions'][action],dict(id=action,move=move,jump=jump,attack=attack))
                    for player in (1,2):
                        arena=Arena()
                        commands=[0,0];commands[player-1]=action
                        step=arena.step(commands)
                        fighter=arena.fighters[player-1]
                        self.assertEqual(player in step['attacks_started'],bool(attack))
                        if attack:self.assertEqual(fighter.attack_type,attack)
                        if jump:self.assertTrue(fighter.jump)
        self.assertEqual(set(a for _,_,a in ACTIONS),{0,1,2})
