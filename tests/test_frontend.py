import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen, Request

from streaming.server import ReplayStore, SpectatorHandler
from weight_space.game import match
from weight_space.network import initialize, save


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        save(self.root / 'model.json', initialize([33, 8, 18]))
        result = match(self.root / 'model.json', self.root / 'model.json', self.root / 'after', 3)
        self.status = {'games': [{'number': 2, 'result': result, 'player_agents': [2, 1]}],
                       'agents': [{'name': 'Astra'}, {'name': 'Fable'}],
                       'editing_after_game': 2, 'edit_rounds': []}
        (self.root / 'demo.json').write_text(json.dumps(self.status))
        self.store = ReplayStore(self.root)

    def test_replay_uses_saved_frames_and_swapped_agent_mapping(self):
        replay = self.store.game(2)
        self.assertEqual(replay['player_agents'], [2, 1])
        self.assertEqual(replay['fps'], 60)
        self.assertEqual([f['step'] for f in replay['frames']], [1, 2, 3])
        self.assertEqual([f['health'] for f in replay['frames'][-1]['fighters']], replay['result']['health'])
        self.assertNotIn('observations', replay['frames'][0])
        with self.assertRaises(ValueError):
            self.store.game(1)

    def test_reply_updates_are_visible_without_server_restart(self):
        self.assertEqual(self.store.replies(2)['agents'][0]['replies'], [])
        lab = self.root / 'edit-2/lab-1'; lab.mkdir(parents=True)
        (lab / 'replies.json').write_text(json.dumps([{'turn': 1, 'note': 'Test a jump.', 'calls': [
            {'tool': 'test_inputs', 'arguments': {}, 'result': {'revision': 1, 'cases': [
                {'action': 4, 'expected_action': 4, 'matches_expected': True, 'inputs': [0]*33}]}}]}]))
        notes = self.store.replies(2)['agents'][0]['replies']
        self.assertEqual(notes[0]['note'], 'Test a jump.')
        self.assertTrue(notes[0]['calls'][0]['tests'][0]['matches_expected'])
        self.assertNotIn('inputs', notes[0]['calls'][0]['tests'][0])
        with self.assertRaises(ValueError):
            self.store.replies(-1)

    def test_context_requests_visible_even_without_a_finished_reply(self):
        folder = self.root / 'edit-2/lab-1'; folder.mkdir(parents=True)
        save(folder / 'revision-0.json', initialize([33, 8, 18]))
        requests = [{'after_game': 2, 'request': '<script>Need collision events</script>',
                     'reason': 'Understand blocked movement.', 'status': 'requested', 'id': 1}]
        (folder / 'context-requests.json').write_text(json.dumps(requests))
        history = self.store.policy_history()
        self.assertEqual(history['agents'][0]['context_requests'], requests)
        self.assertEqual(history['agents'][1]['context_requests'], [])

    def test_http_routes_are_read_only_and_do_not_serve_arbitrary_files(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), SpectatorHandler)
        server.replay_store, server.assets_root = self.store, self.root
        server.hls_origin = 'http://127.0.0.1:1'
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/run') as response:
                self.assertEqual(json.load(response)['demo']['games'][0]['number'], 2)
            with urlopen(base + '/api/policy-history') as response:
                self.assertEqual(len(json.load(response)['agents']), 2)
            # Timed runs can exceed nine games.
            match(self.root / 'model.json', self.root / 'model.json', self.root / 'game-10', 1)
            self.status['games'].append({'number': 10, 'result': {}, 'player_agents': [1, 2]})
            (self.root / 'demo.json').write_text(json.dumps(self.status))
            with urlopen(base + '/api/games/10') as response:
                self.assertEqual(json.load(response)['number'], 10)
            for path in ('/.env', '/api/games/../../.env', '/assets/../model.json', '/api/replies?after=999'):
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + path)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + '/api/run', data=b'{}', method='POST'))
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()
