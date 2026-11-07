import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from weight_space.game import match
from weight_space.lab import WeightLab
from weight_space.network import initialize, save, fingerprint
from weight_space.tool_loop import parse_calls, run_tool_demo


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        save(self.root / 'initial.json', initialize([31, 8, 18], seed=42))
        match(self.root / 'initial.json', self.root / 'initial.json', self.root / 'game', 3)
        self.lab = WeightLab(self.root / 'initial.json', self.root / 'game', self.root / 'lab', 1)

    def edit(self):
        return self.lab.dispatch('edit_weights', {'reason': 'Set an action.', 'zero_all': True,
            'updates': [{'layer': 1, 'row': 4, 'column': None, 'value': 1}]})

    def test_edit_test_submit_and_trace(self):
        self.assertIn('error', self.lab.dispatch('submit', {'reason': 'Too early.'}))
        original = self.lab.dispatch('inspect_step', {'step': 0, 'original': True})
        self.assertEqual(original['action'], original['recorded_action'])
        self.edit()
        result = self.lab.dispatch('test_inputs', {'cases': [{'inputs': [0]*31, 'expected_action': 4}]})
        self.assertFalse(result['opponent_used'])
        self.assertTrue(result['cases'][0]['matches_expected'])
        self.assertEqual(result['cases'][0]['layers'][0]['outputs'], [0]*8)
        self.edit()
        self.assertIn('error', self.lab.dispatch('submit', {'reason': 'New edit needs a test.'}))
        self.lab.dispatch('test_inputs', {'cases': [{'inputs': [0]*31, 'expected_action': 0}]})
        # A failed expectation is feedback. It does not prevent a deliberate submission.
        self.lab.dispatch('submit', {'reason': 'Keep action four.'})
        self.assertTrue(self.lab.submitted)
        with self.assertRaises(ValueError):
            self.edit()

    def test_bad_patch_is_atomic_and_no_code_or_paths(self):
        before = fingerprint(self.lab.model)
        result = self.lab.dispatch('edit_weights', {'reason': 'Invalid patch.', 'zero_all': True,
            'updates': [{'layer': 0, 'row': 0, 'column': 999, 'value': 1}]})
        self.assertIn('error', result)
        self.assertEqual(fingerprint(self.lab.model), before)
        self.assertEqual(self.lab.revision, 0)
        self.assertIn('error', self.lab.dispatch('exec', {'code': 'raise Exception()'}))
        self.assertIn('error', self.lab.dispatch('read_weights', {'path': '/etc/passwd'}))
        self.assertIn('error', self.lab.dispatch('read_steps', {'start': 0, 'count': 9}))
        self.assertIn('error', self.lab.dispatch('test_inputs', {'cases': [{'inputs': [True]*31}]}))
        with self.assertRaises(ValueError):
            self.lab.dispatch('test_inputs', {'cases': [{'inputs': [float('nan')]*31}]})

    def test_budgets(self):
        self.lab.test_cases = 64
        self.assertIn('error', self.lab.dispatch('test_inputs', {'cases': [{'inputs': [0]*31}]}))
        self.lab.revision = 12
        self.assertIn('error', self.edit())
        self.lab.calls = 40
        with self.assertRaises(ValueError):
            self.lab.dispatch('info', {})

    def test_reply_validation(self):
        for reply in ['{}', '{"note":"x","calls":[]}', '{"note":"x","calls":[{"tool":"x","arguments":{"x":NaN}}]}']:
            with self.assertRaises(ValueError):
                parse_calls(reply)

    def test_complete_loop_and_private_models(self):
        def provider(provider, model_id, prompt, timeout, max_tokens, *, quick):
            self.assertTrue(quick)
            self.assertLessEqual(timeout, 60)
            action = 4 if provider == 'codex' else 5
            calls = [
                {'tool': 'edit_weights', 'arguments': {'reason': 'Set a bias.', 'zero_all': True,
                    'updates': [{'layer': 1, 'row': action, 'column': None, 'value': 1}]}},
                {'tool': 'test_inputs', 'arguments': {'cases': [{'inputs': [0]*31, 'expected_action': action}]}},
                {'tool': 'submit', 'arguments': {'reason': 'The test passes.'}},
            ]
            return json.dumps({'note': 'Set and test one action.', 'calls': calls}), {}
        with patch('weight_space.tool_loop.complete', provider):
            result = run_tool_demo(self.root / 'demo', max_steps=3)
        self.assertEqual(result['phase'], 'complete')
        self.assertEqual([a['test_cases'] for a in result['agents']], [1, 1])
        self.assertNotEqual((self.root / 'demo/player-1.json').read_text(),
                            (self.root / 'demo/player-2.json').read_text())


if __name__ == '__main__':
    unittest.main()
