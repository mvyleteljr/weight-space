"""Connect validated dense JSON networks to the trusted fighting game."""

import copy
import json
from pathlib import Path

from Street_Fighter.src.arena import Arena, ACTIONS, OBSERVATION_NAMES, specification
from .network import encode, fingerprint, forward, load, save, validate


def validate_policy(model):
    validate(model)
    if model["input_size"] != len(OBSERVATION_NAMES) + int(model.get("action_feedback", False)) or len(model["layers"][-1]["bias"]) != len(ACTIONS):
        raise ValueError(f"Street Fighter needs {len(OBSERVATION_NAMES)} inputs and {len(ACTIONS)} outputs.")


class DensePolicy:
    def __init__(self, model):
        validate_policy(model)
        self._model = copy.deepcopy(model)
        self.sha256 = fingerprint(self._model)
        self.reset()

    def reset(self):
        self.memory = None

    def act(self, observation):
        scores, self.memory = forward(self._model, observation, memory=self.memory, return_memory=True)
        return max(range(len(scores)), key=scores.__getitem__)


def match(first, second, output, max_steps=3600):
    # Freeze both submissions before the first game step.
    models = [load(first), load(second)]
    policies = [DensePolicy(model) for model in models]
    arena = Arena(max_steps=max_steps)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for index, model in enumerate(models, 1):
        save(output / f"player-{index}.json", model)
    manifest = {"game": specification(), "max_steps": max_steps,
                "models": [{"player": i + 1, "sha256": p.sha256} for i, p in enumerate(policies)],
                "initial_state": arena.state(), "status": "running"}
    (output / "manifest.json").write_text(encode(manifest))
    try:
        for policy in policies:
            policy.reset()
        with (output / "steps.jsonl").open("w") as trace:
            while not arena.done:
                observations = arena.observations()
                actions = [policy.act(obs) for policy, obs in zip(policies, observations)]
                result = arena.step(actions)
                trace.write(json.dumps({**result, "observations": observations,
                                        "next_observations": result["observations"],
                                        "actions": actions}, allow_nan=False) + "\n")
        summary = {"status": "complete", "steps": arena.steps, "winner": arena.winner,
                   "reason": arena.reason, "health": [f.health for f in arena.fighters],
                   "models": manifest["models"]}
        (output / "result.json").write_text(encode(summary))
        manifest["status"] = "complete"
        return summary
    except Exception as error:
        manifest.update(status="failed", error=str(error))
        raise
    finally:
        (output / "manifest.json").write_text(encode(manifest))
