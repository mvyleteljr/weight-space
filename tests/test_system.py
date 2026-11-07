import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from weight_space.experiment import run
from weight_space.network import fingerprint, forward, initialize, load, save, validate
from weight_space.providers import complete, parse_reply
from weight_space.records import record
from weight_space.task import evaluate


def programmed_xor():
    # Direct construction: |a-b| = relu(a-b) + relu(b-a).
    model = initialize([2, 2, 1], zero=True)
    model["layers"][0]["weights"] = [[1, -1], [-1, 1]]
    model["layers"][1]["weights"] = [[1, 1]]
    return model


class NetworkTests(unittest.TestCase):
    def test_direct_weights_solve_task_without_mutation(self):
        model = programmed_xor()
        before = copy.deepcopy(model)
        result = evaluate(model)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual([c["action"] for c in result["cases"]], [0, 1, 1, 0])
        self.assertEqual(model, before)

    def test_initialization_is_repeatable(self):
        self.assertEqual(initialize(seed=9), initialize(seed=9))
        self.assertNotEqual(initialize(seed=9), initialize(seed=10))
        self.assertEqual(evaluate(initialize())["score"], 0.5)

    def test_invalid_parameters_and_shapes_are_rejected(self):
        for value in (float("nan"), float("inf"), True, "1"):
            model = programmed_xor()
            model["layers"][0]["weights"][0][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(model)
        model = programmed_xor()
        model["layers"][1]["weights"] = [[1]]
        with self.assertRaises(ValueError):
            validate(model)
        model = programmed_xor()
        model["code"] = "return 1"
        with self.assertRaises(ValueError):
            validate(model)
        with self.assertRaises(ValueError):
            initialize([100000, 100000])

    def test_output_overflow_is_rejected(self):
        model = initialize([2, 1], zero=True)
        model["layers"][0]["weights"] = [[1e308, 1e308]]
        with self.assertRaises(ValueError):
            forward(model, [1, 1])

    def test_roundtrip_and_snapshot_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            model = programmed_xor()
            file = Path(temp) / "editable.json"
            save(file, model)
            self.assertEqual(load(file), model)
            directory, result = record(Path(temp) / "records", model)
            model["layers"][1]["weights"] = [[0, 0]]
            second, _ = record(Path(temp) / "records", model)
            self.assertNotEqual(directory, second)
            self.assertEqual(fingerprint(load(directory / "model.json")), result["model_sha256"])
            self.assertEqual(evaluate(load(directory / "model.json"))["score"], 1.0)


class LoopTests(unittest.TestCase):
    def test_feedback_reaches_next_round_and_records_are_complete(self):
        replies = [initialize(zero=True), programmed_xor()]
        prompts = []

        def agent(provider, model_id, prompt, timeout, max_tokens):
            prompts.append(prompt)
            return json.dumps({"reason": "Direct test values.", "model": replies.pop(0)}), {}

        with tempfile.TemporaryDirectory() as temp, patch("weight_space.experiment.complete", agent):
            root = Path(temp) / "run"
            summary = run(root, "test", "test-model", model_format="dense")
            self.assertEqual(summary["status"], "passed")
            self.assertEqual([r["score"] for r in summary["rounds"]], [0.5, 1.0])
            feedback = json.loads(prompts[1].split("LAST FEEDBACK\n")[1])
            self.assertEqual(feedback["score"], 0.5)
            self.assertEqual(feedback["metadata"]["round"], 1)
            self.assertEqual(len(list((root / "evaluations").iterdir())), 3)
            with self.assertRaises(FileExistsError):
                run(root, "test", "test-model", model_format="dense")

    def test_invalid_reply_is_saved_and_run_fails(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "weight_space.experiment.complete", return_value=("not json", {})
        ):
            root = Path(temp) / "run"
            with self.assertRaises(ValueError):
                run(root, "test", "test-model", model_format="dense")
            self.assertEqual((root / "round-1-reply.txt").read_text(), "not json")
            self.assertEqual(json.loads((root / "summary.json").read_text())["status"], "failed")

    def test_fenced_json_and_missing_reason(self):
        reply = {"reason": "Direct values.", "model": programmed_xor()}
        self.assertEqual(parse_reply("```json\n" + json.dumps(reply) + "\n```"), reply)
        reply["reason"] = ""
        with self.assertRaises(ValueError):
            parse_reply(json.dumps(reply))

    def test_missing_tinfoil_key_fails_before_network_access(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "TINFOIL_API_KEY"):
            complete("tinfoil", "glm-5-3", "test")

    def test_tinfoil_sdk_call_and_resource_cleanup(self):
        client = MagicMock()
        client.chat.completions.create.return_value.model_dump.return_value = {
            "model": "glm-5-3", "id": "test", "usage": {"total_tokens": 10},
            "choices": [{"message": {"content": "test reply"}, "finish_reason": "stop"}],
        }
        with patch.dict(os.environ, {"TINFOIL_API_KEY": "test-key"}), patch(
            "tinfoil.TinfoilAI", autospec=True, return_value=client
        ) as constructor:
            text, metadata = complete("tinfoil", "glm-5-3", "test prompt", 30, 100)
        constructor.assert_called_once_with(api_key="test-key", timeout=30)
        self.assertEqual(text, "test reply")
        self.assertEqual(metadata["resolved_model"], "glm-5-3")
        self.assertEqual(client.client.max_retries, 0)
        client.client.close.assert_called_once()
        client.chat.completions.create.assert_called_once_with(
            model="glm-5-3", messages=[{"role": "user", "content": "test prompt"}],
            max_tokens=100, stream=False,
        )

    def test_quick_tinfoil_calls_use_supported_reasoning_levels(self):
        client = MagicMock()
        client.chat.completions.create.return_value.model_dump.return_value = {
            "choices": [{"message": {"content": "reply"}}]}
        with patch.dict(os.environ, {"TINFOIL_API_KEY": "test-key"}), patch(
            "tinfoil.TinfoilAI", return_value=client
        ):
            for model, effort in [('deepseek-v4-1-flash', 'none'), ('gemma4-31b', 'none'), ('glm-5-3', 'low')]:
                complete('tinfoil', model, 'prompt', quick=True)
                self.assertEqual(client.chat.completions.create.call_args.kwargs['reasoning_effort'], effort)


if __name__ == "__main__":
    unittest.main()
