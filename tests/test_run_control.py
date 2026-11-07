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
                first = manager.start(7)
                first_status = manager.status()
                with self.assertRaises(RunBusyError):
                    manager.start(7)
                process.poll.return_value = 0
                second = manager.start(3)
            self.assertNotEqual(first, second)
            self.assertEqual(first_status['seed'], 101)
            self.assertEqual(manager.status()['seed'], 202)
            self.assertEqual(manager.status()['tally']['wins'], [0, 0])
            command = launch.call_args.args[0]
            self.assertEqual(command[:3], ['/bin/uv', 'run', '--project'])
            self.assertIn('--swap-sides', command)
            self.assertNotIn('--paired-games', command)
            self.assertEqual(command[-4:], ['--player-1', 'codex:gpt-6-astra', '--player-2', 'claude:fable'])
            self.assertTrue(launch.call_args.kwargs['start_new_session'])
            for bad in (True, '7', 0, 10, None):
                with self.assertRaises(ValueError):
                    manager.start(bad)

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
                cases = [({'games': 3}, {**headers, 'Origin': 'https://evil.example'}, 403),
                         ({'games': 3}, {**headers, 'X-Run-Token': 'bad'}, 403),
                         ({'games': 3}, {**headers, 'Host': 'evil.example'}, 403),
                         ({'games': 3, 'command': 'anything'}, headers, 400)]
                for body, request_headers, code in cases:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + '/api/runs', data=json.dumps(body).encode(), headers=request_headers))
                    self.assertEqual(error.exception.code, code); error.exception.close()
                server.run_manager.start.assert_not_called()
                with urlopen(Request(base + '/api/runs', data=b'{"games":3}', headers=headers)) as response:
                    self.assertEqual(json.load(response), {'run': 'new-run'})
                server.run_manager.start.assert_called_once_with(3)
                server.run_manager.start.side_effect = RunBusyError('A run is already active.')
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + '/api/runs', data=b'{"games":3}', headers=headers))
                self.assertEqual(error.exception.code, 409); error.exception.close()
            finally:
                server.shutdown(); server.server_close(); thread.join()
