"""A data-only dense and recurrent network format. No training or executable model files."""

import copy
import hashlib
import json
import math
import random
from pathlib import Path

MAX_PARAMETERS = 100_000
ACTIVATIONS = {"linear", "relu", "tanh"}


def validate(model):
    if not isinstance(model, dict) or set(model) not in ({"version", "input_size", "layers"}, {"version", "input_size", "layers", "action_feedback"}):
        raise ValueError("Model requires version, input_size, layers, and optional action_feedback.")
    if type(model["version"]) is not int or model["version"] != 1:
        raise ValueError("Model version must be 1.")
    width = model["input_size"]
    if type(width) is not int or not 1 <= width <= MAX_PARAMETERS:
        raise ValueError("Invalid input size.")
    layers = model["layers"]
    if not isinstance(layers, list) or not 1 <= len(layers) <= 32:
        raise ValueError("Use 1 to 32 layers.")
    count = 0
    for layer in layers:
        if not isinstance(layer, dict) or set(layer) not in ({"weights", "bias", "activation"}, {"weights", "bias", "activation", "recurrent"}):
            raise ValueError("Each layer needs weights, bias, activation, and optionally recurrent weights.")
        if layer["activation"] not in ("linear", "relu", "tanh"):
            raise ValueError("Unknown activation.")
        weights, bias = layer["weights"], layer["bias"]
        if not isinstance(weights, list) or not weights or not isinstance(bias, list):
            raise ValueError("Weights must be a nonempty matrix; bias must be a list.")
        if len(weights) != len(bias):
            raise ValueError("One bias is required per output neuron.")
        recurrent = layer.get("recurrent", [])
        if "recurrent" in layer and (not isinstance(recurrent, list) or len(recurrent) != len(bias)
                or any(not isinstance(row, list) or len(row) != len(bias) for row in recurrent)):
            raise ValueError("Recurrent weights must be a square matrix of layer width.")
        count += len(weights) * (width + 1) + sum(len(row) for row in recurrent)
        if count > MAX_PARAMETERS:
            raise ValueError("Model exceeds the proxy task parameter limit.")
        for row in weights:
            if not isinstance(row, list) or len(row) != width:
                raise ValueError("Weight shape does not match the previous layer.")
        for value in [*bias, *(v for row in weights for v in row), *(v for row in recurrent for v in row)]:
            try:
                finite = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("Weights and biases must be finite numbers.")
        width = len(bias)
    if "action_feedback" in model and (model["action_feedback"] is not True or model["input_size"] not in (32, 34) or len(model["layers"][-1]["bias"]) != 18):
        raise ValueError("Action feedback requires 34 inputs (32 for legacy policies) and 18 actions.")
    return count


def initialize(sizes=(2, 4, 1), seed=0, zero=False):
    if len(sizes) < 2 or any(type(n) is not int or n < 1 for n in sizes):
        raise ValueError("Supply at least two positive layer sizes.")
    if len(sizes) > 33 or sum((a + 1) * b for a, b in zip(sizes, sizes[1:])) > MAX_PARAMETERS:
        raise ValueError("Network is too large for the proxy task.")
    rng = random.Random(seed)
    model = {"version": 1, "input_size": sizes[0], "layers": []}
    for index, (inputs, outputs) in enumerate(zip(sizes, sizes[1:])):
        model["layers"].append({
            "weights": [[0.0 if zero else rng.uniform(-0.1, 0.1)
                         for _ in range(inputs)] for _ in range(outputs)],
            "bias": [0.0] * outputs,
            "activation": "linear" if index == len(sizes) - 2 else "relu",
        })
    validate(model)
    return model


def forward(model, inputs, *, return_trace=False, memory=None, return_memory=False):
    validate(model)
    feedback = model.get("action_feedback", False)
    previous_action = -1.0
    if feedback and memory is not None:
        if not isinstance(memory, list) or len(memory) != len(model["layers"]) + 1 or not isinstance(memory[-1], list) or len(memory[-1]) != 1:
            raise ValueError("Invalid action feedback memory.")
        previous_action = memory[-1][0]
        if type(previous_action) not in (int, float) or previous_action not in [-1.0] + [i / 17 for i in range(18)]:
            raise ValueError("Invalid previous action.")
        memory = memory[:-1]
    if feedback:
        inputs = list(inputs) + [previous_action]
    if len(inputs) != model["input_size"] or any(
        type(x) not in (int, float) or not math.isfinite(x) for x in inputs
    ):
        raise ValueError("Input shape or values are invalid.")
    if memory is None:
        memory = [[0.0] * len(layer["bias"]) if "recurrent" in layer else [] for layer in model["layers"]]
    if (not isinstance(memory, list) or len(memory) != len(model["layers"])
            or any(not isinstance(state, list) or len(state) != (len(layer["bias"]) if "recurrent" in layer else 0)
                   or any(type(x) not in (int, float) or not math.isfinite(x) for x in state)
                   for state, layer in zip(memory, model["layers"]))):
        raise ValueError("Memory shape or values are invalid.")
    next_memory = []
    values = list(inputs)
    trace = {"inputs": list(inputs), "layers": []}
    for layer, previous in zip(model["layers"], memory):
        outputs = []
        pre_activation = []
        for index, (row, bias) in enumerate(zip(layer["weights"], layer["bias"])):
            value = sum(w * x for w, x in zip(row, values)) + bias
            if "recurrent" in layer:
                value += sum(w * h for w, h in zip(layer["recurrent"][index], previous))
            if not math.isfinite(value):
                raise ValueError("Network produced a non-finite value.")
            if return_trace:
                pre_activation.append(value)
            if layer["activation"] == "relu":
                value = max(0.0, value)
            elif layer["activation"] == "tanh":
                value = math.tanh(value)
            outputs.append(value)
        values = outputs
        next_memory.append(list(outputs) if "recurrent" in layer else [])
        if return_trace:
            trace["layers"].append({"activation": layer["activation"],
                                     "pre_activation": pre_activation, "outputs": list(outputs)})
    if feedback:
        next_memory.append([max(range(len(values)), key=values.__getitem__) / 17])
        memory = memory + [[previous_action]]
    if return_trace:
        return {**trace, "outputs": values, "memory_before": memory, "memory_after": next_memory}
    return (values, next_memory) if return_memory else values


def encode(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def fingerprint(model):
    validate(model)
    return hashlib.sha256(encode(model).encode()).hexdigest()


def load(path):
    path = Path(path)
    if path.stat().st_size > 8_000_000:
        raise ValueError("Model file is too large.")
    model = json.loads(path.read_text())
    validate(model)
    return model


def save(path, model):
    validate(model)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode(model))


def architecture(model, include_connections=False):
    """Bounded visualization metadata; include all neurons and weights for the viewer."""
    count = validate(model)
    def sample(n):
        return list(range(n)) if n <= 6 else [0, 1, 2, n-3, n-2, n-1]
    layers = []
    width = model["input_size"]
    for layer in model["layers"]:
        n = len(layer["bias"])
        layers.append({"width": n, "activation": layer["activation"],
            "type": "recurrent" if "recurrent" in layer else "dense",
            "inputs": width, "parameters": (width+1)*n + (n*n if "recurrent" in layer else 0),
            "neurons": list(range(n)) if include_connections else sample(n),
            **({"biases": layer["bias"]} if include_connections else {}),
            "connections": [{"from": col, "to": row, "weight": layer["weights"][row][col]}
                            for row in range(n) for col in range(width)] if include_connections else []})
        width = n
    return {"inputs": model["input_size"], "outputs": len(model["layers"][-1]["bias"]),
            "parameters": count, "sha256": fingerprint(model),
            "action_feedback": bool(model.get("action_feedback")),
            "input_neurons": list(range(model["input_size"])) if include_connections else sample(model["input_size"]),
            "memory_size": sum(len(layer["bias"]) for layer in model["layers"] if "recurrent" in layer) + int(model.get("action_feedback", False)),
            "layers": layers}


def with_action_feedback(model, enabled=True):
    validate(model)
    if type(enabled) is not bool:
        raise ValueError("enabled must be boolean.")
    candidate = copy.deepcopy(model)
    if enabled != bool(candidate.get("action_feedback")):
        if enabled:
            if candidate["input_size"] not in (31, 33) or len(candidate["layers"][-1]["bias"]) != 18:
                raise ValueError("Feedback requires a game policy.")
            candidate.update(input_size=candidate["input_size"]+1, action_feedback=True)
            for row in candidate["layers"][0]["weights"]:
                row.append(0.0)
        else:
            candidate.pop("action_feedback")
            candidate["input_size"] -= 1
            for row in candidate["layers"][0]["weights"]:
                row.pop()
    if validate(candidate) > 20_000:
        raise ValueError("At most 20,000 parameters.")
    return candidate


def design(layers):
    """Construct a bounded, zero-initialized architecture chosen by an agent."""
    if not isinstance(layers, list) or not 1 <= len(layers) <= 8:
        raise ValueError("Choose 1 to 8 layers, ending in 18 outputs.")
    width, count = 33, 0
    for layer in layers:
        if not isinstance(layer, dict) or set(layer) != {"width", "activation", "type"}:
            raise ValueError("Each layer needs width, activation, type.")
        n = layer["width"]
        if type(n) is not int or not 1 <= n <= 64 or layer["activation"] not in ACTIVATIONS or layer["type"] not in ("dense", "recurrent"):
            raise ValueError("Use widths 1–64, dense/recurrent layers, linear/relu/tanh activations.")
        count += (width + 1) * n + (n*n if layer["type"] == "recurrent" else 0)
        width = n
    if width != 18 or count > 20_000:
        raise ValueError("End in 18 outputs; at most 20,000 parameters.")
    model = initialize([33] + [layer["width"] for layer in layers], zero=True)
    for layer, spec in zip(model["layers"], layers):
        layer["activation"] = spec["activation"]
        if spec["type"] == "recurrent":
            layer["recurrent"] = [[0.0] * spec["width"] for _ in range(spec["width"])]
    validate(model)
    return model


def revision_summary(before, after):
    validate(before); total = validate(after)
    old, new = architecture(before), architecture(after)
    changed_architecture = old["inputs"] != new["inputs"] or [(l["width"], l["activation"], l["type"]) for l in old["layers"]] != [(l["width"], l["activation"], l["type"]) for l in new["layers"]]
    def numbers(model):
        return [v for layer in model["layers"] for v in
                (layer["bias"] + [x for row in layer["weights"] for x in row]
                 + [x for row in layer.get("recurrent", []) for x in row])]
    changed = total if changed_architecture else sum(a != b for a, b in zip(numbers(before), numbers(after)))
    return {"changed_parameters": changed, "total_parameters": total,
            "architecture_changed": changed_architecture, "architecture": new,
            "before_sha256": fingerprint(before), "after_sha256": fingerprint(after)}
