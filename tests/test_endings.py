import copy
import unittest

from Street_Fighter.src.arena import Arena, ANIMATION_STEPS, ANIMATION_TICKS, ending_states


class EndingTests(unittest.TestCase):
    def knockout(self, dead):
        arena = Arena()
        for player in dead:
            fighter = arena.fighters[player-1]
            fighter.health, fighter.alive = 0, False
            fighter.animate()
        arena.done, arena.reason, arena.winner = True, 'knockout', 2 if dead == [1] else 1 if dead == [2] else None
        return arena.state()

    def test_both_characters_show_every_death_frame_before_completion(self):
        for dead in ([1], [2], [1,2]):
            state = self.knockout(dead)
            original = copy.deepcopy(state)
            frames = ending_states(state)
            self.assertEqual(state, original)
            self.assertEqual(len(frames), 7 * ANIMATION_TICKS - 1)
            self.assertTrue(frames[-1]['ending_complete'])
            self.assertTrue(all(not f['ending_complete'] for f in frames[:-1]))
            for player in dead:
                self.assertEqual({f['fighters'][player-1]['frame_index'] for f in frames}, set(range(ANIMATION_STEPS[player-1][6])))
                self.assertTrue(all(f['fighters'][player-1]['action'] == 6 for f in frames))
            for frame in frames:
                self.assertEqual((frame['step'],frame['winner'],frame['powerups']), (state['step'],state['winner'],state['powerups']))
                self.assertEqual([f['health'] for f in frame['fighters']], [f['health'] for f in state['fighters']])

    def test_airborne_knockout_lands_and_time_limit_has_no_fake_death(self):
        state = self.knockout([1])
        state['fighters'][0].update(y=100, vel_y=-20, jump=True)
        frames = ending_states(state)
        self.assertEqual(frames[-1]['fighters'][0]['y'],310)
        self.assertEqual(frames[-1]['fighters'][0]['frame_index'],6)
        state['reason']='time_limit'
        self.assertEqual(ending_states(state),[])
        self.assertEqual(ending_states(Arena().state()),[])
