"""A data-only tool protocol over subscription CLI calls. No returned code runs."""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
from pathlib import Path
import time

from .demo import PAIRINGS, publish
from .game import match
from .lab import WeightLab, TOOLS
from .network import encode, fingerprint, initialize, load, save
from .providers import complete


def parse_calls(text):
    if len(text.encode()) > 100_000:
        raise ValueError("Reply exceeds 100 KB. Use small tool calls.")
    text = text.strip()
    if text.startswith("```") and text.splitlines()[-1].strip() == "```":
        text = "\n".join(text.splitlines()[1:-1])
    packet = json.loads(text)
    json.dumps(packet, allow_nan=False)
    if not isinstance(packet, dict) or set(packet) != {"note", "calls"}:
        raise ValueError("Return exactly note and calls.")
    if not isinstance(packet["note"], str) or len(packet["note"]) > 300:
        raise ValueError("Keep the note under 300 characters.")
    if not isinstance(packet["calls"], list) or not 1 <= len(packet["calls"]) <= 4:
        raise ValueError("Return 1 to 4 tool calls.")
    for call in packet["calls"]:
        if not isinstance(call, dict) or set(call) != {"tool", "arguments"} \
                or not isinstance(call["tool"], str) or not isinstance(call["arguments"], dict):
            raise ValueError("Each call needs a tool name and an arguments object.")
    return packet


def prompt_for(lab, history, turn):
    return f"""You are programming a neural network through direct weight edits.
Work quickly. Use short notes and small tool calls. Do not write a long analysis.
Do not return a complete model. Use edit_weights to change numbers, test_inputs
to check them, and submit when ready. Aim for 3 to 5 replies. This is reply {turn}/10.
Your tools are a JSON protocol handled by a trusted host. DO NOT call native CLI
tools, shell, Python, file tools, or web tools. DO NOT write or run code. No training,
gradients, optimizers, or automated parameter search. Choose explicit numbers by reasoning.
Return JSON only: {{"note":"One short sentence.","calls":[{{"tool":"info","arguments":{{}}}}]}}
You can batch up to four sequential calls. Tool errors return as data; correct them.
Both agents started from the same random network. You may inspect the recorded
game, but you cannot read the other agent's pending weights. Your candidate is private.
Keep the 31 -> 8 ReLU -> 18 linear architecture. zero_all can clear the random weights
before you set selected entries. column:null sets a bias; otherwise column is the
input index in that neuron's weight row. Indices start at zero.
Use test_inputs on synthetic observations or inputs from read_steps. A test is
ONLY a network forward pass: no opponent, rollout, optimizer, or gradients. Include
expected_action when checking behavior. Try at least two distinct situations.
Inspect layer values when a test fails, adjust your weights, and test again.
You must edit and test the latest revision before submit. Stop after submit.
There are at most 40 tool calls, 12 edits, and 64 input cases. No need to use them all.
Movement speed is 10; attacks deal 10 damage in a 160-pixel-wide forward box from
the fighter center. Fighters are 80x180. Inputs are blocked while hit or attacking.
Attack recovery includes a 20-frame cooldown. Jump speed is -30; gravity is 2/frame.
Inputs use self then opponent then relative x, relative y, and time remaining.
Largest output score selects the action; first index wins ties. Positive relative x
means opponent is right. Ground contact is 1 when grounded. Both attacks can hit
in one step. The match is 30 seconds; more remaining health wins on timeout.
These test results show action selection, not proof of match strength.
Use ASD-STE100 Simplified Technical English for notes and reasons.

TOOLS
{json.dumps(TOOLS, separators=(',', ':'))}
CURRENT SUMMARY
{json.dumps(lab.info({}), separators=(',', ':'))}
TOOL HISTORY
{json.dumps(history, separators=(',', ':'), allow_nan=False)}
"""


def run_agent(lab, provider, model_id, max_seconds=240, reply_timeout=60):
    history = []
    deadline = time.monotonic() + max_seconds
    for turn in range(1, 11):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("The four-minute editing budget expired.")
        progress = {"status": "request_pending", "turn": turn, "revision": lab.revision,
                    "tool_calls": lab.calls, "test_cases": lab.test_cases,
                    "request_started_at": time.time(), "reply_timeout": min(reply_timeout, remaining)}
        publish(lab.directory / "progress.json", progress)
        prompt = prompt_for(lab, history, turn)
        (lab.directory / f"turn-{turn}.prompt.txt").write_text(prompt)
        text, metadata = complete(provider, model_id, prompt, min(reply_timeout, remaining),
                                  4000, quick=True)
        (lab.directory / f"turn-{turn}.reply.txt").write_text(text)
        (lab.directory / f"turn-{turn}.provider.json").write_text(encode(metadata))
        try:
            packet = parse_calls(text)
        except (ValueError, TypeError) as error:
            history.append({"invalid_reply": text[:2000], "error": str(error)})
            continue
        results = []
        for call in packet["calls"]:
            result = lab.dispatch(call["tool"], call["arguments"])
            results.append({"tool": call["tool"], "result": result})
            if lab.submitted:
                return json.loads((lab.directory / "submission.json").read_text())
        history.append({"agent": packet, "tool_results": results})
    raise ValueError("Reply budget exhausted before submission.")


def run_tool_demo(output, seed=42, max_steps=1800):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    agents = PAIRINGS["astra-fable"]
    status = {"phase": "initializing", "mode": "input-tools", "seed": seed,
              "max_steps": max_steps, "pairing": "astra-fable",
              "agents": [{"name": name, "player": i + 1, "provider": provider,
                          "model": model, "status": "waiting"}
                         for i, (name, provider, model) in enumerate(agents)]}
    publish(output / "demo.json", status)
    try:
        initial = initialize([31, 8, 18], seed=seed)
        save(output / "initial.json", initial)
        status["initial_sha256"] = fingerprint(initial)
        status["before"] = match(output / "initial.json", output / "initial.json", output / "before", max_steps)
        status["phase"] = "editing"
        labs = [WeightLab(output / "initial.json", output / "before", output / f"lab-{i + 1}", i + 1)
                for i in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_agent, lab, provider, model): index
                       for index, (lab, (_, provider, model)) in enumerate(zip(labs, agents))}
            while pending:
                finished, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for future, index in pending.items():
                    path = labs[index].directory / "progress.json"
                    if path.exists():
                        status["agents"][index].update(json.loads(path.read_text()))
                for future in finished:
                    index = pending.pop(future)
                    try:
                        result = future.result()
                        save(output / f"player-{index + 1}.json", load(labs[index].directory / "submitted.json"))
                        status["agents"][index].update(result, status="submitted")
                    except Exception as error:
                        status["agents"][index].update(status="failed", error=str(error))
                publish(output / "demo.json", status)
        if any(agent["status"] == "failed" for agent in status["agents"]):
            raise ValueError("An agent did not finish the input-test loop. See its saved tool log.")
        status["phase"] = "rematch"
        publish(output / "demo.json", status)
        status["after"] = match(output / "player-1.json", output / "player-2.json", output / "after", max_steps)
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
    args = parser.parse_args()
    print(encode(run_tool_demo(args.output, args.seed, args.max_steps)))
