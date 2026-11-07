"""Read historical code bundles as inert data. Execution is disabled."""

import ast
import hashlib
import json
from pathlib import Path

from .security import CODE_DISABLED
from .model import validate_weights
from .network import encode, initialize

TEMPLATE = '''from weight_space.model import BaseModel
from weight_space.ops import dense, relu, threshold


class Model(BaseModel):
    def act(self, observation):
        hidden = relu(dense(observation, self.weights["hidden.weight"], self.weights["hidden.bias"]))
        output = dense(hidden, self.weights["output.weight"], self.weights["output.bias"])
        return threshold(output[0])
'''


def initialize_bundle(seed=0):
    network = initialize(seed=seed)
    hidden, output = network["layers"]
    return {"version": 1, "code": TEMPLATE, "weights": {
        "hidden.weight": hidden["weights"], "hidden.bias": hidden["bias"],
        "output.weight": output["weights"], "output.bias": output["bias"],
    }}


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"version", "code", "weights"}:
        raise ValueError("Bundle must contain version, code, and weights only.")
    if type(bundle["version"]) is not int or bundle["version"] != 1:
        raise ValueError("Bundle version must be 1.")
    if not isinstance(bundle["code"], str) or len(bundle["code"].encode()) > 100_000:
        raise ValueError("Supply Python source of at most 100 KB.")
    try:
        tree = ast.parse(bundle["code"])
    except SyntaxError as error:
        raise ValueError(f"Invalid model source: {error.msg}") from None
    if not any(isinstance(node, ast.ClassDef) and node.name == "Model" for node in tree.body):
        raise ValueError("Source must define a Model class.")
    return validate_weights(bundle["weights"])


def identity(bundle):
    validate_bundle(bundle)
    return {
        "bundle_sha256": hashlib.sha256(encode(bundle).encode()).hexdigest(),
        "code_sha256": hashlib.sha256(bundle["code"].encode()).hexdigest(),
        "weights_sha256": hashlib.sha256(encode(bundle["weights"]).encode()).hexdigest(),
    }


def write_bundle(directory, bundle):
    validate_bundle(bundle)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "model.py").write_text(bundle["code"])
    (directory / "weights.json").write_text(encode(bundle["weights"]))
    (directory / "manifest.json").write_text(encode({"version": 1, **identity(bundle)}))


def read_bundle(directory):
    directory = Path(directory)
    for name in ("model.py", "weights.json"):
        if (directory / name).stat().st_size > 8_000_000:
            raise ValueError("Bundle file is too large.")
    # Recompute identity after edits. The saved manifest describes the previous save.
    bundle = {"version": 1, "code": (directory / "model.py").read_text(),
              "weights": json.loads((directory / "weights.json").read_text())}
    validate_bundle(bundle)
    return bundle


def evaluate_bundle(bundle, timeout=10):
    raise ValueError(CODE_DISABLED)
