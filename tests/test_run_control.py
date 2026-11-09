import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from streaming.run_control import RunManager, RunBusyError
from streaming.server import SpectatorHandler


class RunControlTests(unittest.TestCase):
    def test_fresh_runs_fixed_command_and_busy_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = RunManager(folder)
            process = Mock(); process.poll.return_value = None
            with patch('streaming.run_control.shutil.which', return_value='/bin/uv'), \
                 patch('streaming.run_control.subprocess.Popen', return_value=process) as launch, \
                 patch('streaming.run_control.threading.Thread.start'), \
                 patch('streaming.run_control.secrets.randbits', side_effect=[101, 202]):
                first = manager.prepare(7)
                first_status = manager.status()
                with self.assertRaises(RunBusyError):
                    manager.prepare(7)
                process.poll.return_value = 0
                second = manager.prepare(3)
            self.assertNotEqual(first, second)
            self.assertEqual(first_status['seed'], 101)
            self.assertEqual(manager.status()['seed'], 202)
            self.assertEqual(manager.status()['tally']['wins'], [0, 0])
            command = launch.call_args.args[0]
            self.assertEqual(command[:3], ['/bin/uv', 'run', '--project'])
            self.assertIn('--random-sides', command)
            self.assertNotIn('--swap-sides', command)
            for option in ('--zero-initial', '--wait-for-start', '--wait-for-viewer'):
                self.assertIn(option, command)
            self.assertEqual(command[command.index('--duration-seconds') + 1], '600')
            self.assertNotIn('--paired-games', command)
            self.assertEqual(command[-4:], ['--player-1', 'codex:gpt-6-astra', '--player-2', 'claude:claude-opus-5-5'])
            self.assertTrue(launch.call_args.kwargs['start_new_session'])
            for bad in (True, '7', 0, 10, None):
                with self.assertRaises(ValueError):
                    manager.prepare(bad)

    def test_pending_approval_blocks_new_run_after_process_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = RunManager(folder)
            (manager.directory / 'demo.json').write_text(json.dumps({'phase': 'awaiting_approval'}))
            manager.process = Mock()
            manager.process.poll.return_value = 0
            self.assertTrue(manager.active())
            with self.assertRaises(RunBusyError):
                manager.prepare(3)

    def test_start_requires_local_origin_token_and_exact_body(self):
        with tempfile.TemporaryDirectory() as folder:
            server = ThreadingHTTPServer(('127.0.0.1', 0), SpectatorHandler)
            server.run_manager = Mock(token='test-token')
            server.run_manager.start.return_value = Path(folder) / 'new-run'
            server.replay_store = None
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            headers = {'Origin': base, 'Content-Type': 'application/json', 'X-Run-Token': 'test-token'}
            try:
                cases = [({}, {**headers, 'Origin': 'https://evil.example'}, 403),
                         ({}, {**headers, 'X-Run-Token': 'bad'}, 403),
                         ({}, {**headers, 'Host': 'evil.example'}, 403),
                         ({'command': 'anything'}, headers, 400)]
                for body, request_headers, code in cases:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + '/api/runs', data=json.dumps(body).encode(), headers=request_headers))
                    self.assertEqual(error.exception.code, code); error.exception.close()
                server.run_manager.start.assert_not_called()
                with urlopen(Request(base + '/api/runs', data=b'{}', headers=headers)) as response:
                    self.assertEqual(json.load(response), {'run': 'new-run'})
                server.run_manager.start.assert_called_once_with()
                server.run_manager.start.side_effect = RunBusyError('A run is already active.')
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + '/api/runs', data=b'{}', headers=headers))
                self.assertEqual(error.exception.code, 409); error.exception.close()
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_start_gate_reset_kills_process_and_uses_new_context(self):
        from weight_space.network import load
        with tempfile.TemporaryDirectory() as folder:
            manager = RunManager(folder)
            for layer in load(manager.directory / 'initial.json')['layers']:
                self.assertTrue(all(v == 0 for row in layer['weights'] for v in row))
                self.assertTrue(all(v == 0 for v in layer['bias']))
            with self.assertRaises(RunBusyError): manager.start()
            process = Mock(pid=12345); process.poll.return_value = None
            with patch('streaming.run_control.shutil.which', return_value='/bin/uv'), \
                 patch('streaming.run_control.subprocess.Popen', return_value=process), \
                 patch('streaming.run_control.threading.Thread.start'), \
                 patch('streaming.run_control.os.killpg') as kill:
                old = manager.prepare()
                with self.assertRaises(RunBusyError): manager.start()
                old.mkdir()
                (old / 'demo.json').write_text(json.dumps({'phase':'ready', 'games':[]}))
                self.assertEqual(manager.start(), old)
                self.assertTrue((old / 'start').exists())
                new = manager.reset()
                kill.assert_called_once_with(12345, 15)
                self.assertNotEqual(old, new)
                self.assertFalse((new / 'start').exists())
                self.assertEqual(manager.status()['phase'], 'initializing')
                self.assertEqual(manager.status()['games'], [])
                self.assertEqual(manager.status()['tally']['wins'], [0,0])

    def test_finished_game_must_match_current_run_and_visible_game(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = RunManager(folder)
            path = manager.directory
            (path / 'demo.json').write_text(json.dumps({'phase':'playing', 'viewing_game':2}))
            for run, game in [('old',2), (path.name,1), (path.name,True), (path.name,3)]:
                with self.assertRaises(ValueError): manager.game_finished(run,game)
            manager.game_finished(path.name,2)
            self.assertTrue((path / 'viewed-2').exists())
            manager.game_finished(path.name,2)  # duplicate delivery is harmless

    def test_pause_and_resume_preserve_run(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = RunManager(folder)
            manager.process = Mock()
            manager.process.poll.return_value = None
            directory = manager.directory
            manager.pause(True)
            self.assertTrue(manager.status()['paused'])
            manager.pause(False)
            self.assertFalse(manager.status()['paused'])
            self.assertEqual(directory, manager.directory)
            manager.process.poll.return_value = 0
            with self.assertRaises(RunBusyError): manager.pause(True)
