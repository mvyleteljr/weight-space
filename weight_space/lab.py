"""Bounded data tools for private weight editing and input-only simulations."""

import copy
import json
import math
from pathlib import Path
import time

from Street_Fighter.src.arena import ACTIONS, specification
from .demo import check_revision, publish
from .network import forward, load, save

TOOLS = {
    "info": "{} -> input names, action IDs, network shape, budgets, and game result",
    "read_steps": "{start: int, count: int=3, stride: int=1} -> recorded states, inputs and actions (max 8 steps)",
    "inspect_step": "{step: int, original: bool=false} -> own network activations and action on that recorded input",
    "read_weights": "{layer: int, row: int} -> weights and bias of one neuron",
    "edit_weights": "{reason: string, zero_all: bool=false, updates: [{layer:int,row:int,column:int|null,value:number}]} -> new private revision; null column sets bias",
    "test_inputs": "{cases:[{inputs:number[31], expected_action:int|null}]} -> action, scores, activations, expectation check (max 8 cases); no opponent or game simulation",
    "submit": "{reason:string} -> lock current revision; requires an edit and input test of that revision",
}


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}.")
    return value


def keys(arguments, allowed, required=()):
    if not isinstance(arguments, dict) or set(arguments) - set(allowed) or set(required) - set(arguments):
        raise ValueError("Unknown or missing tool arguments.")


class WeightLab:
    def __init__(self, initial, recording, directory, player):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.initial = load(initial)
        self.model = copy.deepcopy(self.initial)
        self.player = integer(player, 1, 2, "player")
        self.rows = [json.loads(line) for line in (Path(recording) / "steps.jsonl").read_text().splitlines()]
        self.result = json.loads((Path(recording) / "result.json").read_text())
        self.revision, self.calls, self.test_cases = 0, 0, 0
        self.tested_revision = None
        self.submitted = False
        save(self.directory / "revision-0.json", self.model)

    def dispatch(self, name, arguments):
        # Reject non-JSON data before any change or audit write.
        json.dumps([name, arguments], allow_nan=False)
        if self.submitted:
            raise ValueError("The model has been submitted. It is locked.")
        if self.calls >= 40:
            raise ValueError("Tool call budget exhausted.")
        self.calls += 1
        event = {"call": self.calls, "tool": name, "arguments": arguments,
                 "started_at": time.time(), "revision_before": self.revision}
        try:
            if name not in TOOLS:
                raise ValueError("Unknown tool. No code or file tools are available.")
            # Dispatch only trusted methods from a fixed table, never agent-supplied names.
            methods = {"info": self.info, "read_steps": self.read_steps,
                       "inspect_step": self.inspect_step, "read_weights": self.read_weights,
                       "edit_weights": self.edit_weights, "test_inputs": self.test_inputs,
                       "submit": self.submit}
            result = methods[name](arguments)
            event.update(ok=True, result=result)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
            result = {"error": str(error)}
            event.update(ok=False, result=result)
        event.update(revision_after=self.revision, finished_at=time.time())
        with (self.directory / "tools.jsonl").open("a") as log:
            log.write(json.dumps(event, allow_nan=False) + "\n")
        publish(self.directory / "progress.json", {
            "status": "submitted" if self.submitted else "running_tools",
            "last_tool": name, "last_tool_ok": event["ok"], "tool_calls": self.calls,
            "revision": self.revision, "test_cases": self.test_cases,
            "last_activity": time.time(),
        })
        return result

    def info(self, args):
        keys(args, [])
        return {"player": self.player, "interface": specification(),
                "layers": [{"inputs": len(layer["weights"][0]), "outputs": len(layer["bias"]),
                            "activation": layer["activation"]} for layer in self.model["layers"]],
                "recorded_steps": len(self.rows), "result": self.result,
                "revision": self.revision, "calls_left": 40 - self.calls,
                "test_cases_left": 64 - self.test_cases, "edits_left": 12 - self.revision}

    def read_steps(self, args):
        keys(args, ["start", "count", "stride"], ["start"])
        start = integer(args["start"], 0, len(self.rows) - 1, "start")
        count = integer(args.get("count", 3), 1, 8, "count")
        stride = integer(args.get("stride", 1), 1, len(self.rows), "stride")
        return [{"step": i, "inputs": self.rows[i]["observations"][self.player - 1],
                 "actions": self.rows[i]["actions"], "next_state": self.rows[i]["state"]}
                for i in range(start, min(len(self.rows), start + count * stride), stride)]

    def inspect_step(self, args):
        keys(args, ["step", "original"], ["step"])
        step = integer(args["step"], 0, len(self.rows) - 1, "step")
        original = args.get("original", False)
        if type(original) is not bool:
            raise ValueError("original must be boolean.")
        model = self.initial if original else self.model
        return {"step": step, "revision": 0 if original else self.revision,
                "recorded_action": self.rows[step]["actions"][self.player - 1],
                **self.evaluate_input(model, self.rows[step]["observations"][self.player - 1])}

    @staticmethod
    def evaluate_input(model, inputs):
        if not isinstance(inputs, list) or len(inputs) != 31 or any(
            type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 100 for x in inputs
        ):
            raise ValueError("Supply 31 finite input values with magnitude at most 100.")
        trace = forward(model, inputs, return_trace=True)
        action = max(range(18), key=trace["outputs"].__getitem__)
        return {"action": action, "controls": ACTIONS[action], **trace}

    def read_weights(self, args):
        keys(args, ["layer", "row"], ["layer", "row"])
        layer = self.model["layers"][integer(args["layer"], 0, len(self.model["layers"]) - 1, "layer")]
        row = integer(args["row"], 0, len(layer["bias"]) - 1, "row")
        return {"revision": self.revision, "weights": layer["weights"][row], "bias": layer["bias"][row]}

    def edit_weights(self, args):
        keys(args, ["reason", "zero_all", "updates"], ["reason", "updates"])
        if self.revision >= 12:
            raise ValueError("Weight edit budget exhausted.")
        self.reason(args["reason"])
        zero = args.get("zero_all", False)
        if type(zero) is not bool or not isinstance(args["updates"], list) or len(args["updates"]) > 418:
            raise ValueError("Use a boolean reset and at most 418 explicit updates.")
        candidate = copy.deepcopy(self.model)
        if zero:
            for layer in candidate["layers"]:
                layer["weights"] = [[0.0] * len(row) for row in layer["weights"]]
                layer["bias"] = [0.0] * len(layer["bias"])
        for update in args["updates"]:
            keys(update, ["layer", "row", "column", "value"], ["layer", "row", "column", "value"])
            layer = candidate["layers"][integer(update["layer"], 0, len(candidate["layers"]) - 1, "layer")]
            row = integer(update["row"], 0, len(layer["bias"]) - 1, "row")
            value = update["value"]
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
                raise ValueError("Weight values must be finite numbers with magnitude at most 1,000,000.")
            if update["column"] is None:
                layer["bias"][row] = value
            else:
                column = integer(update["column"], 0, len(layer["weights"][row]) - 1, "column")
                layer["weights"][row][column] = value
        changes = check_revision(self.initial, candidate)
        # Write only after every update passes validation. Rejected batches change nothing.
        save(self.directory / f"revision-{self.revision + 1}.json", candidate)
        self.model = candidate
        self.revision += 1
        return {"revision": self.revision, **changes}

    def test_inputs(self, args):
        keys(args, ["cases"], ["cases"])
        cases = args["cases"]
        if not isinstance(cases, list) or not 1 <= len(cases) <= 8:
            raise ValueError("Supply 1 to 8 test cases.")
        if self.test_cases + len(cases) > 64:
            raise ValueError("Input test budget exhausted.")
        results = []
        for case in cases:
            keys(case, ["inputs", "expected_action"], ["inputs"])
            expected = case.get("expected_action")
            if expected is not None:
                integer(expected, 0, 17, "expected_action")
            result = self.evaluate_input(self.model, case["inputs"])
            results.append({**result, "expected_action": expected,
                            "matches_expected": None if expected is None else result["action"] == expected})
        self.test_cases += len(cases)
        self.tested_revision = self.revision
        return {"revision": self.revision, "cases": results, "opponent_used": False}

    @staticmethod
    def reason(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
            raise ValueError("Give a short reason of 1 to 500 characters.")

    def submit(self, args):
        keys(args, ["reason"], ["reason"])
        self.reason(args["reason"])
        if self.revision == 0 or self.tested_revision != self.revision:
            raise ValueError("Edit weights, then test the current revision before submitting.")
        result = {"reason": args["reason"], "revision": self.revision,
                  "tool_calls": self.calls, "test_cases": self.test_cases,
                  **check_revision(self.initial, self.model)}
        save(self.directory / "submitted.json", self.model)
        publish(self.directory / "submission.json", result)
        self.submitted = True
        return result
