import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from weight_space.network import design, architecture, forward, validate, save, load, fingerprint
from weight_space.game import DensePolicy, match
from weight_space.lab import WeightLab
from weight_space.tool_loop import run_tool_demo, prompt_for, run_agent, ReviewPending, prompt_summary
from streaming.server import ReplayStore


def memory_model():
    model = design([{'width': 1, 'type': 'recurrent', 'activation': 'linear'},
                    {'width': 18, 'type': 'dense', 'activation': 'linear'}])
    model['layers'][0]['weights'][0][0] = 1
    model['layers'][0]['recurrent'][0][0] = 1
    model['layers'][1]['weights'][1][0] = 1
    model['layers'][1]['bias'][0] = 1.5
    return model


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = memory_model()
        save(self.root / 'model.json', self.model)

    def lab(self, name='lab'):
        game = self.root / 'game'
        if not game.exists():
            match(self.root / 'model.json', self.root / 'model.json', game, 5)
        return WeightLab(self.root / 'model.json', game, self.root / name, 1)

    def test_memory_changes_action_and_is_private_and_resets(self):
        first, second = DensePolicy(self.model), DensePolicy(self.model)
        inputs = [1] + [0]*32
        self.assertEqual(first.act(inputs), 0)
        self.assertEqual(first.act(inputs), 1)
        self.assertEqual(second.act(inputs), 0)
        first.reset()
        self.assertEqual(first.act(inputs), 0)
        self.assertEqual(self.model, load(self.root / 'model.json'))
        self.assertEqual(architecture(self.model)['memory_size'], 1)

    def test_invalid_memory_architecture_and_nonfinite_state_are_rejected(self):
        for specs in ([], [{'width': 19, 'type': 'dense', 'activation': 'linear'}],
                      [{'width': 100000, 'type': 'recurrent', 'activation': 'tanh'}]):
            with self.assertRaises(ValueError): design(specs)
        bad = memory_model(); bad['layers'][0]['recurrent'] = [[1, 2]]
        with self.assertRaises(ValueError): validate(bad)
        with self.assertRaises(ValueError): forward(self.model, [0]*33, memory=[[float('nan')], []])
        with self.assertRaises(ValueError): forward(self.model, [0]*33, memory=[[], []])

    def test_recurrent_matches_are_deterministic_and_reset_between_games(self):
        a = match(self.root / 'model.json', self.root / 'model.json', self.root / 'a', 8)
        b = match(self.root / 'model.json', self.root / 'model.json', self.root / 'b', 8)
        self.assertEqual(a, b)
        self.assertEqual((self.root / 'a/steps.jsonl').read_text(), (self.root / 'b/steps.jsonl').read_text())

    def test_sequence_tests_differ_from_independent_inputs(self):
        lab = self.lab()
        cases = {'cases': [{'inputs': [1]+[0]*32}, {'inputs': [1]+[0]*32}]}
        independent = lab.dispatch('test_inputs', cases)
        sequence = lab.dispatch('test_sequence', cases)
        self.assertEqual([c['action'] for c in independent['cases']], [0, 0])
        self.assertEqual([c['action'] for c in sequence['cases']], [0, 1])
        self.assertEqual(sequence, lab.dispatch('test_sequence', cases))

    def test_inspection_reconstructs_prefix_memory(self):
        lab = self.lab()
        memory = None
        for row in lab.rows[:4]:
            trace = forward(lab.model, row['observations'][0], memory=memory, return_trace=True)
            memory = trace['memory_after']
        inspected = lab.inspect_step({'step': 3})
        self.assertEqual(inspected['outputs'], trace['outputs'])
        self.assertEqual(inspected['memory_before'], trace['memory_before'])

    def test_atomic_design_and_edit_then_test_before_submission(self):
        lab = self.lab()
        before = fingerprint(lab.model)
        error = lab.dispatch('set_architecture', {'reason': 'Bad.', 'layers': []})
        self.assertIn('error', error); self.assertEqual(fingerprint(lab.model), before)
        changed = lab.dispatch('set_architecture', {'reason': 'Use memory.', 'layers': [
            {'width': 2, 'type': 'recurrent', 'activation': 'tanh'},
            {'width': 18, 'type': 'dense', 'activation': 'linear'}]})
        self.assertTrue(changed['architecture_changed'])
        self.assertEqual(lab.model['layers'][0]['recurrent'], [[0, 0], [0, 0]])
        edited = lab.dispatch('edit_recurrent', {'reason': 'Retain state.', 'updates': [
            {'layer': 0, 'row': 0, 'column': 0, 'value': .9}]})
        self.assertEqual(edited['revision'], 2)
        self.assertIn('error', lab.dispatch('submit', {'reason': 'Too early.'}))
        lab.dispatch('test_inputs', {'cases': [{'inputs': [0]*33}, {'inputs': [0]*33}]})
        self.assertIn('error', lab.dispatch('submit', {'reason': 'Memory is not tested.'}))
        lab.dispatch('test_sequence', {'cases': [{'inputs': [0]*33}, {'inputs': [0]*33}]})
        self.assertNotIn('error', lab.dispatch('submit', {'reason': 'Ready.'}))
        self.assertEqual(load(lab.directory / 'submitted.json')['layers'][0]['recurrent'][0][0], .9)

    def test_agents_keep_independent_architectures_across_character_swaps_and_history(self):
        def agent(lab, provider, model, *args):
            recurrent = provider == 'claude'
            if lab.game_number == 1:
                lab.dispatch('set_architecture', {'reason': 'My design.', 'layers': [
                    {'width': 3 if recurrent else 2, 'type': 'recurrent' if recurrent else 'dense', 'activation': 'tanh'},
                    {'width': 18, 'type': 'dense', 'activation': 'linear'}]})
            else:
                self.assertEqual(architecture(lab.model)['memory_size'], 3 if recurrent else 0)
            lab.dispatch('edit_weights', {'reason': 'Choose action.', 'updates': [
                {'layer': 1, 'row': 1, 'column': None, 'value': lab.game_number}]})
            lab.dispatch('test_sequence', {'cases': [{'inputs': [0]*33}, {'inputs': [0]*33}]})
            result = lab.dispatch('submit', {'reason': 'Ready.'})
            events = [json.loads(x) for x in (lab.directory / 'tools.jsonl').read_text().splitlines()]
            (lab.directory / 'replies.json').write_text(json.dumps([{'turn': 1, 'note': 'My public note.',
                'calls': [{'tool': e['tool'], 'arguments': e['arguments'], 'result': e['result']} for e in events]}]))
            return result
        with patch('weight_space.tool_loop.run_agent', agent):
            status = run_tool_demo(self.root / 'run', games=3, max_steps=3, swap_sides=True)
        self.assertEqual(status['phase'], 'complete')
        last = status['games'][-1]['result']['models']
        swapped = status['games'][1]['player_agents']
        self.assertEqual(swapped, [2, 1])
        self.assertNotEqual(last[0]['sha256'], last[1]['sha256'])
        histories = ReplayStore(self.root / 'run').policy_history()['agents']
        first = histories[0]['snapshots']; second = histories[1]['snapshots']
        self.assertEqual(first[-1]['architecture']['memory_size'], 0)
        self.assertEqual(second[-1]['architecture']['memory_size'], 3)
        self.assertEqual(first[-1]['stage'], 'submitted')
        self.assertEqual(first[0]['architecture']['layers'][0]['width'], 8)
        self.assertEqual(first[1]['architecture']['layers'][0]['width'], 2)
        self.assertEqual(len({s['id'] for s in first}), len(first))
        self.assertNotIn('"weights":', json.dumps(histories))
        self.assertEqual(histories, ReplayStore(self.root / 'run').policy_history()['agents'])

    def test_failed_recurrent_edit_is_atomic_and_timeouts_keep_previous_design(self):
        lab = self.lab()
        before = fingerprint(lab.model)
        result = lab.dispatch('edit_recurrent', {'reason': 'Invalid batch.', 'updates': [
            {'layer': 0, 'row': 0, 'column': 0, 'value': .7},
            {'layer': 1, 'row': 0, 'column': 0, 'value': .8}]})
        self.assertIn('error', result)
        self.assertEqual(lab.revision, 0)
        self.assertEqual(fingerprint(lab.model), before)
        def timeout(lab, *args):
            lab.dispatch('set_architecture', {'reason': 'Candidate.', 'layers': [
                {'width': 18, 'type': 'recurrent', 'activation': 'tanh'}]})
            raise TimeoutError('Budget elapsed.')
        with patch('weight_space.tool_loop.run_agent', timeout):
            run = run_tool_demo(self.root / 'timeout', games=2, max_steps=3)
        self.assertEqual(run['games'][0]['result']['models'], run['games'][1]['result']['models'])
        self.assertEqual(run['agents'][0]['status'], 'kept_previous')

    def test_initialization_precedes_game_one_and_has_no_recordings(self):
        calls = []
        def agent(lab, *args):
            calls.append(lab.game_number)
            if lab.game_number == 0:
                self.assertEqual(lab.rows, [])
                self.assertIsNone(lab.result)
                self.assertIsNone(lab.prior_submission)
                self.assertFalse((self.root / 'prepared/before').exists())
                self.assertIn('INITIALIZATION BEFORE GAME 1', prompt_for(lab, [], 1))
                lab.dispatch('set_architecture', {'reason':'Explore.', 'layers':[
                    {'width':18,'type':'dense','activation':'linear'}]})
            else:
                lab.dispatch('edit_weights', {'reason':'Tune.', 'updates':[
                    {'layer':0,'row':0,'column':None,'value':1}]})
            lab.dispatch('test_inputs', {'cases':[{'inputs':[0]*33}]})
            return lab.dispatch('submit', {'reason':'Ready.'})
        with patch('weight_space.tool_loop.run_agent', agent):
            status=run_tool_demo(self.root / 'prepared', games=2, max_steps=3, prepare_agents=True)
        self.assertEqual(sorted(calls),[0,0,1,1])
        self.assertEqual(status['edit_rounds'][0]['after_game'],0)
        played=load(self.root / 'prepared/before/player-1.json')
        self.assertEqual(len(played['layers']),1)
        history=ReplayStore(self.root / 'prepared').policy_history()
        self.assertEqual(history['agents'][0]['snapshots'][0]['after_game'],0)

    def test_fresh_runs_do_not_inherit_previous_policy_or_context(self):
        seen = []
        def agent(lab, *args):
            info = lab.info({})
            self.assertIsNone(info['prior_submission'])
            self.assertEqual(info['context_requests'], [])
            self.assertEqual(lab.revision, 0)
            self.assertNotIn('action_feedback', lab.model)
            self.assertEqual([len(l['bias']) for l in lab.model['layers']], [8, 18])
            self.assertTrue(all('recurrent' not in l for l in lab.model['layers']))
            seen.append(fingerprint(lab.model))
            lab.dispatch('edit_weights', {'reason': 'Unique learned weight.', 'updates': [
                {'layer': 0, 'row': 0, 'column': 0, 'value': 9876}]})
            lab.dispatch('test_inputs', {'cases': [{'inputs': [0]*33}]})
            return lab.dispatch('submit', {'reason': 'Tested.'})
        with patch('weight_space.tool_loop.run_agent', agent):
            first = run_tool_demo(self.root / 'fresh-a', seed=100, games=2, max_steps=3)
            second = run_tool_demo(self.root / 'fresh-b', seed=200, games=2, max_steps=3)
        self.assertEqual(seen[:2], [first['initial_sha256']]*2)
        self.assertEqual(seen[2:], [second['initial_sha256']]*2)
        self.assertNotEqual(seen[0], seen[2])
        self.assertNotEqual(first['games'][-1]['result']['models'][0]['sha256'], seen[2])
        self.assertEqual(len(second['games']), 2)
        self.assertTrue((self.root / 'fresh-a/lab-1/submitted.json').exists())

    def test_request_stops_reply_before_later_tools(self):
        lab = self.lab()
        packet = {'note': 'Need evidence.', 'calls': [
            {'tool': 'request_context', 'arguments': {'request': 'Include collision events.',
             'reason': 'Movement stops without explanation.'}},
            {'tool': 'set_architecture', 'arguments': {'reason': 'Must not execute.', 'layers': []}}]}
        with patch('weight_space.tool_loop.complete', return_value=(json.dumps(packet), {})) as provider:
            result = run_agent(lab, 'codex', 'test')
        self.assertTrue(result['awaiting_approval'])
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(lab.calls, 1)
        self.assertEqual(lab.revision, 0)
        self.assertFalse((lab.directory / 'submitted.json').exists())

    def test_request_stops_training_and_preserves_review_artifact(self):
        def agent(lab, provider, *args):
            if provider == 'claude':
                self.assertTrue(lab.review_event.wait(2))
                raise ReviewPending()
            lab.dispatch('request_context', {'request': 'Include collision events.',
                'reason': 'Movement stops without explanation.'})
            lab.review_event.set()
            return {'awaiting_approval': True, 'requests': lab.context_requests}
        with patch('weight_space.tool_loop.run_agent', agent):
            status = run_tool_demo(self.root / 'review', games=3, max_steps=3)
        self.assertEqual(status['phase'], 'awaiting_approval')
        self.assertEqual(len(status['games']), 1)
        saved = json.loads((self.root / 'review/approval-request.json').read_text())
        self.assertFalse(saved['changes_applied'])
        self.assertEqual(saved['requests'][0]['agent'], 'Astra')
        self.assertEqual(saved['requests'][0]['requests'][0]['request'], 'Include collision events.')

    def test_context_request_is_persistent_and_does_not_change_policy(self):
        lab = self.lab()
        before = fingerprint(lab.model)
        result = lab.dispatch('request_context', {'request': 'Include collision events.',
            'reason': 'Distinguish blocked movement from a policy error.'})
        self.assertEqual(result['status'], 'awaiting_approval')
        self.assertEqual(lab.revision, 0)
        self.assertEqual(fingerprint(lab.model), before)
        saved = json.loads((lab.directory / 'context-requests.json').read_text())
        self.assertEqual(saved, lab.info({})['context_requests'])
        self.assertEqual(saved[0]['request'], 'Include collision events.')
        for _ in range(2):
            lab.dispatch('request_context', {'request': 'Add event timestamps.', 'reason': 'Compare outcomes.'})
        self.assertIn('error', lab.dispatch('request_context', {'request': 'Extra.', 'reason': 'Extra.'}))
        self.assertEqual(len(json.loads((lab.directory / 'context-requests.json').read_text())), 3)

    def test_context_index_and_perspective_match_recorded_observations(self):
        lab = self.lab()
        info = lab.info({})
        self.assertEqual(len(info['input_index']), 33)
        self.assertEqual(info['input_index'][14]['name'], 'opponent.x/width')
        summary = info['recording_summary'][0]
        self.assertEqual(sum(a['count'] for a in summary['action_counts']), len(lab.rows))
        self.assertEqual(summary['final_health_self'], lab.result['health'][0])
        self.assertEqual(summary['last_step'], len(lab.rows)-1)
        self.assertIn('POST-action', prompt_for(lab, [], 1))
        self.assertIn('Recurrence is optional', prompt_for(lab, [], 1))

    def test_observed_contact_event_indices_and_health_changes(self):
        lab = self.lab()
        # Legacy recordings have health deltas but no cumulative damage counters.
        for row in lab.rows:
            for fighter in row['state']['fighters']:
                fighter.pop('damage_dealt', None)
        lab.rows[0]['observations'][0][3] = 1
        lab.rows[0]['observations'][1][3] = 1
        lab.rows[0]['state']['fighters'][0]['health'] = 90
        lab.rows[0]['state']['fighters'][1]['health'] = 80
        event = lab.recording_summary()[0]['contact_events'][0]
        self.assertEqual(event, {'step': 0, 'health_lost_self': 10, 'health_lost_opponent': 20})
        self.assertEqual(lab.info({})['match_dimensions']['max_steps'], 5)

    def test_diagram_connections_include_all_neurons_and_actual_weights(self):
        model = memory_model()
        graph = architecture(model, include_connections=True)
        self.assertEqual(graph['layers'][0]['connections'][0], {'from':0,'to':0,'weight':1})
        self.assertEqual(graph['layers'][0]['parameters'], 35)
        self.assertEqual(graph['input_neurons'], list(range(33)))
        self.assertEqual(graph['layers'][1]['neurons'], list(range(18)))
        self.assertEqual(len(graph['layers'][0]['connections']), 33)
        self.assertEqual(len(graph['layers'][1]['connections']), 18)
        self.assertEqual(architecture(model)['layers'][0]['connections'], [])
        altered = memory_model(); altered['layers'][0]['weights'][0][0] = 2
        from weight_space.network import revision_summary
        self.assertFalse(revision_summary(model, altered)['architecture_changed'])
        self.assertEqual(revision_summary(model, altered)['changed_parameters'], 1)

    def test_compact_prompt_preserves_interface_evidence_and_policy_identity(self):
        info = self.lab().info({})
        before = json.dumps(info, sort_keys=True)
        initial = prompt_summary(info, include_interface=True)
        self.assertEqual(initial['input_index'], info['input_index'])
        self.assertEqual(initial['interface']['actions'], info['interface']['actions'])
        self.assertEqual(initial['architecture']['sha256'], info['architecture']['sha256'])
        self.assertEqual(initial['recording_summary'][0]['outcome'], info['recording_summary'][0]['outcome'])
        self.assertEqual(initial['recording_summary'][0]['contact_events'], info['recording_summary'][0]['contact_events'])
        self.assertEqual(initial['recording_summary'][0]['reason'], info['recordings'][0]['result']['reason'])
        self.assertNotIn('observation_names', initial['interface'])
        self.assertNotIn('connections', initial['architecture']['layers'][0])
        self.assertNotIn('result', initial)
        self.assertNotIn('recordings', initial)
        update = prompt_summary(info, current_only=True)
        self.assertNotIn('interface', update)
        self.assertNotIn('recording_summary', update)
        self.assertEqual(update['test_cases_left'], info['test_cases_left'])
        self.assertEqual(update['architecture'], initial['architecture'])
        self.assertEqual(json.dumps(info, sort_keys=True), before)

    def test_context_is_loaded_from_editable_markdown_each_request(self):
        context = self.root / 'agent-context.md'
        context.write_text('My goal. Reply {{REPLY_NUMBER}}. Literal {braces}. {{RUN_PHASE}}')
        lab = self.lab()
        with patch('weight_space.tool_loop.AGENT_CONTEXT_PATH', context):
            first = prompt_for(lab, [], 1)
            self.assertIn('My goal. Reply 1. Literal {braces}.', first)
            context.write_text('Updated goal. {{REPLY_NUMBER}}')
            self.assertEqual(prompt_for(lab, [], 2), 'Updated goal. 2')

    def test_prompts_offer_architecture_without_balance(self):
        prompt = prompt_for(self.lab(), [], 1)
        self.assertIn('set_architecture', prompt)
        self.assertIn('test_sequence', prompt)
        self.assertNotIn('Keep the 33 -> 8', prompt)
        self.assertNotIn('attack_balance', prompt)
        self.assertNotIn('recovery_frames', prompt)


if __name__ == '__main__': unittest.main()
