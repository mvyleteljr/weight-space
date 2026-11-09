"""End-to-end orchestration with fake agents: no provider calls or paid inference."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from weight_space.tool_loop import run_tool_demo
from weight_space.network import load


class TrainingFlowTests(unittest.TestCase):
    def test_continue_preserves_policies_games_scores_and_agent_context(self):
        from weight_space.network import fingerprint
        from weight_space.checkpoint import current_models
        packet = {'note':'Remember my opening strategy.', 'calls':[
            {'tool':'edit_weights','arguments':{'reason':'Explore','updates':[
                {'layer':1,'row':4,'column':None,'value':2}]}},
            {'tool':'submit','arguments':{'reason':'Use these weights'}}]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'run'
            with patch('weight_space.tool_loop.complete',return_value=(json.dumps(packet),{})):
                first = run_tool_demo(root,max_steps=3,games=2,prepare_agents=True,
                                      single_reply=True,persistent_sessions=False,zero_initial=True,random_sides=True)
            original = {p: p.read_bytes() for p in root.rglob('*') if p.is_file() and p.name != 'demo.json'}
            models = [fingerprint(load(p)) for p in current_models(root, first)]
            prompts = []
            def provider(provider, model, prompt, *args, **kwargs):
                prompts.append(prompt)
                return json.dumps({'note':'Keep learning.','calls':[
                    {'tool':'submit','arguments':{'reason':'Keep current policy'}}]}), {}
            with patch('weight_space.tool_loop.complete',side_effect=provider) as calls:
                final = run_tool_demo(root,games=2,continue_run=True,single_reply=True,persistent_sessions=False)
            self.assertEqual(calls.call_count,4)  # one update per agent per new game
            self.assertEqual(final['phase'],'complete')
            self.assertEqual(len(final['games']),4)
            self.assertEqual(final['games'][:2],first['games'])
            self.assertEqual(final['tally']['games'],4)
            self.assertEqual([fingerprint(load(p)) for p in current_models(root,final)],models)
            for p, data in original.items(): self.assertEqual(p.read_bytes(),data)
            self.assertEqual(sum('saved conversation' in p for p in prompts),2)
            self.assertTrue(all('Remember my opening strategy.' in p for p in prompts[:2]))
            self.assertTrue(all('"completed_game":2' in p for p in prompts[:2]))
            self.assertNotIn('saved conversation', (root/'edit-2/lab-1/turn-1.prompt.txt').read_text())
            final['phase']='awaiting_approval'
            (root/'demo.json').write_text(json.dumps(final))
            with self.assertRaisesRegex(ValueError,'Only a completed'):
                run_tool_demo(root,continue_run=True)

    def test_one_provider_query_per_agent_for_initialization_and_each_update(self):
        packet={'note':'Try an attack in the next game.', 'calls':[
            {'tool':'edit_weights','arguments':{'reason':'Explore','updates':[
                {'layer':1,'row':4,'column':None,'value':2}]}},
            {'tool':'submit','arguments':{'reason':'Evaluate in the next game'}}]}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'run'
            with patch('weight_space.tool_loop.complete',return_value=(json.dumps(packet),{})) as provider:
                status=run_tool_demo(root,max_steps=3,games=3,prepare_agents=True,
                                     single_reply=True,persistent_sessions=False,zero_initial=True)
            self.assertEqual(status['phase'],'complete')
            self.assertEqual(len(status['games']),3)
            self.assertEqual(provider.call_count,6)  # 2 initial proposals + 2 after each of games 1 and 2
            submissions=list(root.glob('**/submission.json'))
            self.assertEqual(len(submissions),6)
            for path in submissions:
                self.assertEqual(json.loads(path.read_text())['test_cases'],0)
                self.assertEqual(len(list(path.parent.glob('turn-*.reply.txt'))),1)

    def test_zero_initialize_start_then_show_every_game_before_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'run'
            calls, errors = [], []
            def agent(lab, *args):
                calls.append(lab.game_number)
                lab.dispatch('test_inputs', {'cases':[{'inputs':[0]*33}]})
                if lab.game_number:
                    lab.dispatch('edit_weights', {'reason':'Test update', 'updates':[
                        {'layer':1,'row':0,'column':None,'value':1}]})
                    lab.dispatch('test_inputs', {'cases':[{'inputs':[0]*33}]})
                return lab.dispatch('submit', {'reason':'Ready'})
            def run():
                try:
                    run_tool_demo(root, max_steps=3, games=2, prepare_agents=True,
                                  zero_initial=True, wait_for_start=True, wait_for_viewer=True)
                except Exception as error:
                    errors.append(error)
            def wait_for(predicate):
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    if errors: raise errors[0]
                    if (root / 'demo.json').exists():
                        status = json.loads((root / 'demo.json').read_text())
                        if predicate(status): return status
                    time.sleep(.01)
                self.fail('Trainer did not reach expected state')
            with patch('weight_space.tool_loop.run_agent', agent):
                thread = threading.Thread(target=run, daemon=True); thread.start()
                try:
                    ready = wait_for(lambda s:s['phase']=='ready')
                    self.assertEqual(ready['games'], [])
                    self.assertEqual(sorted(calls), [0,0])
                    for layer in load(root / 'initial.json')['layers']:
                        self.assertTrue(all(v == 0 for row in layer['weights'] for v in row))
                        self.assertTrue(all(v == 0 for v in layer['bias']))
                    self.assertFalse((root / 'before').exists())
                    (root / 'start').touch()
                    game = wait_for(lambda s:s['phase']=='playing' and s['viewing_game']==1)
                    self.assertEqual(game['tally']['games'], 0)  # no score spoiler
                    time.sleep(.15)
                    self.assertEqual(sorted(calls),[0,0])
                    self.assertFalse((root / 'after').exists())
                    (root / 'viewed-1').touch()
                    game = wait_for(lambda s:s['phase']=='playing' and s['viewing_game']==2)
                    self.assertEqual(game['tally']['games'],1)
                    self.assertEqual(sorted(calls),[0,0,1,1])
                    (root / 'viewed-2').touch()
                    final = wait_for(lambda s:s['phase']=='complete')
                    self.assertEqual(final['tally']['games'],2)
                finally:
                    root.mkdir(exist_ok=True)
                    for marker in ('start','viewed-1','viewed-2'): (root / marker).touch()
                    thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])

    def test_initialization_timeout_does_not_enable_start_or_play(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'run'
            with patch('weight_space.tool_loop.run_agent', side_effect=TimeoutError('timeout')):
                with self.assertRaisesRegex(ValueError, 'Initial policies'):
                    run_tool_demo(root,max_steps=1,prepare_agents=True,wait_for_start=True,zero_initial=True)
            self.assertEqual(json.loads((root/'demo.json').read_text())['phase'],'failed')
            self.assertFalse((root/'before').exists())

    def test_random_assignments_match_context_saved_policies_and_scores(self):
        import random
        with tempfile.TemporaryDirectory() as folder:
            expected_rng=random.Random(0)
            expected=[[2,1] if expected_rng.getrandbits(1) else [1,2] for _ in range(6)]
            def agent(lab,*args):
                agent_id=int(lab.directory.name.rsplit('-',1)[1])
                upcoming=expected[lab.game_number].index(agent_id)+1
                self.assertEqual(lab.next_player,upcoming)
                previous=expected[max(0,lab.game_number-1)].index(agent_id)+1
                self.assertEqual(lab.player,previous)
                lab.dispatch('edit_weights',{'reason':'Identify agent','updates':[
                    {'layer':1,'row':0,'column':None,'value':agent_id}]})
                lab.dispatch('test_inputs',{'cases':[{'inputs':[0]*33}]})
                return lab.dispatch('submit',{'reason':'Ready'})
            with patch('weight_space.tool_loop.run_agent',agent):
                for name in ('first','repeat'):
                    root=Path(folder)/name
                    status=run_tool_demo(root,seed=0,max_steps=3,games=6,prepare_agents=True,random_sides=True)
                    self.assertEqual([g['player_agents'] for g in status['games']],expected)
                    self.assertEqual(expected[0],[2,1])
                    for game in status['games']:
                        for slot,agent_id in enumerate(game['player_agents'],1):
                            model=load(root/game['directory']/f'player-{slot}.json')
                            self.assertEqual(model['layers'][1]['bias'][0],agent_id)
                    self.assertEqual(status['tally']['games'],6)
