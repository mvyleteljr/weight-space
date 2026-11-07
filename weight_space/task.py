"""XOR is an interface check, not a measure of game skill."""

from .network import forward, validate

DESCRIPTION = """The task is binary XOR. Inputs are [a, b], where each value is 0 or 1.
The correct action is 1 when a and b differ, and 0 when they are equal.
Your network must have 2 inputs and 1 output. An output >= 0.5 selects action 1.
All four input pairs are tested. There is no hidden test set for this task.
Choose the dense layer sizes and activations. Set weights and biases directly.
Do not use training, gradients, optimizers, automated search, or pretrained weights.
You may use the feedback to reason about changes between rounds.
The evaluator runs the network only. It cannot execute submitted code.
This proxy supports linear, relu, and tanh activations, up to 32 layers and
100,000 parameters. These are proxy limits, not final game rules.
"""


def evaluate(model):
    count = validate(model)
    if model["input_size"] != 2 or len(model["layers"][-1]["bias"]) != 1:
        raise ValueError("XOR requires two inputs and one output.")
    cases = []
    for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
        output = forward(model, [a, b])[0]
        action, expected = int(output >= 0.5), int(a != b)
        cases.append({"state": [a, b], "output": output, "action": action,
                      "expected_action": expected, "reward": int(action == expected)})
    return {"task": "xor-v1", "score": sum(c["reward"] for c in cases) / 4,
            "parameters": count, "cases": cases}
