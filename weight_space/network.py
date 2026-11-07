"""A data-only dense network format. No training or executable model files."""

import hashlib
import json
import math
import random
from pathlib import Path

MAX_PARAMETERS = 100_000
ACTIVATIONS = {"linear", "relu", "tanh"}


def validate(model):
    if not isinstance(model, dict) or set(model) != {"version", "input_size", "layers"}:
        raise ValueError("Model must contain version, input_size, and layers only.")
    if type(model["version"]) is not int or model["version"] != 1:
        raise ValueError("Model version must be 1.")
    width = model["input_size"]
    if type(width) is not int or not 1 <= width <= MAX_PARAMETERS:
        raise ValueError("Invalid input size.")
    layers = model["layers"]
    if not isinstance(layers, list) or not 1 <= len(layers) <= 32:
        raise ValueError("Use 1 to 32 dense layers.")
    count = 0
    for layer in layers:
        if not isinstance(layer, dict) or set(layer) != {"weights", "bias", "activation"}:
            raise ValueError("Each layer needs weights, bias, and activation only.")
        if layer["activation"] not in ("linear", "relu", "tanh"):
            raise ValueError("Unknown activation.")
        weights, bias = layer["weights"], layer["bias"]
        if not isinstance(weights, list) or not weights or not isinstance(bias, list):
            raise ValueError("Weights must be a nonempty matrix; bias must be a list.")
        if len(weights) != len(bias):
            raise ValueError("One bias is required per output neuron.")
        count += len(weights) * (width + 1)
        if count > MAX_PARAMETERS:
            raise ValueError("Model exceeds the proxy task parameter limit.")
        for row in weights:
            if not isinstance(row, list) or len(row) != width:
                raise ValueError("Weight shape does not match the previous layer.")
        for value in [*bias, *(v for row in weights for v in row)]:
            try:
                finite = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("Weights and biases must be finite numbers.")
        width = len(bias)
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


def forward(model, inputs, *, return_trace=False):
    validate(model)
    if len(inputs) != model["input_size"] or any(
        type(x) not in (int, float) or not math.isfinite(x) for x in inputs
    ):
        raise ValueError("Input shape or values are invalid.")
    values = list(inputs)
    trace = {"inputs": list(inputs), "layers": []}
    for layer in model["layers"]:
        outputs = []
        pre_activation = []
        for row, bias in zip(layer["weights"], layer["bias"]):
            value = sum(w * x for w, x in zip(row, values)) + bias
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
        if return_trace:
            trace["layers"].append({"activation": layer["activation"],
                                     "pre_activation": pre_activation, "outputs": list(outputs)})
    if return_trace:
        return {**trace, "outputs": values}
    return values


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
