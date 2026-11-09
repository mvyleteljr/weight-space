import tempfile
import unittest
from pathlib import Path
from weight_space.network import design, with_action_feedback, forward, save, fingerprint
from weight_space.game import DensePolicy, match
from weight_space.lab import WeightLab


class ActionFeedbackTests(unittest.TestCase):
    def model(self):
        model = with_action_feedback(design([{'width':18, 'type':'dense', 'activation':'linear'}]))
        model['layers'][0]['weights'][1][31] = -2
        model['layers'][0]['bias'][1] = 1
        return model

    def test_private_feedback_resets_and_alternates(self):
        model = self.model()
        a, b = DensePolicy(model), DensePolicy(model)
        # -1 at start selects 1, then feedback 1/17 still selects 1.
        self.assertEqual(a.act([0]*31), 1)
        self.assertEqual(a.memory[-1], [1/17])
        self.assertEqual(b.memory, None)
        a.reset()
        self.assertIsNone(a.memory)
        trace = forward(model, [0]*31, return_trace=True)
        self.assertEqual(trace['inputs'][-1], -1)
        trace2 = forward(model, [0]*31, memory=trace['memory_after'], return_trace=True)
        self.assertEqual(trace2['inputs'][-1], 1/17)
        with self.assertRaises(ValueError):
            forward(model, [0]*31, memory=[[], [float('nan')]])

    def test_enable_disable_preserves_weights_and_behavior(self):
        base = design([{'width':18,'type':'dense','activation':'linear'}])
        base['layers'][0]['weights'][2][0] = 5
        enabled = with_action_feedback(base)
        self.assertEqual(forward(base,[1]*31), forward(enabled,[1]*31))
        self.assertEqual(fingerprint(base),fingerprint(with_action_feedback(enabled,False)))
        self.assertEqual(len(base['layers'][0]['weights'][0]),31)

    def test_lab_sequence_and_prefix_and_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); save(root/'model.json',self.model())
            match(root/'model.json',root/'model.json',root/'game',3)
            lab=WeightLab(root/'model.json',root/'game',root/'lab',1)
            lab.dispatch('edit_weights',{'reason':'Use action feedback.','updates':[
                {'layer':0,'row':1,'column':31,'value':-20}]})
            cases={'cases':[{'inputs':[0]*31},{'inputs':[0]*31}]}
            separate=lab.dispatch('test_inputs',cases)
            self.assertEqual([c['action'] for c in separate['cases']],[1,1])
            self.assertIn('error',lab.dispatch('submit',{'reason':'Not sequence tested.'}))
            sequence=lab.dispatch('test_sequence',cases)
            self.assertEqual([c['action'] for c in sequence['cases']],[1,0])
            self.assertEqual(lab.inspect_step({'step':1})['inputs'][-1],1/17)
            self.assertNotIn('error',lab.dispatch('submit',{'reason':'Sequence verified.'}))
            self.assertEqual(lab.info({})['input_index'][-1]['index'],31)
