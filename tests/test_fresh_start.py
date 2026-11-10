"""Reset isolation and saved-run restoration, without provider calls or a live game server."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch

from streaming.run_control import RunManager
from streaming.server import configure_runs
from weight_space.network import design, load, save, with_action_feedback
from weight_space.tool_loop import run_agent, run_tool_demo


class FreshStartTests(unittest.TestCase):
    def assert_zero_policy(self, model):
        self.assertEqual(model['input_size'], 33)
        self.assertEqual([len(layer['bias']) for layer in model['layers']], [8, 18])
        self.assertFalse(model.get('action_feedback', False))
        for layer in model['layers']:
            self.assertNotIn('recurrent', layer)
            self.assertTrue(all(value == 0 for row in layer['weights'] for value in row))
            self.assertTrue(all(value == 0 for value in layer['bias']))

    def stale_run(self, root):
        manager = RunManager(root)
        model = with_action_feedback(design([
            {'width':4, 'type':'recurrent', 'activation':'tanh'},
            {'width':18, 'type':'dense', 'activation':'linear'},
        ]))
        model['layers'][0]['weights'][0][0] = 9876
        model['layers'][0]['recurrent'][0][0] = .75
        model['layers'][1]['bias'][0] = 4321
        save(manager.directory/'initial.json', model)
        save(manager.directory/'initial-agent-1.json', model)
        save(manager.directory/'edit-2/player-2.json', model)
        (manager.directory/'old-context.txt').write_text('OLD_GAME_SECRET_STRATEGY')
        (manager.directory/'demo.json').write_text(json.dumps({
            'phase':'complete', 'games':[{'number':1}], 'edit_rounds':[],
            'tally':{'wins':[7,5], 'games':12, 'draws':0}, 'agents':[],
        }))
        for name in ('start', 'paused', 'viewed-1'):
            (manager.directory/name).touch()
        manager.pointer.write_text(json.dumps({'run':manager.directory.name}))
        return manager

    def assert_empty_run(self, manager):
        self.assert_zero_policy(load(manager.directory/'initial.json'))
        status = manager.status()
        self.assertEqual(status['games'], [])
        self.assertEqual(status['edit_rounds'], [])
        self.assertEqual(status['tally'], {'wins':[0,0], 'games':0, 'draws':0})
        self.assertFalse(status['paused'])
        self.assertIsNone(manager.autoplay)
        self.assertFalse(manager.continuing)
        for name in ('initial-agent-1.json', 'old-context.txt', 'start', 'paused', 'viewed-1'):
            self.assertFalse((manager.directory/name).exists())

    def test_cold_training_reopens_saved_run_and_ignores_readonly_demo_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            old = self.stale_run(temp)
            saved = {p:p.read_bytes() for p in old.directory.rglob('*') if p.is_file()}
            process = Mock(); process.poll.return_value = None
            with patch.dict('os.environ', {'WEIGHT_SPACE_DEMO':'some-other-run'}), \
                 patch('streaming.run_control.shutil.which', return_value='/bin/uv'), \
                 patch('streaming.run_control.subprocess.Popen', return_value=process) as launch, \
                 patch('streaming.run_control.threading.Thread.start'):
                server = SimpleNamespace()
                configure_runs(server, temp, allow_new_runs=True, demo='unrelated-saved-demo')
            self.assertEqual(server.run_manager.directory, old.directory)
            self.assertEqual(server.replay_store.directory, old.directory)
            command = launch.call_args.args[0]
            self.assertIn('--continue-run', command)
            self.assertIn('--wait-for-start', command)
            self.assertNotIn('--zero-initial', command)
            for path, data in saved.items():
                if path.name not in ('start','paused'):
                    self.assertEqual(path.read_bytes(), data)
            server = SimpleNamespace()
            configure_runs(server, temp, demo=old.directory)
            self.assertIsNone(server.run_manager)
            self.assertEqual(server.replay_store.directory, old.directory)

    def test_first_launch_starts_fresh_and_invalid_pointer_never_silently_resets(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(RunManager, 'prepare', autospec=True) as prepare:
                manager = RunManager.reopen(temp)
                self.assert_empty_run(manager)
                prepare.assert_called_once_with(manager)
                for name in ('missing-run', '../outside'):
                    manager.pointer.write_text(json.dumps({'run':name}))
                    with self.assertRaisesRegex(ValueError, 'Saved run is unavailable'):
                        RunManager.reopen(temp)
                self.assertEqual(prepare.call_count, 1)

    def test_reset_clears_nonzero_recurrent_policy_context_and_autoplay(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = self.stale_run(temp)
            old = manager.directory
            process = Mock(pid=12345)
            process.poll.return_value = None
            process.wait.return_value = 0
            manager.process = process
            manager.continuing = True
            manager.autoplay = object()
            def prepare(fresh):
                self.assertNotEqual(fresh.directory, old)
                self.assert_empty_run(fresh)
                return fresh.directory
            with patch('streaming.run_control.os.killpg') as kill, \
                 patch.object(RunManager, 'prepare', autospec=True, side_effect=prepare):
                manager.reset()
            kill.assert_called_once_with(process.pid, 15)
            # A late old-process watcher must not overwrite the new run.
            manager._watch(process, old, {})
            self.assert_empty_run(manager)

    def test_agent_initialization_really_receives_zero_weights_and_fresh_sessions(self):
        sessions = []
        def checked_agent(lab, *args):
            if lab.game_number == 0:
                self.assert_zero_policy(lab.initial)
                self.assert_zero_policy(lab.model)
                self.assertEqual(lab.rows, [])
                self.assertIsNone(lab.prior_submission)
                self.assertIsNone(lab.result)
                self.assertIsNone(lab.restored_context)
                self.assertEqual(lab.context_requests, [])
                self.assertIsNone(lab.provider_session.session_id)
                self.assertIsNone(lab.provider_session.context_text)
                self.assertIsNone(lab.provider_session.round)
                self.assertEqual(lab.provider_session.requests, 0)
                self.assertFalse((lab.directory.parents[1]/'before').exists())
            return run_agent(lab, *args)
        def provider(provider, model, prompt, *args, session, **kwargs):
            if session.session_id is None:
                self.assertIn('INITIALIZATION BEFORE GAME 1', prompt)
                self.assertNotIn('OLD_GAME_SECRET_STRATEGY', prompt)
                self.assertNotIn('saved conversation', prompt)
                session.session_id = str(uuid.uuid4())
                sessions.append((provider, session.session_id, session.workspace.name))
            session.requests += 1
            packet = {'note':'OLD_GAME_SECRET_STRATEGY', 'calls':[
                {'tool':'set_architecture','arguments':{'reason':'Exercise reset','layers':[
                    {'width':4,'type':'recurrent','activation':'tanh'},
                    {'width':18,'type':'dense','activation':'linear'}]}},
                {'tool':'set_action_feedback','arguments':{'enabled':True,'reason':'Remember actions'}},
                {'tool':'edit_recurrent','arguments':{'reason':'Remember state','updates':[
                    {'layer':0,'row':0,'column':0,'value':.75}]}},
                {'tool':'edit_weights','arguments':{'reason':'Distinct weight','updates':[
                    {'layer':1,'row':0,'column':None,'value':9876}]}},
                {'tool':'submit','arguments':{'reason':'Use fresh proposal'}},
            ]}
            return json.dumps(packet), {}
        with tempfile.TemporaryDirectory() as temp, \
             patch('weight_space.tool_loop.run_agent', checked_agent), \
             patch('weight_space.tool_loop.complete', provider):
            for name in ('cold', 'reset'):
                root = Path(temp)/name
                result = run_tool_demo(root, max_steps=1, games=2, prepare_agents=True,
                                       zero_initial=True, single_reply=True)
                self.assertEqual(result['phase'], 'complete')
                self.assert_zero_policy(load(root/'initial.json'))
                for agent in (1,2):
                    self.assert_zero_policy(load(root/f'edit-0/lab-{agent}/revision-0.json'))
                    self.assertEqual(load(root/f'edit-0/player-{agent}.json')['layers'][-1]['bias'][0], 9876)
            self.assertEqual(len(sessions), 4)
            self.assertEqual(len({sid for _,sid,_ in sessions}), 4)
            self.assertEqual(len({path for _,_,path in sessions}), 4)

    def test_zero_initial_cannot_be_overridden_by_resume_options(self):
        with tempfile.TemporaryDirectory() as temp:
            for options in ({'resume_from':Path(temp)/'old'}, {'continue_run':True}):
                with self.assertRaisesRegex(ValueError, 'Zero initialization cannot restore'):
                    run_tool_demo(Path(temp)/'new', zero_initial=True, **options)
            self.assertFalse((Path(temp)/'new').exists())
