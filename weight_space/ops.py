"""Optional network operations. Architecture code can compose these operations."""

import math


def dense(values, weights, bias):
    if len(weights) != len(bias) or any(len(row) != len(values) for row in weights):
        raise ValueError("Dense layer dimensions do not match.")
    return [sum(w * x for w, x in zip(row, values)) + b for row, b in zip(weights, bias)]


def relu(values):
    return [max(0.0, x) for x in values]


def tanh(values):
    return [math.tanh(x) for x in values]


def threshold(value, cutoff=0.5):
    if not math.isfinite(value):
        raise ValueError("Network output must be finite.")
    return int(value >= cutoff)


def argmax(values):
    if not values or any(not math.isfinite(x) for x in values):
        raise ValueError("Network outputs must be finite and nonempty.")
    return max(range(len(values)), key=values.__getitem__)
