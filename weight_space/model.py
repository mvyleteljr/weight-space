"""Common storage and interface for custom network implementations."""

import json
import math
from pathlib import Path
from typing import Protocol

from .network import encode


class ModelInterface(Protocol):
    def load(self, path: Path) -> None: ...
    def act(self, observation: list[float]) -> int: ...
    def save(self, path: Path) -> None: ...
    def reset(self) -> None: ...


def validate_weights(weights):
    """Accept named, rectangular numeric arrays of any rank (including scalars)."""
    if not isinstance(weights, dict) or not weights:
        raise ValueError("Weights must be a nonempty map of names to numeric arrays.")
    count = 0

    def shape(value, depth=0):
        nonlocal count
        if depth > 16:
            raise ValueError("Weight array rank exceeds the proxy limit.")
        if isinstance(value, list):
            if not value:
                raise ValueError("Weight arrays cannot be empty.")
            shapes = [shape(item, depth + 1) for item in value]
            if any(s != shapes[0] for s in shapes):
                raise ValueError("Weight arrays must be rectangular.")
            return [len(value), *shapes[0]]
        try:
            finite = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("Weights must contain finite numbers only.")
        count += 1
        if count > 100_000:
            raise ValueError("Weights exceed the proxy parameter limit.")
        return []

    shapes = {}
    for name, value in weights.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Each parameter needs a nonempty name.")
        shapes[name] = shape(value)
    return {"parameters": count, "shapes": shapes}


class BaseModel:
    """Optional base class. Agents implement act and can override reset for memory."""

    def load(self, path):
        self.weights = json.loads(Path(path).read_text())
        validate_weights(self.weights)
        self.reset()

    def save(self, path):
        validate_weights(self.weights)
        Path(path).write_text(encode(self.weights))

    def reset(self):
        pass

    def act(self, observation):
        raise NotImplementedError
