"""Restart checkpoints and immutable history, with fake agents only."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from streaming.server import ReplayStore
from weight_space.checkpoint import current_models, training_lock
from weight_space.game import match
from weight_space.network import fingerprint, load
from weight_space.tool_loop import run_tool_demo


class RestartRecoveryTests(unittest.TestCase):
    def proposal(self, provider, model, prompt, *args, **kwargs):
        return json.dumps({'note': f'{provider} private strategy', 'calls': [
            {'tool':'edit_weights','arguments':{'reason':'Distinct policy','updates':[
                {'layer':1,'row':4,'column':None,'value':2 if provider == 'codex' else 3}]}},
            {'tool':'submit','arguments':{'reason':'Use this policy'}}]}), {}

    def files(self, root):
        return {p:p.read_bytes() for p in root.rglob('*') if p.is_file() and p.name != 'demo.json'}

    def assert_files_preserved(self, files):
        for path, data in files.items():
            self.assertEqual(path.read_bytes(), data, str(path))

    def launch(self, root, **kwargs):
        return run_tool_demo(root, max_steps=3, games=2, prepare_agents=True,
                             single_reply=True, persistent_sessions=False, **kwargs)

    def gated_resume(self, root, provider, inspect_ready, *, wait_for_viewer=False):
        errors, result = [], []
        def run():
            try:
                result.append(self.launch(root, continue_run=True, wait_for_start=True,
                                          wait_for_viewer=wait_for_viewer))
            except BaseException as error:
                errors.append(error)
        with patch('weight_space.tool_loop.complete', side_effect=provider):
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            try:
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    if errors: raise errors[0]
                    status = json.loads((root/'demo.json').read_text())
                    if status['phase'] == 'ready': break
                    time.sleep(.01)
                else: self.fail('Did not reach the Start gate')
                inspect_ready(status)
            finally:
                # Release all gates even after a failed assertion.
                for name in ('start', 'viewed-1', 'viewed-2', 'viewed-3', 'viewed-4'):
                    (root/name).touch()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        return result[0]

    def test_restart_after_initial_policies_keeps_weights_context_and_waits_for_start(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'run'
            with patch('weight_space.tool_loop.complete', side_effect=self.proposal), \
                 patch('weight_space.tool_loop.match', side_effect=SystemExit('server stopped')):
                with self.assertRaises(SystemExit): self.launch(root, zero_initial=True, random_sides=True)
            old=json.loads((root/'demo.json').read_text())
            files=self.files(root)
            hashes=[fingerprint(load(p)) for p in current_models(root, old)]
            calls=[]
            def provider(provider, model, prompt, *args, **kwargs):
                calls.append((provider,prompt))
                return self.proposal(provider,model,prompt)
            def ready(status):
                self.assertEqual(calls, [])
                self.assertEqual(status['games'], [])
                self.assertEqual([fingerprint(load(p)) for p in current_models(root,status)],hashes)
            final=self.gated_resume(root, provider, ready)
            self.assertEqual(len(calls),2)  # Only after game 1; no duplicate initialization.
            for provider,prompt in calls:
                self.assertIn(provider+' private strategy',prompt)
                self.assertNotIn(('claude' if provider=='codex' else 'codex')+' private strategy',prompt)
            self.assertEqual(final['tally']['games'],2)
            self.assertEqual(final['games'][0]['player_agents'],old['next_player_agents'])
            self.assert_files_preserved(files)

    def test_restart_during_viewing_preserves_game_and_counts_it_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'run'
            with patch('weight_space.tool_loop.complete', side_effect=self.proposal), \
                 patch('weight_space.tool_loop.time.sleep', side_effect=SystemExit('server stopped')):
                with self.assertRaises(SystemExit): self.launch(root, wait_for_viewer=True)
            old=json.loads((root/'demo.json').read_text())
            self.assertEqual(old['phase'],'playing')
            self.assertEqual(old['tally']['games'],0)
            files=self.files(root)
            calls=[]
            def provider(*args, **kwargs):
                calls.append(args[2]); return self.proposal(*args, **kwargs)
            def ready(status):
                self.assertEqual(status['games'],old['games'])
                self.assertEqual(status['tally']['games'],0)
                self.assertEqual(calls,[])
            final=self.gated_resume(root,provider,ready,wait_for_viewer=True)
            self.assertEqual(final['tally']['games'],3)
            self.assertEqual(final['games'][0],old['games'][0])
            self.assertEqual(len(calls),4)
            self.assert_files_preserved(files)

    def test_interrupted_update_keeps_accepted_policy_and_all_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'run'
            def provider(provider,model,prompt,*args,**kwargs):
                if provider=='claude' and 'Review game 1' in prompt:
                    raise TimeoutError('interrupted')
                return self.proposal(provider,model,prompt)
            def game(p1,p2,directory,max_steps):
                if directory.name=='after': raise SystemExit('server stopped')
                return match(p1,p2,directory,max_steps)
            with patch('weight_space.tool_loop.complete',side_effect=provider), patch('weight_space.tool_loop.match',game):
                with self.assertRaises(SystemExit): self.launch(root)
            status=json.loads((root/'demo.json').read_text())
            status['phase']='editing'
            status['edit_rounds']=[r for r in status['edit_rounds'] if r['after_game']!=1]
            status['agents'][1]['status']='request_pending'
            (root/'demo.json').write_text(json.dumps(status))
            files=self.files(root)
            old_hashes=[fingerprint(load(p)) for p in current_models(root,status,recover=True)]
            calls=[]
            def resumed(provider,model,prompt,*args,**kwargs):
                calls.append(prompt); return self.proposal(provider,model,prompt)
            final=self.gated_resume(root,resumed,lambda status:self.assertEqual(calls,[]))
            self.assertEqual(len(calls),2)  # No duplicate query for interrupted round 1.
            order=final['games'][1]['player_agents']
            for slot,agent in enumerate(order,1):
                self.assertEqual(fingerprint(load(root/'after'/f'player-{slot}.json')),old_hashes[agent-1])
            self.assertEqual(final['tally']['games'],3)
            self.assert_files_preserved(files)

    def test_partial_initialization_retries_only_missing_agent_and_retains_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'run'
            def initial(provider,model,prompt,*args,**kwargs):
                if provider=='claude': raise TimeoutError('interrupted')
                return self.proposal(provider,model,prompt)
            with patch('weight_space.tool_loop.complete',side_effect=initial):
                with self.assertRaisesRegex(ValueError,'Initial policies'):
                    self.launch(root,wait_for_start=True,zero_initial=True)
            files=self.files(root)
            calls=[]
            def provider(provider,model,prompt,*args,**kwargs):
                calls.append(provider); return self.proposal(provider,model,prompt)
            def ready(status):
                self.assertEqual(calls,['claude'])
                history=ReplayStore(root).policy_history()['agents'][1]['snapshots']
                self.assertTrue(any(s['id'].startswith('0:recovery-1:') for s in history))
                self.assertTrue(any(s['id']=='0:start' for s in history))
                selected=next(s for s in history if s['stage']=='submitted')
                self.assertEqual(fingerprint(ReplayStore(root).policy_model(1,selected['id'])),selected['architecture']['sha256'])
            final=self.gated_resume(root,provider,ready)
            self.assertEqual(final['tally']['games'],2)
            self.assert_files_preserved(files)

    def test_second_trainer_cannot_overwrite_running_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'run'
            with training_lock(root):
                with self.assertRaisesRegex(ValueError,'active trainer'):
                    self.launch(root)
            self.assertFalse(root.exists())
