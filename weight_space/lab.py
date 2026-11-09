"""Bounded data tools for private weight editing and input-only simulations."""

from .network import with_action_feedback

import copy
import json
import math
from pathlib import Path
import time

from Street_Fighter.src.arena import ACTIONS, learning_specification
from .demo import publish
from .network import forward, load, save, design, architecture, revision_summary

TOOLS = {
    "set_action_feedback": "{enabled:boolean,reason:string} -> optionally add input 33: own previous selected action / 17, -1 at game start; preserves weights, new column starts zero; edit column 33 to use it; test_sequence required",
    "request_context": "{request:string,reason:string} -> send an environment/context change request to the supervising assistant; stops training for user approval; make this the final call",

    "set_architecture": "{reason:string,layers:[{width:int,type:dense|recurrent,activation:linear|relu|tanh}]} -> replace with ZERO weights; 1-8 layers, width<=64, <=20000 parameters, 33 environment inputs (+ optional action feedback)/18 outputs; one policy for BOTH characters",
    "edit_recurrent": "{reason:string,updates:[{layer:int,row:int,column:int,value:number}]} -> edit recurrent state-to-state weights",
    "test_sequence": "{cases:[{inputs:number[33],expected_action:int|null}]} -> consecutive ticks with recurrent memory; zero memory at sequence start; max 8 ticks",

    "info": "{} -> input names, action IDs, network shape, budgets, and game result",
    "read_steps": "{start: int, count: int=3, stride: int=1} -> recorded states, inputs and actions (max 8 steps)",
    "inspect_step": "{step: int, original: bool=false} -> own network activations and action on that recorded input",
    "read_weights": "{layer: int, row: int} -> weights and bias of one neuron",
    "edit_weights": "{reason: string, zero_all: bool=false, updates: [{layer:int,row:int,column:int|null,value:number}]} -> new private revision; null column sets bias",
    "test_inputs": "{cases:[{inputs:number[33], expected_action:int|null}]} -> action, scores, activations, expectation check (max 8 cases); no opponent or game simulation",
    "submit": "{reason:string} -> lock current revision; requires testing the latest revision; edits optional before game 1; stateful policies need >=2 sequence ticks",
}


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}.")
    return value


def keys(arguments, allowed, required=()):
    if not isinstance(arguments, dict) or set(arguments) - set(allowed) or set(required) - set(arguments):
        raise ValueError("Unknown or missing tool arguments.")


class WeightLab:
    def __init__(self, initial, recording, directory, player, game_number=1, prior_submission=None,
                 additional_recordings=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.initial = load(initial)
        self.model = copy.deepcopy(self.initial)
        self.player = integer(player, 1, 2, "player")
        self.game_number = game_number
        self.prior_submission = prior_submission
        self.result = json.loads((Path(recording) / "result.json").read_text()) if recording is not None else None
        self.recordings = []
        sources = [(recording, player, game_number - 1 if additional_recordings else game_number)] if recording is not None else []
        sources.extend(additional_recordings or [])
        self.rows = []
        for source, side, number in sources:
            start = len(self.rows)
            rows = [json.loads(line) for line in (Path(source) / "steps.jsonl").read_text().splitlines()]
            self.rows.extend({**row, "recorded_player": side, "recorded_game": number,
                              "game_step": i} for i, row in enumerate(rows))
            self.recordings.append({"game": number, "your_player": side, "start": start,
                                    "count": len(rows), "result": json.loads((Path(source) / "result.json").read_text())})
        self.revision, self.calls, self.test_cases = 0, 0, 0
        self.tested_revision = None
        self.sequence_tested_revision = None
        self.submitted = False
        self.context_requests = []
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
                       "submit": self.submit, "set_architecture": self.set_architecture,
                       "set_action_feedback": self.set_action_feedback, "edit_recurrent": self.edit_recurrent, "test_sequence": self.test_sequence,
                       "request_context": self.request_context}
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
        return {"player": self.player, "completed_game": self.game_number,
                "next_player": getattr(self, "next_player", self.player),
                "next_game": self.game_number + 1, "prior_submission": self.prior_submission,
                "interface": learning_specification(),
                "architecture": architecture(self.model),
                "input_index": [{"index": i, "name": name} for i, name in enumerate(learning_specification()["observation_names"] + (["self.previous_selected_action/17 (-1 at reset)"] if self.model.get("action_feedback") else []))],
                "recording_summary": self.recording_summary(),
                "context_requests": self.context_requests,
                "seconds_left": getattr(self, "seconds_left", None),
                "architecture_limits": {"layers": 8, "width": 64, "parameters": 20000},
                "layers": [{"inputs": len(layer["weights"][0]), "outputs": len(layer["bias"]),
                            "activation": layer["activation"]} for layer in self.model["layers"]],
                "recorded_steps": len(self.rows), "result": self.result,
                "match_dimensions": {k: self.rows[0]["state"][k] for k in ("width", "height", "max_steps")} if self.rows else None,
                "recordings": self.recordings,
                "revision": self.revision, "calls_left": 40 - self.calls,
                "test_cases_left": 64 - self.test_cases, "edits_left": 12 - self.revision}

    def request_context(self, args):
        keys(args, ["request", "reason"], ["request", "reason"])
        self.reason(args["request"]); self.reason(args["reason"])
        if len(self.context_requests) >= 3:
            raise ValueError("At most three context requests per editing round.")
        entry = {"id": len(self.context_requests) + 1, "request": args["request"],
                 "reason": args["reason"], "after_game": self.game_number, "status": "awaiting_approval"}
        self.context_requests.append(entry)
        publish(self.directory / "context-requests.json", self.context_requests)
        return {**entry, "message": "Training will stop for assistant review and explicit user approval. No environment change is granted."}

    def recording_summary(self):
        if hasattr(self, "_recording_summary"):
            return self._recording_summary
        summaries = []
        for recording in self.recordings:
            rows = self.rows[recording["start"]:recording["start"] + recording["count"]]
            side = recording["your_player"] - 1
            events, healing, counts = [], [], [0] * 18
            for i, row in enumerate(rows):
                counts[row["actions"][side]] += 1
                before = [row["observations"][0][3] * 100, row["observations"][1][3] * 100]
                loss = [round(before[j] - row["state"]["fighters"][j]["health"], 6) for j in range(2)]
                if any(v > 0 for v in loss):
                    events.append({"step": recording["start"] + i, "health_lost_self": max(0,loss[side]),
                                   "health_lost_opponent": max(0,loss[1-side])})
                if row.get("powerups_collected"):
                    healing.append({"step": recording["start"]+i, "players": row["powerups_collected"]})
            result = recording["result"]
            summaries.append({"game": recording["game"], "your_player": side + 1,
                "outcome": "draw" if result["winner"] is None else "win" if result["winner"] == side + 1 else "loss",
                "final_health_self": result["health"][side], "final_health_opponent": result["health"][1-side],
                "action_counts": [{"id": i, "count": n} for i,n in enumerate(counts) if n],
                "powerup_collections": healing, "contact_event_count": len(events), "contact_events": events[:6] + events[-6:] if len(events)>12 else events,
                "events_truncated": len(events)>12,
                "first_step": recording["start"], "last_step": recording["start"] + len(rows)-1})
        self._recording_summary = summaries
        return summaries

    def read_steps(self, args):
        keys(args, ["start", "count", "stride"], ["start"])
        start = integer(args["start"], 0, len(self.rows) - 1, "start")
        count = integer(args.get("count", 3), 1, 8, "count")
        stride = integer(args.get("stride", 1), 1, len(self.rows), "stride")
        return [{"step": i, "game": self.rows[i]["recorded_game"], "game_step": self.rows[i]["game_step"],
                 "your_player": self.rows[i]["recorded_player"],
                 "inputs": self.rows[i]["observations"][self.rows[i]["recorded_player"] - 1],
                 "actions": self.rows[i]["actions"], "next_state": self.rows[i]["state"]}
                for i in range(start, min(len(self.rows), start + count * stride), stride)]

    def inspect_step(self, args):
        keys(args, ["step", "original"], ["step"])
        step = integer(args["step"], 0, len(self.rows) - 1, "step")
        original = args.get("original", False)
        if type(original) is not bool:
            raise ValueError("original must be boolean.")
        model = self.initial if original else self.model
        memory = None
        if model.get("action_feedback") or any("recurrent" in layer for layer in model["layers"]):
            source = self.rows[step]["recorded_game"]
            for row in self.rows[:step]:
                if row["recorded_game"] == source:
                    _, memory = forward(model, row["observations"][row["recorded_player"] - 1],
                                        memory=memory, return_memory=True)
        return {"step": step, "revision": 0 if original else self.revision,
                "game": self.rows[step]["recorded_game"], "your_player": self.rows[step]["recorded_player"],
                "recorded_action": self.rows[step]["actions"][self.rows[step]["recorded_player"] - 1],
                **self.evaluate_input(model, self.rows[step]["observations"][self.rows[step]["recorded_player"] - 1], memory)}

    @staticmethod
    def evaluate_input(model, inputs, memory=None):
        if not isinstance(inputs, list) or len(inputs) != 33 or any(
            type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 100 for x in inputs
        ):
            raise ValueError("Supply 33 finite input values with magnitude at most 100.")
        trace = forward(model, inputs, return_trace=True, memory=memory)
        action = max(range(18), key=trace["outputs"].__getitem__)
        return {"action": action, "controls": ACTIONS[action], **trace}

    def read_weights(self, args):
        keys(args, ["layer", "row"], ["layer", "row"])
        layer = self.model["layers"][integer(args["layer"], 0, len(self.model["layers"]) - 1, "layer")]
        row = integer(args["row"], 0, len(layer["bias"]) - 1, "row")
        return {"revision": self.revision, "weights": layer["weights"][row], "bias": layer["bias"][row],
                "recurrent": layer["recurrent"][row] if "recurrent" in layer else None}

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
                if "recurrent" in layer:
                    layer["recurrent"] = [[0.0] * len(row) for row in layer["recurrent"]]
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
        changes = revision_summary(self.initial, candidate)
        # Write only after every update passes validation. Rejected batches change nothing.
        save(self.directory / f"revision-{self.revision + 1}.json", candidate)
        self.model = candidate
        self.revision += 1
        return {"revision": self.revision, **changes}

    def commit_candidate(self, candidate):
        if self.revision >= 12:
            raise ValueError("Edit budget exhausted.")
        changes = revision_summary(self.initial, candidate)
        save(self.directory / f"revision-{self.revision + 1}.json", candidate)
        self.model = candidate
        self.revision += 1
        return {"revision": self.revision, **changes}

    def set_action_feedback(self, args):
        keys(args, ["enabled", "reason"], ["enabled", "reason"])
        self.reason(args["reason"])
        return self.commit_candidate(with_action_feedback(self.model, args["enabled"]))

    def set_architecture(self, args):
        keys(args, ["reason", "layers"], ["reason", "layers"])
        self.reason(args["reason"])
        candidate = design(args["layers"])
        if self.model.get("action_feedback"):
            candidate = with_action_feedback(candidate)
        return self.commit_candidate(candidate)

    def edit_recurrent(self, args):
        keys(args, ["reason", "updates"], ["reason", "updates"])
        self.reason(args["reason"])
        updates = args["updates"]
        if not isinstance(updates, list) or len(updates) > 418:
            raise ValueError("Use at most 418 updates.")
        candidate = copy.deepcopy(self.model)
        for update in updates:
            keys(update, ["layer", "row", "column", "value"], ["layer", "row", "column", "value"])
            layer = candidate["layers"][integer(update["layer"], 0, len(candidate["layers"]) - 1, "layer")]
            if "recurrent" not in layer:
                raise ValueError("Select a recurrent layer.")
            row = integer(update["row"], 0, len(layer["bias"]) - 1, "row")
            column = integer(update["column"], 0, len(layer["bias"]) - 1, "column")
            value = update["value"]
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
                raise ValueError("Use finite weights with magnitude <= 1,000,000.")
            layer["recurrent"][row][column] = value
        return self.commit_candidate(candidate)

    def test_sequence(self, args):
        return self._test(args, sequential=True)

    def test_inputs(self, args):
        return self._test(args, sequential=False)

    def _test(self, args, sequential):
        keys(args, ["cases"], ["cases"])
        cases = args["cases"]
        if not isinstance(cases, list) or not 1 <= len(cases) <= 8:
            raise ValueError("Supply 1 to 8 test cases.")
        if self.test_cases + len(cases) > 64:
            raise ValueError("Input test budget exhausted.")
        results = []
        memory = None
        for case in cases:
            keys(case, ["inputs", "expected_action"], ["inputs"])
            expected = case.get("expected_action")
            if expected is not None:
                integer(expected, 0, 17, "expected_action")
            result = self.evaluate_input(self.model, case["inputs"], memory)
            if sequential:
                memory = result["memory_after"]
            results.append({**result, "expected_action": expected,
                            "matches_expected": None if expected is None else result["action"] == expected})
        self.test_cases += len(cases)
        self.tested_revision = self.revision
        if sequential and len(cases) >= 2:
            self.sequence_tested_revision = self.revision
        return {"revision": self.revision, "cases": results, "opponent_used": False, "sequential": sequential}

    @staticmethod
    def reason(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
            raise ValueError("Give a short reason of 1 to 500 characters.")

    def submit(self, args):
        keys(args, ["reason"], ["reason"])
        self.reason(args["reason"])
        if (self.revision == 0 and self.game_number != 0) or self.tested_revision != self.revision:
            raise ValueError("Edit weights, then test the current revision before submitting.")
        if (self.model.get("action_feedback") or any("recurrent" in layer for layer in self.model["layers"])) and self.sequence_tested_revision != self.revision:
            raise ValueError("Test the current stateful revision with test_sequence using at least two ticks.")
        result = {"reason": args["reason"], "revision": self.revision,
                  "context_requests": self.context_requests,
                  "tool_calls": self.calls, "test_cases": self.test_cases,
                  **revision_summary(self.initial, self.model)}
        save(self.directory / "submitted.json", self.model)
        publish(self.directory / "submission.json", result)
        self.submitted = True
        return result
