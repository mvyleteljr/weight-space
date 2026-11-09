import unittest
from Street_Fighter.src.arena import Arena, encode_action, OBSERVATION_NAMES
from weight_space.network import initialize, with_action_feedback, forward

class PowerupTests(unittest.TestCase):
    def test_owner_only_full_restore_once_and_reset(self):
        for player in (1,2):
            a=Arena(); own=a.fighters[player-1]; other=a.fighters[2-player]
            self.assertEqual(a.observe(player)[31:],[1,1])
            # The owner must reach the opposite edge; the other cube does nothing.
            own.x=0 if player==1 else 920
            other.x=500;own.health=25
            a.step([0,0]);self.assertEqual(own.health,25)
            own.x=920 if player==1 else 0
            result=a.step([0,0])
            self.assertEqual(own.health,100)
            self.assertEqual(result['powerups_collected'],[player])
            self.assertEqual(result['rewards'],[0,0])
            self.assertEqual(a.observe(player)[31:],[0,1])
            self.assertEqual(a.observe(3-player)[31:],[1,0])
            own.health=40;a.step([0,0]);self.assertEqual(own.health,40)
            a.reset();self.assertTrue(all(c['available'] for c in a.powerups))
            self.assertEqual(len(a.observe(player)),33)

    def test_full_health_still_consumes_and_no_revive(self):
        a=Arena();a.fighters[0].x=920;a.fighters[1].x=500
        self.assertEqual(a.step([0,0])['powerups_collected'],[1])
        a.reset();a.fighters[0].x=920;a.fighters[0].health=0;a.fighters[1].x=500
        result=a.step([0,0])
        self.assertTrue(result['terminated']);self.assertEqual(result['powerups_collected'],[])

    def test_both_cubes_require_getting_past_opponent_and_are_reachable(self):
        for player in (1,2):
            for jump in (False,True):
                arena=Arena(max_steps=700)
                for _ in range(600):
                    cmds=[0,0];cmds[player-1]=encode_action(1 if player==1 else -1,jump)
                    result=arena.step(cmds)
                    if player in result['powerups_collected']:break
                self.assertEqual(arena.powerups[player-1]['available'],not jump)
                self.assertTrue(arena.powerups[2-player]['available'])

    def test_feedback_is_appended_after_cube_inputs_and_legacy_can_be_read(self):
        model=initialize([33,18],zero=True)
        model=with_action_feedback(model)
        self.assertEqual(model['input_size'],34)
        trace=forward(model,Arena().observe(1),return_trace=True)
        self.assertEqual(trace['inputs'][-3:],[1,1,-1])
        legacy=with_action_feedback(initialize([31,18],zero=True))
        self.assertEqual(legacy['input_size'],32)
        self.assertEqual(len(forward(legacy,[0]*31)),18)
        self.assertEqual(OBSERVATION_NAMES[-2:],['self.cube_available','opponent.cube_available'])
