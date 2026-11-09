import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch

from weight_space.providers import ProviderSession, complete
from weight_space.tool_loop import run_tool_demo, session_prompt
from weight_space.lab import WeightLab
from weight_space.network import initialize, save


class SessionTests(unittest.TestCase):
    def test_codex_resumes_exact_id_without_enabling_tools(self):
        sid = str(uuid.uuid4())
        session = ProviderSession('codex', 'test')
        self.addCleanup(session.close)
        commands = []
        def cli(command, **kwargs):
            commands.append(command)
            self.assertEqual(kwargs['cwd'], session.workspace.name)
            self.assertIn('model_reasoning_effort="medium"', command)
            self.assertIn('--ignore-user-config', command)
            self.assertIn('shell_tool', command)
            self.assertIn('read-only', command)
            self.assertNotIn('--ephemeral', command)
            Path(command[command.index('--output-last-message')+1]).write_text('{}')
            return subprocess.CompletedProcess(command, 0, json.dumps({'type':'thread.started','thread_id':sid}), '')
        with patch('weight_space.providers.shutil.which', return_value='/bin/codex'), patch('weight_space.providers.subprocess.run', cli):
            complete('codex','test','initial',session=session, reasoning_effort='medium')
            _, meta=complete('codex','test','update',session=session, reasoning_effort='medium')
        self.assertNotIn('resume', commands[0])
        self.assertEqual(commands[1][-3:], ['resume',sid,'-'])
        self.assertTrue(meta['resumed'])

    def test_claude_uses_distinct_run_sessions_and_stable_workspace(self):
        a,b=ProviderSession('claude','test'),ProviderSession('claude','test')
        self.addCleanup(a.close);self.addCleanup(b.close)
        commands=[]
        def cli(command, **kwargs):
            commands.append(command)
            flag='--resume' if '--resume' in command else '--session-id'
            sid=command[command.index(flag)+1]
            self.assertEqual(command[command.index('--effort')+1], 'medium')
            self.assertIn('--safe-mode',command)
            self.assertEqual(command[command.index('--tools')+1],'')
            return subprocess.CompletedProcess(command,0,json.dumps({'session_id':sid,'result':'ok'}),'')
        with patch('weight_space.providers.shutil.which',return_value='/bin/claude'),patch('weight_space.providers.subprocess.run',cli):
            complete('claude','test','initial',session=a, reasoning_effort='medium')
            complete('claude','test','update',session=a, reasoning_effort='medium')
            complete('claude','test','fresh run',session=b, reasoning_effort='medium')
        self.assertNotEqual(a.session_id,b.session_id)
        self.assertNotEqual(a.workspace.name,b.workspace.name)
        self.assertIn('--resume',commands[1]);self.assertNotIn('--resume',commands[2])

    def test_timeout_captures_session_for_explicit_retry(self):
        s=ProviderSession('codex','test');self.addCleanup(s.close)
        sid=str(uuid.uuid4())
        error=subprocess.TimeoutExpired('codex',60,output=json.dumps({'type':'thread.started','thread_id':sid}).encode())
        with patch('weight_space.providers.shutil.which',return_value='/bin/codex'),patch('weight_space.providers.subprocess.run',side_effect=error):
            with self.assertRaises(TimeoutError):complete('codex','test','initial',session=s)
        self.assertEqual(s.session_id,sid);self.assertTrue(s.interrupted)

    def test_delta_omits_old_context_and_history_and_sends_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);save(root/'model.json',initialize([31,8,18]))
            lab=WeightLab(root/'model.json',None,root/'lab',1,0)
            session=ProviderSession('codex','test');self.addCleanup(session.close)
            context=root/'context.md';context.write_text('Original instructions {{CURRENT_SUMMARY}}')
            with patch('weight_space.tool_loop.AGENT_CONTEXT_PATH',context):
                initial,text,kind=session_prompt(lab,[],1,session)
                self.assertEqual(kind,'initial');self.assertIn('Original instructions',initial)
                session.session_id=str(uuid.uuid4());session.context_text=text;session.round=0;session.history_sent=1
                history=[{'tool_results':'OLD_RESULT'}, {'tool_results':'NEW_RESULT'}]
                update,_,kind=session_prompt(lab,history,2,session)
                self.assertNotIn('Original instructions',update);self.assertNotIn('OLD_RESULT',update)
                self.assertIn('NEW_RESULT',update);self.assertEqual(kind,'update')
                context.write_text('Changed instructions {{CURRENT_SUMMARY}}')
                changed,_,_=session_prompt(lab,history,3,session)
                self.assertIn('REVISED INSTRUCTIONS',changed);self.assertIn('Changed instructions',changed)

    def test_one_conversation_per_agent_across_rounds_and_new_ids_on_reset(self):
        sessions=[];prompts=[]
        def provider(provider,model,prompt,*args,session=None,**kwargs):
            if session.session_id is None:session.session_id=str(uuid.uuid4())
            sessions.append((provider,session.session_id));prompts.append(prompt)
            packet={'note':'Tested update.','calls':[
                {'tool':'edit_weights','arguments':{'reason':'Select action.','updates':[{'layer':1,'row':1,'column':None,'value':2}]}},
                {'tool':'test_inputs','arguments':{'cases':[{'inputs':[0]*31}]}},
                {'tool':'submit','arguments':{'reason':'Verified.'}}]}
            return json.dumps(packet),{'session_id':session.session_id}
        with tempfile.TemporaryDirectory() as folder,patch('weight_space.tool_loop.complete',provider):
            for name in ('one','two'):
                run_tool_demo(Path(folder)/name,games=2,max_steps=2,prepare_agents=True)
        for provider_name in ('codex','claude'):
            ids=[sid for provider,sid in sessions if provider==provider_name]
            self.assertEqual(ids[0],ids[1]);self.assertEqual(ids[2],ids[3]);self.assertNotEqual(ids[0],ids[2])
        self.assertEqual(sum('UPDATE ONLY' in p for p in prompts),4)
