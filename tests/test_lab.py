import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from weight_space.game import match
from weight_space.lab import WeightLab
from weight_space.network import initialize, save, fingerprint
from weight_space.tool_loop import parse_calls, run_tool_demo, run_agent
from weight_space.transcript import read_replies, reply_lines


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

    def test_reply_notes_are_published_before_next_request_and_kept_after_submit(self):
        def provider(*args, **kwargs):
            path = self.lab.directory / 'replies.json'
            if not path.exists():
                return json.dumps({'note': 'Read the first step.', 'calls': [
                    {'tool': 'read_steps', 'arguments': {'start': 0, 'count': 1}}]}), {}
            saved = read_replies(self.lab.directory)
            self.assertEqual(saved[0]['note'], 'Read the first step.')
            self.assertEqual(saved[0]['calls'][0]['result'][0]['step'], 0)
            return json.dumps({'note': 'Set and test a bias.', 'calls': [
                {'tool': 'edit_weights', 'arguments': {'reason': 'Set a bias.', 'updates': [
                    {'layer': 1, 'row': 0, 'column': None, 'value': 1}]}},
                {'tool': 'test_inputs', 'arguments': {'cases': [{'inputs': [0]*31}]}},
                {'tool': 'submit', 'arguments': {'reason': 'Keep these weights.'}}]}), {}
        with patch('weight_space.tool_loop.complete', provider):
            run_agent(self.lab, 'codex', 'test')
        saved = read_replies(self.lab.directory)
        self.assertEqual(len(saved), 2)
        self.assertIsNotNone(saved[-1]['calls'][-1]['result'])
        lines = reply_lines(saved)
        self.assertIn('Reply 1: Read the first step.', lines)
        # The viewer also reads reply notes and results from older runs.
        (self.lab.directory / 'replies.json').unlink()
        self.assertEqual(read_replies(self.lab.directory), saved)

    def test_complete_loop_and_private_models(self):
        def provider(provider, model_id, prompt, timeout, max_tokens, *, quick, output_schema):
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
            result = run_tool_demo(self.root / 'demo', max_steps=3,
                                   players=['codex:gpt-6-luna', 'tinfoil:deepseek-v4-1-flash'],
                                   reply_timeout=20, edit_seconds=35)
        self.assertEqual(result['phase'], 'complete')
        self.assertEqual([a['name'] for a in result['agents']], ['Luna', 'DeepSeek Flash'])
        self.assertEqual(result['reply_timeout'], 20)
        self.assertEqual([a['test_cases'] for a in result['agents']], [1, 1])
        self.assertNotEqual((self.root / 'demo/player-1.json').read_text(),
                            (self.root / 'demo/player-2.json').read_text())

    def test_three_games_carry_weights_and_use_latest_feedback(self):
        def agent(lab, provider, model, edit_seconds, reply_timeout):
            if lab.game_number == 2:
                self.assertEqual(lab.initial['layers'][1]['bias'][4], 1)
                self.assertIsNotNone(lab.prior_submission)
                self.assertEqual(lab.result['models'][lab.player - 1]['sha256'], fingerprint(lab.initial))
            lab.dispatch('edit_weights', {'reason': 'Increase a bias.', 'updates': [
                {'layer': 1, 'row': 4, 'column': None, 'value': lab.game_number}]})
            lab.dispatch('test_inputs', {'cases': [{'inputs': [0]*31}]})
            return lab.dispatch('submit', {'reason': 'Keep this revision.'})
        with patch('weight_space.tool_loop.run_agent', agent):
            result = run_tool_demo(self.root / 'three', max_steps=3, games=3)
        self.assertEqual([g['number'] for g in result['games']], [1, 2, 3])
        self.assertEqual([r['after_game'] for r in result['edit_rounds']], [1, 2])
        self.assertNotEqual(result['games'][1]['result']['models'], result['games'][2]['result']['models'])
        self.assertTrue((self.root / 'three/game-3/result.json').exists())

    def test_side_pairs_freeze_weights_and_map_feedback_to_each_agent(self):
        def agent(lab, provider, model, edit_seconds, reply_timeout):
            self.assertEqual(len(lab.recordings), 2)
            first, second = lab.recordings
            self.assertEqual(first['your_player'], lab.player)
            self.assertEqual(second['your_player'], 3 - lab.player)
            for recording in lab.recordings:
                side = recording['your_player']
                self.assertEqual(recording['result']['models'][side - 1]['sha256'], fingerprint(lab.initial))
                row = lab.read_steps({'start': recording['start'], 'count': 1})[0]
                self.assertEqual(row['your_player'], side)
                self.assertEqual(row['inputs'][13], side - 1)
                trace = lab.inspect_step({'step': recording['start'], 'original': True})
                self.assertEqual(trace['action'], trace['recorded_action'])
            lab.dispatch('edit_weights', {'reason': 'Set a bias.', 'updates': [
                {'layer': 1, 'row': lab.player, 'column': None, 'value': lab.game_number}]})
            lab.dispatch('test_inputs', {'cases': [{'inputs': [0]*31}]})
            return lab.dispatch('submit', {'reason': 'Use this on both sides.'})
        with patch('weight_space.tool_loop.run_agent', agent):
            result = run_tool_demo(self.root / 'paired', max_steps=3, games=6, swap_sides=True, paired_games=True)
        self.assertEqual([r['after_game'] for r in result['edit_rounds']], [2, 4])
        for first, second in zip(result['games'][::2], result['games'][1::2]):
            self.assertEqual(first['player_agents'], [1, 2])
            self.assertEqual(second['player_agents'], [2, 1])
            self.assertEqual([m['sha256'] for m in first['result']['models']],
                             [m['sha256'] for m in reversed(second['result']['models'])])
        with self.assertRaises(ValueError):
            run_tool_demo(self.root / 'bad-pair', games=7, swap_sides=True, paired_games=True)

    def test_swaps_edit_every_game_and_count_wins_by_agent(self):
        seen = []
        def agent(lab, provider, model, edit_seconds, reply_timeout):
            canonical = 1 if provider == 'codex' else 2
            side = canonical if lab.game_number % 2 else 3 - canonical
            self.assertEqual(lab.player, side)
            self.assertEqual(lab.info({})['next_player'], 3 - side)
            self.assertEqual(len(lab.recordings), 1)
            self.assertEqual(lab.read_steps({'start': 0, 'count': 1})[0]['inputs'][13], side - 1)
            self.assertEqual(lab.result['models'][side - 1]['sha256'], fingerprint(lab.initial))
            seen.append((lab.game_number, canonical))
            lab.dispatch('edit_weights', {'reason': 'Set a bias.', 'updates': [
                {'layer': 1, 'row': canonical, 'column': None, 'value': lab.game_number}]})
            lab.dispatch('test_inputs', {'cases': [{'inputs': [0]*31}]})
            return lab.dispatch('submit', {'reason': 'Use this revision.'})
        winners = iter([1, 1, None, 2])
        def recorded_match(*args):
            result = match(*args)
            result['winner'] = next(winners)
            return result
        with patch('weight_space.tool_loop.run_agent', agent), patch('weight_space.tool_loop.match', recorded_match):
            result = run_tool_demo(self.root / 'swaps', max_steps=3, games=4, swap_sides=True)
        self.assertEqual(sorted(seen), [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)])
        self.assertEqual([r['after_game'] for r in result['edit_rounds']], [1, 2, 3])
        self.assertEqual(result['tally'], {'wins': [2, 1], 'draws': 1, 'games': 4})


if __name__ == '__main__':
    unittest.main()
