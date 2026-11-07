import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from weight_space.__main__ import main
from weight_space.bundle import evaluate_bundle, identity, read_bundle, write_bundle
from weight_space.experiment import make_prompt, run
from weight_space.network import initialize, validate
from weight_space.providers import complete, parse_reply
from weight_space.records import record_bundle
from weight_space.worker import evaluate as legacy_worker


class SubmissionSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.marker = self.root / "source-was-executed"
        self.bundle = {
            "version": 1,
            "code": f"from pathlib import Path\nPath({str(self.marker)!r}).write_text('bad')\nclass Model: pass\n",
            "weights": {"weight": [1]},
        }

    def test_all_legacy_entry_points_reject_source_without_side_effects(self):
        directory = self.root / "submission"
        write_bundle(directory, self.bundle)
        operations = [
            lambda: evaluate_bundle(self.bundle),
            lambda: legacy_worker(directory, self.root / "result.json"),
            lambda: record_bundle(self.root / "records", self.bundle),
            lambda: parse_reply(json.dumps({"reason": "test", "model": self.bundle}), "bundle"),
            lambda: make_prompt(self.bundle, {}, 1, "bundle"),
        ]
        for operation in operations:
            with self.assertRaisesRegex(ValueError, "execution is disabled"):
                operation()
            self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / "records").exists())
        self.assertFalse((self.root / "result.json").exists())

    def test_rejected_format_never_calls_provider_or_creates_run(self):
        with patch("weight_space.experiment.complete") as provider:
            with self.assertRaisesRegex(ValueError, "execution is disabled"):
                run(self.root / "run", "test", "test", model_format="bundle")
            provider.assert_not_called()
        self.assertFalse((self.root / "run").exists())

    def test_cli_cannot_evaluate_code_and_inspection_is_inert(self):
        directory = self.root / "submission"
        write_bundle(directory, self.bundle)
        for command, expected in (("inspect", 0), ("evaluate", 2)):
            with patch.object(sys, "argv", ["weight_space", command, str(directory)]), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(), expected)
            self.assertFalse(self.marker.exists())
        self.assertEqual(identity(read_bundle(directory)), identity(self.bundle))

    def test_retired_worker_command_does_not_load_submission(self):
        directory = self.root / "submission"
        write_bundle(directory, self.bundle)
        result = subprocess.run(
            [sys.executable, "-m", "weight_space.worker", str(directory), str(self.root / "result.json")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("execution is disabled", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_dense_validator_rejects_code_fields_and_unknown_operations(self):
        model = initialize()
        model["code"] = self.bundle["code"]
        with self.assertRaises(ValueError):
            parse_reply(json.dumps({"reason": "test", "model": model}))
        del model["code"]
        model["layers"][0]["activation"] = self.bundle["code"]
        with self.assertRaises(ValueError):
            validate(model)
        self.assertFalse(self.marker.exists())

    def test_oversized_integer_is_rejected_as_invalid_data(self):
        model = initialize()
        model["layers"][0]["weights"][0][0] = 10 ** 1000
        with self.assertRaisesRegex(ValueError, "finite numbers"):
            validate(model)

    def test_default_loop_is_dense_and_rejects_code_reply(self):
        reply = json.dumps({"reason": "test", "model": self.bundle})
        with patch("weight_space.experiment.complete", return_value=(reply, {})):
            with self.assertRaises(ValueError):
                run(self.root / "run", "test", "test")
        summary = json.loads((self.root / "run" / "summary.json").read_text())
        self.assertEqual(summary["model_format"], "dense")
        self.assertEqual(summary["status"], "failed")
        self.assertFalse(self.marker.exists())

    def test_codex_call_disables_shell_tools(self):
        def fake_cli(command, **kwargs):
            self.assertIn("shell_tool", command)
            self.assertEqual(command[command.index("shell_tool") - 1], "--disable")
            self.assertNotIn("TINFOIL_API_KEY", kwargs["env"])
            Path(command[command.index("--output-last-message") + 1]).write_text("response")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("weight_space.providers.shutil.which", return_value="/test/codex"), \
             patch("weight_space.providers.subprocess.run", side_effect=fake_cli):
            text, _ = complete("codex", "gpt-6-astra", "test")
            self.assertEqual(text, "response")


if __name__ == "__main__":
    unittest.main()
