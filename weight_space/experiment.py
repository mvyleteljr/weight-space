"""The driver supplies feedback. Only the agent chooses new parameters."""

import inspect
from pathlib import Path

from . import task
from .network import encode, initialize
from .providers import complete, parse_reply
from .records import record
from .security import CODE_DISABLED


def make_prompt(model, result, round_number, model_format="dense"):
    if model_format != "dense":
        raise ValueError(CODE_DISABLED)
    return f"""You are testing direct neural network weight programming.
Use ASD-STE100 Simplified Technical English for the short reason.
Do not call tools or inspect files. All task code and feedback are below.
Do not train a network or run an automated parameter search.
Submit data only. Do not submit source code, imports, file paths, or executable objects.
Choose weights through reasoning. Return JSON only, with exactly two fields:
{{"reason": "Explain the weights briefly.", "model": <complete network object>}}
The model format is shown in the current model. Weight matrices use
[output neuron][input neuron]. A layer computes activation(weights @ input + bias).
You can change layer sizes and activations. Return numeric weights and biases.
You may keep correct weights. This is round {round_number}.

TASK
{task.DESCRIPTION}
EVALUATOR CODE
{inspect.getsource(task.evaluate)}
CURRENT MODEL
{encode(model)}
LAST FEEDBACK
{encode(result)}
"""


def run(root, provider, model_id, rounds=2, seed=0, timeout=180, max_tokens=20000,
        model_format="dense"):
    if not 1 <= rounds <= 20:
        raise ValueError("Use 1 to 20 rounds for the proxy test.")
    if timeout <= 0 or max_tokens <= 0:
        raise ValueError("Timeout and token limit must be positive.")
    if model_format != "dense":
        raise ValueError(CODE_DISABLED)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    model = initialize(seed=seed)
    baseline, feedback = record(root / "evaluations", model, "Fresh initialization.",
                                {"round": 0, "seed": seed})
    summary = {"provider": provider, "requested_model": model_id, "seed": seed,
               "model_format": model_format,
               "requested_rounds": rounds, "timeout": timeout, "max_tokens": max_tokens,
               "baseline": str(baseline), "rounds": [], "status": "running"}
    (root / "summary.json").write_text(encode(summary))
    try:
        for number in range(1, rounds + 1):
            prompt = make_prompt(model, feedback, number, model_format)
            (root / f"round-{number}-prompt.txt").write_text(prompt)
            text, metadata = complete(provider, model_id, prompt, timeout, max_tokens)
            (root / f"round-{number}-reply.txt").write_text(text)
            (root / f"round-{number}-provider.json").write_text(encode(metadata))
            reply = parse_reply(text, model_format)
            model = reply["model"]
            path, feedback = record(root / "evaluations", model, reply["reason"],
                                    {**metadata, "round": number})
            summary["rounds"].append({"round": number, "score": feedback["score"],
                                       "record": str(path)})
            (root / "summary.json").write_text(encode(summary))
        summary["status"] = "passed" if feedback["score"] == 1.0 else "not_solved"
    except Exception as error:
        summary.update(status="failed", error=str(error))
        raise
    finally:
        (root / "summary.json").write_text(encode(summary))
    return summary
