import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from weight_space.providers import complete
from weight_space.tool_schema import TOOL_REPLY_SCHEMA
from weight_space.tool_loop import parse_calls


class StructuredReplyTests(unittest.TestCase):
    def test_timeout_message_does_not_include_command_or_schema(self):
        with patch('weight_space.providers.shutil.which', return_value='/test/cli'), \
             patch('weight_space.providers.subprocess.run', side_effect=subprocess.TimeoutExpired(
                 ['claude', '--json-schema', 'private-command-data'], 60)):
            with self.assertRaisesRegex(TimeoutError, '^claude did not reply within 60 seconds.$'):
                complete('claude', 'test', 'prompt', timeout=60, output_schema=TOOL_REPLY_SCHEMA)

    def test_both_clis_receive_schema_and_keep_code_tools_disabled(self):
        packet = {'note': 'Read the interface.', 'calls': [{'tool': 'info', 'arguments': {}}]}

        def cli(command, **kwargs):
            if command[0] == 'codex':
                schema = json.loads(Path(command[command.index('--output-schema') + 1]).read_text())
                self.assertEqual(schema, TOOL_REPLY_SCHEMA)
                self.assertIn('shell_tool', command)
                self.assertIn('read-only', command)
                Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(packet))
                return subprocess.CompletedProcess(command, 0, '', '')
            self.assertEqual(json.loads(command[command.index('--json-schema') + 1]), TOOL_REPLY_SCHEMA)
            self.assertEqual(command[command.index('--tools') + 1], '')
            # Free text is not the structured reply and must not be used.
            return subprocess.CompletedProcess(command, 0, json.dumps({
                'result': 'Some prose.', 'structured_output': packet}), '')

        with patch('weight_space.providers.shutil.which', return_value='/test/cli'), \
             patch('weight_space.providers.subprocess.run', side_effect=cli):
            for provider in ('codex', 'claude'):
                text, _ = complete(provider, 'test', 'prompt', quick=True, output_schema=TOOL_REPLY_SCHEMA)
                self.assertEqual(parse_calls(text), packet)

    def test_missing_claude_structured_output_fails_closed(self):
        with patch('weight_space.providers.shutil.which', return_value='/test/cli'), \
             patch('weight_space.providers.subprocess.run', return_value=subprocess.CompletedProcess(
                 [], 0, json.dumps({'result': 'Unstructured text'}), '')):
            with self.assertRaisesRegex(RuntimeError, 'no structured output'):
                complete('claude', 'test', 'prompt', output_schema=TOOL_REPLY_SCHEMA)
