import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from weight_space.demo import check_revision, run_demo
from weight_space.network import forward, initialize, load


class DemoTests(unittest.TestCase):
    def test_same_initial_weights_independent_edits_and_rematch(self):
        prompts = []

        def fake_provider(provider, model_id, prompt, timeout, max_tokens):
            prompts.append(prompt)
            model = json.loads(prompt.split("YOUR CURRENT MODEL\n")[1].split("SHARED GAME 1 FEEDBACK\n")[0])
            model["layers"][-1]["bias"][0] = 1
            return json.dumps({"reason": "Set one bias directly.", "model": model}), {}

        with tempfile.TemporaryDirectory() as temp, patch("weight_space.demo.complete", fake_provider):
            root = Path(temp) / "demo"
            result = run_demo(root, max_steps=3)
            self.assertEqual(result["phase"], "complete")
            self.assertEqual(load(root / "before/player-1.json"), load(root / "before/player-2.json"))
            self.assertEqual(prompts[0].split("SHARED GAME 1 FEEDBACK\n")[1],
                             prompts[1].split("SHARED GAME 1 FEEDBACK\n")[1])
            self.assertEqual([a["changed_parameters"] for a in result["agents"]], [1, 1])
            self.assertTrue((root / "after/result.json").exists())
            feedback = json.loads((root / "shared-feedback.json").read_text())
            self.assertTrue(feedback["activation_samples"])
            trace = feedback["activation_samples"][0]["networks"][0]
            self.assertEqual(trace["outputs"], forward(load(root / "initial.json"), trace["inputs"]))
            self.assertIn("pre_activation", trace["layers"][0])

    def test_relu_trace_includes_negative_pre_activation(self):
        model = initialize([2, 2, 1], zero=True)
        model["layers"][0]["weights"] = [[1, -1], [-1, 1]]
        model["layers"][1]["weights"] = [[1, 1]]
        trace = forward(model, [0, 1], return_trace=True)
        self.assertEqual(trace["layers"][0]["pre_activation"], [-1, 1])
        self.assertEqual(trace["layers"][0]["outputs"], [0, 1])
        self.assertEqual(trace["outputs"], [1])

    def test_architecture_change_is_rejected(self):
        before = initialize([31, 8, 18])
        with self.assertRaises(ValueError):
            check_revision(before, initialize([31, 4, 18]))
        after = copy.deepcopy(before)
        after["layers"][0]["activation"] = "tanh"
        with self.assertRaises(ValueError):
            check_revision(before, after)

    def test_invalid_reply_is_saved_without_starting_rematch(self):
        with tempfile.TemporaryDirectory() as temp, patch("weight_space.demo.complete", return_value=("not json", {})):
            root = Path(temp) / "demo"
            with self.assertRaises(ValueError):
                run_demo(root, max_steps=1)
            self.assertEqual(json.loads((root / "demo.json").read_text())["phase"], "failed")
            self.assertFalse((root / "after").exists())
            self.assertTrue((root / "player-1.reply.txt").exists())


if __name__ == "__main__":
    unittest.main()
