import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from streaming.autoplay import current_models
from streaming.run_control import RunManager, RunBusyError
from weight_space.network import initialize, load, save, fingerprint


class AutoplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = RunManager(self.tmp.name)
        self.root = self.manager.directory
        self.manager.process = Mock()
        self.manager.process.poll.return_value = None
        self.models = [initialize([33, 8, 18], zero=True) for _ in range(2)]
        for i, model in enumerate(self.models, 1):
            model['layers'][-1]['bias'][1 if i == 1 else 12] = 1
            save(self.root / f'edit-0/player-{i}.json', model)
        self.status = {'phase':'playing','games':[], 'agents':[{'status':'submitted'}]*2,
                       'edit_rounds':[{'after_game':0,'agents':[{'status':'submitted'}]*2}]}
        (self.root/'demo.json').write_text(json.dumps(self.status))

    def test_requires_pause_and_freezes_weights_without_training(self):
        with self.assertRaises(RunBusyError): self.manager.autoplay_game()
        self.manager.pause(True)
        original = (self.root/'demo.json').read_bytes()
        with patch('weight_space.tool_loop.complete') as llm, patch('streaming.autoplay.secrets.randbits',side_effect=[0,1,0,1]):
            first=self.manager.autoplay_game()
            session=first['session']
            self.assertEqual(first['game']['player_agents'],[1,2])
            self.assertEqual(first['game']['activity'][0][0]['action'],1)
            self.assertEqual(first['game']['activity'][0][1]['action'],12)
            self.assertEqual(first['tally']['games'],0)
            self.assertIs(self.manager.autoplay_game(session,0),first)
            save(self.root/'edit-0/player-1.json',initialize([33,8,18],zero=True))
            second=self.manager.autoplay_game(session,1)
            self.assertEqual(second['game']['player_agents'],[2,1])
            self.assertEqual(second['game']['activity'][0][0]['action'],12)
            self.assertEqual(second['game']['activity'][0][1]['action'],1)
            self.assertEqual(second['tally']['games'],1)
            for n in (2,3): self.manager.autoplay_game(session,n)
            llm.assert_not_called()
        self.assertEqual((self.root/'demo.json').read_bytes(),original)
        self.assertEqual(len(self.manager.autoplay.store.cache),2)
        self.assertFalse((self.manager.autoplay.directory/'before').exists())
        self.assertFalse(list(self.root.glob('viewed-*')))
        for i, model in enumerate(self.models,1):
            self.assertEqual(fingerprint(load(self.manager.autoplay.directory/f'agent-{i}.json')),fingerprint(model))
        self.manager.pause(False)
        self.assertIsNone(self.manager.autoplay)
        with self.assertRaises(RunBusyError): self.manager.autoplay_game(session,4)
        self.manager.pause(True)
        with self.assertRaises(RunBusyError): self.manager.autoplay_game(session,4)

    def test_candidates_and_rejected_updates_are_not_used(self):
        save(self.root/'player-1.json',initialize([33,18],zero=True))
        status={**self.status,'editing_after_game':1,'agents':[{'status':'kept_previous'},{'status':'request_pending'}]}
        self.assertEqual(current_models(self.root,status),[self.root/f'edit-0/player-{i}.json' for i in (1,2)])
        status['agents'][0]['status']='submitted'
        self.assertEqual(current_models(self.root,status)[0],self.root/'player-1.json')

    def test_history_selections_control_both_agents_without_changing_training(self):
        from streaming.server import ReplayStore
        historic = [initialize([33,4,18],zero=True), initialize([33,8,18],zero=True)]
        for i, model in enumerate(historic,1):
            model['layers'][-1]['bias'][3 if i==1 else 8]=1
            folder=self.root/f'edit-0/lab-{i}'
            save(folder/'revision-0.json',model)
            save(folder/'revision-1.json',self.models[i-1])
            (folder/'replies.json').write_text(json.dumps([{'turn':1,'note':'New weights','calls':[
                {'tool':'edit_weights','arguments':{},'result':{'revision':1}},
                {'tool':'submit','arguments':{},'result':{'revision':1}}]}]))
        history=ReplayStore(self.root).policy_history()
        self.assertEqual(history['agents'][0]['snapshots'][0]['id'],'0:start')
        saved={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.manager.pause(True)
        with patch('weight_space.tool_loop.complete') as llm, patch('streaming.autoplay.secrets.randbits',return_value=1):
            first=self.manager.autoplay_game()
            sid=first['session']
            # Swap Astra only. The same character assignments are retained.
            a=self.manager.autoplay_game(sid,1,['0:start',None])
            self.assertEqual(a['game']['player_agents'],[2,1])
            self.assertEqual([d['action'] for d in a['game']['activity'][0]],[12,3])
            self.assertEqual(a['game']['networks'][1],history['agents'][0]['snapshots'][0]['architecture'])
            self.assertEqual(a['tally']['games'],0)
            self.assertIs(self.manager.autoplay_game(sid,1,['0:start',None]),a)
            # Independently switch Opus, then return Astra to the latest network.
            b=self.manager.autoplay_game(sid,2,['0:start','0:start'])
            self.assertEqual([d['action'] for d in b['game']['activity'][0]],[8,3])
            c=self.manager.autoplay_game(sid,3,[None,'0:start'])
            self.assertEqual([d['action'] for d in c['game']['activity'][0]],[8,1])
            self.assertEqual(c['game']['policy_selections'],[None,'0:start'])
            # Consecutive autoplay matches retain both selected policies.
            d=self.manager.autoplay_game(sid,4)
            self.assertEqual([v['action'] for v in d['game']['activity'][0]],[8,1])
            self.assertEqual(d['tally']['games'],1)
            for bad in (['../../initial.json',None],['9:start',None],[False,None],[None]):
                with self.assertRaises(ValueError): self.manager.autoplay_game(sid,5,bad)
            self.assertEqual(self.manager.autoplay.number,5)
            e=self.manager.autoplay_game(sid,5,[None,None])
            self.assertEqual([v['action'] for v in e['game']['activity'][0]],[12,1])
            llm.assert_not_called()
        for path, data in saved.items(): self.assertEqual(path.read_bytes(),data)
        self.manager.pause(False)
        with self.assertRaises(RunBusyError): self.manager.autoplay_game(sid,6,['0:start',None])

    def test_completed_run_can_autoplay_without_a_trainer(self):
        self.status['phase'] = 'complete'
        (self.root/'demo.json').write_text(json.dumps(self.status))
        self.manager.process = None
        with patch('weight_space.tool_loop.complete') as llm:
            first = self.manager.autoplay_game()
            self.assertEqual(first['game']['number'], 1)
            self.manager.autoplay_game(first['session'], 1)
            llm.assert_not_called()
        self.assertEqual(self.manager.status()['phase'], 'complete')
        for phase in ('ready', 'initializing', 'failed', 'awaiting_approval'):
            self.status['phase'] = phase
            (self.root/'demo.json').write_text(json.dumps(self.status))
            with self.assertRaises(RunBusyError): self.manager.autoplay_game()

    def test_reset_invalidates_session(self):
        self.manager.pause(True)
        first=self.manager.autoplay_game()
        with patch('streaming.run_control.os.killpg'), patch.object(self.manager,'prepare',return_value=Path('new')):
            self.manager.reset()
        self.assertIsNone(self.manager.autoplay)
        with self.assertRaises(RunBusyError): self.manager.autoplay_game(first['session'],1)

    def test_stop_keeps_training_paused_and_late_cleanup_cannot_stop_restart(self):
        self.manager.pause(True)
        with patch('weight_space.tool_loop.complete') as llm:
            first = self.manager.autoplay_game()
            self.manager.stop_autoplay(first['session'])
            self.assertIsNone(self.manager.autoplay)
            self.assertTrue(self.manager.status()['paused'])
            with self.assertRaises(RunBusyError): self.manager.autoplay_game(first['session'],1)
            second = self.manager.autoplay_game()
            self.assertNotEqual(first['session'], second['session'])
            self.manager.stop_autoplay(first['session'])
            self.assertEqual(self.manager.autoplay.id, second['session'])
            self.manager.autoplay_game(second['session'], 1)
            llm.assert_not_called()

    def test_policy_route_requires_active_session_and_local_authorization(self):
        from http.server import ThreadingHTTPServer
        from streaming.server import SpectatorHandler
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import threading
        self.manager.pause(True)
        first=self.manager.autoplay_game()
        server=ThreadingHTTPServer(('127.0.0.1',0),SpectatorHandler)
        server.run_manager=self.manager
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        headers={'Origin':base,'Content-Type':'application/json','X-Run-Token':self.manager.token}
        body={'session':first['session'],'after':1,'policies':[None,None]}
        try:
            for payload, request_headers, code in (
                (body,{**headers,'Origin':'https://example.com'},403),
                (body,{**headers,'X-Run-Token':'wrong'},403),
                ({**body,'policies':None},headers,400),
                ({**body,'policies':['../../initial.json',None]},headers,400),
                ({**body,'session':'old'},headers,409),
            ):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/autoplay-policies',data=json.dumps(payload).encode(),headers=request_headers))
                self.assertEqual(error.exception.code,code);error.exception.close()
            with urlopen(Request(base+'/api/autoplay-policies',data=json.dumps(body).encode(),headers=headers)) as response:
                self.assertEqual(json.load(response)['game']['policy_selections'],[None,None])
            for payload, request_headers, code in (
                ({'session':first['session']},{**headers,'Origin':'https://example.com'},403),
                ({'session':first['session']},{**headers,'X-Run-Token':'wrong'},403),
                ({},headers,400), ({'session':None},headers,400),
            ):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/autoplay-stop',data=json.dumps(payload).encode(),headers=request_headers))
                self.assertEqual(error.exception.code,code);error.exception.close()
            with urlopen(Request(base+'/api/autoplay-stop',data=json.dumps({'session':first['session']}).encode(),headers=headers)) as response:
                self.assertTrue(json.load(response)['ok'])
            self.assertIsNone(self.manager.autoplay)
            self.assertTrue(self.manager.status()['paused'])
            self.manager.pause(False)
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base+'/api/autoplay-policies',data=json.dumps(body).encode(),headers=headers))
            self.assertEqual(error.exception.code,409);error.exception.close()
        finally:
            server.shutdown();server.server_close();thread.join()
