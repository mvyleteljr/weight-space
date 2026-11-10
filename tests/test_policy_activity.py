import copy
import unittest

from streaming.policy_activity import recorded_activity
from weight_space.network import design, with_action_feedback, forward


class PolicyActivityTests(unittest.TestCase):
    def test_reconstructs_actual_stateful_decisions_across_unsampled_ticks(self):
        model=with_action_feedback(design([{'width':2,'type':'recurrent','activation':'relu'},
                                          {'width':18,'type':'dense','activation':'linear'}]),True)
        model['layers'][0]['weights'][0][0]=1
        model['layers'][0]['weights'][1][33]=.5
        model['layers'][0]['recurrent'][0][0]=.5
        model['layers'][1]['weights'][4][0]=2
        model['layers'][1]['weights'][3][1]=1
        original=copy.deepcopy(model)
        rows, expected, memory=[],[],[None,None]
        for step in range(6):
            observations=[[step+1]+[0]*32,[-step]+[0]*32]
            traces=[forward(model,observations[p],memory=memory[p],return_trace=True) for p in range(2)]
            memory=[trace['memory_after'] for trace in traces]
            actions=[max(range(18),key=trace['outputs'].__getitem__) for trace in traces]
            rows.append({'observations':observations,'actions':actions})
            expected.append(traces)
        saved_rows=copy.deepcopy(rows)
        result=recorded_activity([model,model],rows,stride=2)
        self.assertEqual(len(result),3)
        for i, pair in enumerate(result):
            for p, activity in enumerate(pair):
                self.assertEqual(activity['values'],[expected[i*2][p]['inputs']]+[layer['outputs'] for layer in expected[i*2][p]['layers']])
                self.assertEqual(activity['action'],rows[i*2]['actions'][p])
        self.assertEqual(result[1][0]['values'][0][-1],4/17)
        self.assertEqual(model,original)
        self.assertEqual(rows,saved_rows)
        rows[0]['actions'][0]=17
        with self.assertRaisesRegex(ValueError,'recorded action'):
            recorded_activity([model,model],rows)

    def test_default_keeps_every_alternating_decision_and_reports_actual_motion(self):
        model=design([{'width':18,'type':'dense','activation':'linear'}])
        model['layers'][0]['weights'][1][28]=-1
        model['layers'][0]['weights'][12][28]=1
        rows=[]
        for direction in (-1,1,-1,1):
            observation=[0.5]+[0]*32
            observation[28]=direction
            rows.append({'observations':[observation,observation],
                         'actions':[1 if direction<0 else 12]*2,
                         'state':{'width':1000,'fighters':[{'x':490},{'x':500}]}})
        result=recorded_activity([model,model],rows)
        self.assertEqual([pair[0]['action'] for pair in result],[1,12,1,12])
        # Requested direction and actual displacement are separate evidence.
        self.assertEqual(result[1][0]['motion'],'left')
        self.assertEqual(result[1][1]['motion'],'still')
