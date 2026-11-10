"""Run one shared initialization, one independent edit per agent, and a rematch."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from Street_Fighter.src import arena
from .game import match, validate_policy
from .network import encode, fingerprint, forward, initialize, load, save
from .providers import complete, parse_reply

PAIRINGS = {
    "astra-opus": (("Astra", "codex", "gpt-6-astra"), ("Opus 5.5", "claude", "claude-opus-5-5")),
    "astra-fable": (("Astra", "codex", "gpt-6-astra"), ("Fable", "claude", "fable")),
    "astra-kimi": (("Astra", "codex", "gpt-6-astra"), ("Kimi K3", "tinfoil", "kimi-k3")),
}


def publish(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(encode(value))
    temporary.replace(path)


def feedback(directory):
    rows = [json.loads(line) for line in (directory / "steps.jsonl").read_text().splitlines()]
    counts = [Counter(row["actions"][i] for row in rows) for i in range(2)]
    samples = []
    activations = []
    models = [load(directory / f"player-{player}.json") for player in (1, 2)]
    for i, row in enumerate(rows):
        if i % 60 == 0 or any(row["rewards"]) or row["done"]:
            samples.append({"step": row["state"]["step"], "actions": row["actions"],
                            "fighters": row["state"]["fighters"], "rewards": row["rewards"]})
        if i % 300 == 0 or i == 60 or any(row["rewards"]) or row["done"]:
            activations.append({"step_before_action": i, "actions": row["actions"],
                                "networks": [forward(model, obs, return_trace=True)
                                             for model, obs in zip(models, row["observations"])]})
    return {"result": json.loads((directory / "result.json").read_text()),
            "action_counts": [dict(count) for count in counts], "samples": samples,
            "activation_samples": activations,
            "sampling": "States each second. Full-precision activations at start, one second, each five seconds, damage, and terminal steps. Full state trace is saved locally."}


def check_revision(before, after):
    validate_policy(after)
    if len(before["layers"]) != len(after["layers"]):
        raise ValueError("Keep the shared architecture for this demo.")
    changed = total = 0
    for old, new in zip(before["layers"], after["layers"]):
        if old["activation"] != new["activation"] or len(old["bias"]) != len(new["bias"]) \
                or len(old["weights"][0]) != len(new["weights"][0]):
            raise ValueError("Keep the shared layer sizes and activations for this demo.")
        old_values = old["bias"] + [value for row in old["weights"] for value in row]
        new_values = new["bias"] + [value for row in new["weights"] for value in row]
        changed += sum(a != b for a, b in zip(old_values, new_values))
        total += len(old_values)
    return {"changed_parameters": changed, "total_parameters": total,
            "before_sha256": fingerprint(before), "after_sha256": fingerprint(after)}


def edit_prompt(name, player, model, results):
    return f"""You are {name}, player {player}, in a neural-network weight programming experiment.
Your opponent started with exactly the same random weights. Game 1 is complete.
Use the shared feedback below to improve your own weights for game 2.
Both agents receive the same feedback, and neither sees the other's pending edits.
Return JSON only: {{"reason": "Short explanation in ASD-STE100 Simplified Technical English.",
"model": <complete dense model object with all weights and biases>}}.
Do not call tools. Do not submit or run source code. Do not train, compute gradients,
use an optimizer, or run an automated parameter search. Reason about the game and
assign weights directly. You may change every weight and bias, including setting
values to zero. For this demo, keep exactly the same layer sizes and activations:
33 inputs -> 8 ReLU neurons -> 18 linear action scores. Largest score selects an
action; first index wins a tie. Matrices use [output neuron][input neuron].
There is no recurrent memory. All actions must come from this network.
The brief reason will be shown to the user. Explain the behavior you intend.
Feedback includes each layer's pre-activation values, post-activation values,
and all 18 action scores at sampled states for both original networks.
The arena resolves both actions simultaneously. No first-player timing advantage
is intended. Player 1 is Grimes; player 2 is Shoggoth. See rules below.

INTERFACE
{encode(arena.learning_specification())}
YOUR CURRENT MODEL
{encode(model)}
SHARED GAME 1 FEEDBACK
{encode(results)}
"""


def run_demo(output, seed=42, max_steps=1800, timeout=300, pairing="astra-opus"):
    if pairing not in PAIRINGS:
        raise ValueError("Unknown agent pairing.")
    agents = PAIRINGS[pairing]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    status = {"phase": "initializing", "seed": seed, "max_steps": max_steps, "pairing": pairing,
              "request_timeout_seconds": timeout,
              "agents": [{"name": name, "player": i + 1, "provider": provider,
                          "model": model_id, "status": "waiting"}
                         for i, (name, provider, model_id) in enumerate(agents)]}
    publish(output / "demo.json", status)
    try:
        initial = initialize([33, 8, 18], seed=seed)
        save(output / "initial.json", initial)
        status["initial_sha256"] = fingerprint(initial)
        status["before"] = match(output / "initial.json", output / "initial.json",
                                 output / "before", max_steps)
        results = feedback(output / "before")
        (output / "shared-feedback.json").write_text(encode(results))
        status["phase"] = "editing"
        status["edit_started_at"] = time.time()
        for agent in status["agents"]:
            agent["status"] = "editing"
        publish(output / "demo.json", status)

        def request(index):
            name, provider, model_id = agents[index]
            prompt = edit_prompt(name, index + 1, initial, results)
            prefix = output / f"player-{index + 1}"
            prefix.with_suffix(".prompt.txt").write_text(prompt)
            text, metadata = complete(provider, model_id, prompt, timeout, 24000)
            prefix.with_suffix(".reply.txt").write_text(text)
            prefix.with_suffix(".provider.json").write_text(encode(metadata))
            reply = parse_reply(text)
            changes = check_revision(initial, reply["model"])
            save(prefix.with_suffix(".json"), reply["model"])
            return {"status": "submitted", "reason": reply["reason"], **changes}

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(request, index): index for index in range(2)}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    status["agents"][index].update(future.result())
                except Exception as error:
                    status["agents"][index].update(status="failed", error=str(error))
                publish(output / "demo.json", status)
        if any(agent["status"] == "failed" for agent in status["agents"]):
            raise ValueError("An agent did not submit valid weights. See the demo record.")
        status["phase"] = "rematch"
        publish(output / "demo.json", status)
        status["after"] = match(output / "player-1.json", output / "player-2.json",
                                output / "after", max_steps)
        status["phase"] = "complete"
        return status
    except Exception as error:
        status.update(phase="failed", error=str(error))
        raise
    finally:
        publish(output / "demo.json", status)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=1800)
    parser.add_argument("--pairing", choices=PAIRINGS, default="astra-opus")
    args = parser.parse_args()
    print(encode(run_demo(args.output, args.seed, args.max_steps, pairing=args.pairing)))
