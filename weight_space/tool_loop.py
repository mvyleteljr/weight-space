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
from .tool_schema import TOOL_REPLY_SCHEMA


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
The CLI enforces a strict reply schema. Include each required field. Use false for
zero_all unless you intend to clear all weights; use null for no expected action.
You can batch up to four sequential calls. Tool errors return as data; correct them.
Both agents started from the same random network. You may inspect the recorded
game, but you cannot read the other agent's pending weights. Your candidate is private.
You are now reviewing game {lab.game_number} to prepare for game {lab.game_number + 1}.
Your weights carry forward from your last game. They are not reset between games.
The summary's player is your slot in the recorded game. next_player is your slot
in the next game: 1 is warrior; 2 is wizard. Prepare for that character.
If the summary contains two recordings, the same weights played both characters.
Review both results before editing. Each recording states your player slot and its
start index in read_steps. Actions remain world left/right. The same policy must
work as warrior and wizard. The opponent's pending weights remain private.
The original flag in inspect_step means the weights at the start of this edit round.
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
Read the interface rules below. Fighters can move through each other. They turn
toward each other automatically. You can jump and move in the air. There is no
block action or invulnerability. Defense uses position and timing. An attack
checks for damage only when it starts, not throughout the attack animation.
Inputs use self then opponent then relative x, relative y, and time remaining.
Largest output score selects the action; first index wins ties. Positive relative x
means opponent is right. Ground contact is 1 when grounded. Both attacks can hit
in one step. More remaining health wins when the match step limit is reached.
These test results show action selection, not proof of match strength.
Use ASD-STE100 Simplified Technical English for notes and reasons.

TOOLS
{json.dumps(TOOLS, separators=(',', ':'))}
CURRENT SUMMARY
{json.dumps(lab.info({}), separators=(',', ':'))}
YOUR WEIGHTS FROM THE LAST GAME (only after game 1)
{json.dumps(lab.initial if lab.game_number > 1 else None, separators=(',', ':'))}
TOOL HISTORY
{json.dumps(history, separators=(',', ':'), allow_nan=False)}
"""


def run_agent(lab, provider, model_id, max_seconds=240, reply_timeout=60):
    history = []
    replies = []
    timeout_retries = 0
    deadline = time.monotonic() + max_seconds
    for turn in range(1, 11):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("The editing time budget expired.")
        progress = {"status": "request_pending", "turn": turn, "revision": lab.revision,
                    "tool_calls": lab.calls, "test_cases": lab.test_cases,
                    "request_started_at": time.time(), "reply_timeout": min(reply_timeout, remaining)}
        publish(lab.directory / "progress.json", progress)
        prompt = prompt_for(lab, history, turn)
        (lab.directory / f"turn-{turn}.prompt.txt").write_text(prompt)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("The editing time budget expired.")
            progress.update(request_started_at=time.time(), reply_timeout=min(reply_timeout, remaining),
                            timeout_retries=timeout_retries)
            publish(lab.directory / "progress.json", progress)
            try:
                text, metadata = complete(provider, model_id, prompt, min(reply_timeout, remaining),
                                          4000, quick=True,
                                          output_schema=TOOL_REPLY_SCHEMA if provider in ("codex", "claude") else None)
                break
            except TimeoutError:
                retry = timeout_retries == 0 and deadline - time.monotonic() > 0
                note = ("The reply timed out. Retrying once with the same inputs." if retry else
                        "The reply timed out. Keep the weights from the last game.")
                replies.append({"turn": turn, "note": note, "calls": []})
                publish(lab.directory / "replies.json", replies)
                if not retry:
                    raise
                timeout_retries += 1
        (lab.directory / f"turn-{turn}.reply.txt").write_text(text)
        (lab.directory / f"turn-{turn}.provider.json").write_text(encode(metadata))
        try:
            packet = parse_calls(text)
        except (ValueError, TypeError) as error:
            history.append({"invalid_reply": text[:2000], "error": str(error)})
            replies.append({"turn": turn, "note": "Reply format error: " + str(error), "calls": []})
            publish(lab.directory / "replies.json", replies)
            continue
        entry = {"turn": turn, "note": packet["note"],
                 "calls": [{**call, "result": None} for call in packet["calls"]]}
        replies.append(entry)
        publish(lab.directory / "replies.json", replies)
        results = []
        for index, call in enumerate(packet["calls"]):
            result = lab.dispatch(call["tool"], call["arguments"])
            entry["calls"][index]["result"] = result
            publish(lab.directory / "replies.json", replies)
            results.append({"tool": call["tool"], "result": result})
            if lab.submitted:
                return json.loads((lab.directory / "submission.json").read_text())
        history.append({"agent": packet, "tool_results": results})
    raise ValueError("Reply budget exhausted before submission.")


def game_directory(number):
    return {1: "before", 2: "after"}.get(number, f"game-{number}")


def player_spec(value):
    provider, separator, model = value.partition(":")
    if provider not in ("codex", "claude", "tinfoil") or not separator or not model:
        raise ValueError("Use codex:model, claude:model, or tinfoil:model.")
    names = {"gpt-6-astra": "Astra", "fable": "Fable", "gpt-6-luna": "Luna",
             "deepseek-v4-1-flash": "DeepSeek Flash", "gemma4-31b": "Gemma 4"}
    return names.get(model, model), provider, model


def run_tool_demo(output, seed=42, max_steps=1800, games=2, players=None,
                  reply_timeout=60, edit_seconds=240, swap_sides=False, paired_games=False):
    if type(games) is not int or not 2 <= games <= 9:
        raise ValueError("Choose 2 to 9 games.")
    if paired_games and (not swap_sides or games < 4 or games % 2):
        raise ValueError("Paired games need side swaps and 4, 6, or 8 games.")
    if not 0 < reply_timeout <= 600 or not 0 < edit_seconds <= 3600:
        raise ValueError("Use positive time limits: replies up to 600 seconds; edits up to 3600 seconds.")
    agents = tuple(player_spec(value) for value in players) if players else PAIRINGS["astra-fable"]
    if len(agents) != 2:
        raise ValueError("Supply exactly two players.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    status = {"phase": "initializing", "mode": "input-tools", "seed": seed,
              "max_steps": max_steps, "pairing": "custom" if players else "astra-fable", "games_requested": games,
              "reply_timeout": reply_timeout, "edit_seconds": edit_seconds,
              "swap_sides": swap_sides,
              "paired_games": paired_games,
              "tally": {"wins": [0, 0], "draws": 0, "games": 0},
              "games": [], "edit_rounds": [],
              "agents": [{"name": name, "player": i + 1, "provider": provider,
                          "model": model, "status": "waiting"}
                         for i, (name, provider, model) in enumerate(agents)]}
    publish(output / "demo.json", status)
    try:
        initial = initialize([31, 8, 18], seed=seed)
        save(output / "initial.json", initial)
        status["initial_sha256"] = fingerprint(initial)
        current = [output / "initial.json"] * 2

        def play(number):
            order = [2, 1] if swap_sides and number % 2 == 0 else [1, 2]
            directory = game_directory(number)
            result = match(current[order[0] - 1], current[order[1] - 1], output / directory, max_steps)
            status["games"].append({"number": number, "directory": directory, "result": result,
                                    "player_agents": order,
                                    "edit_after_game": number if not paired_games or number % 2 == 0 else None})
            if result["winner"] is None:
                status["tally"]["draws"] += 1
            else:
                status["tally"]["wins"][order[result["winner"] - 1] - 1] += 1
            status["tally"]["games"] += 1
            if number in (1, 2):
                status[game_directory(number)] = result
            publish(output / "demo.json", status)

        play(1)
        if paired_games:
            play(2)
        prior = [None, None]
        for completed_game in range(2 if paired_games else 1, games, 2 if paired_games else 1):
            status.update(phase="editing", editing_after_game=completed_game)
            status["agents"] = [{"name": name, "player": i + 1, "provider": provider,
                                 "model": model, "status": "waiting"}
                                for i, (name, provider, model) in enumerate(agents)]
            edit_dir = output if completed_game == 1 else output / f"edit-{completed_game}"
            source_game = completed_game - 1 if paired_games else completed_game
            source_order = status["games"][source_game - 1]["player_agents"]
            labs = [WeightLab(current[i], output / game_directory(source_game),
                              edit_dir / f"lab-{i + 1}", source_order.index(i + 1) + 1, completed_game, prior[i],
                              [(output / game_directory(completed_game), 2 - i, completed_game)] if paired_games else None)
                    for i in range(2)]
            for i, lab in enumerate(labs):
                lab.next_player = 2 - i if swap_sides and (completed_game + 1) % 2 == 0 else i + 1
            publish(output / "demo.json", status)
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = {pool.submit(run_agent, lab, provider, model, edit_seconds, reply_timeout): index
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
                            current[index] = edit_dir / f"player-{index + 1}.json"
                            save(current[index], load(labs[index].directory / "submitted.json"))
                            prior[index] = result
                            status["agents"][index].update(result, status="submitted")
                        except TimeoutError as error:
                            # Only submitted models can become current. Discard this round's
                            # candidate, including edits made before a later reply timed out.
                            status["agents"][index].update(status="kept_previous", error=str(error),
                                note="Edit skipped after a timeout. The weights from the last game remain active.",
                                active_sha256=fingerprint(load(current[index])))
                        except Exception as error:
                            status["agents"][index].update(status="failed", error=str(error))
                    publish(output / "demo.json", status)
            if any(agent["status"] == "failed" for agent in status["agents"]):
                raise ValueError("An agent did not finish the input-test loop. See its saved tool log.")
            status["edit_rounds"].append({"after_game": completed_game, "agents": status["agents"]})
            status["phase"] = "rematch"
            publish(output / "demo.json", status)
            play(completed_game + 1)
            if paired_games:
                play(completed_game + 2)
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
    parser.add_argument("--games", type=int, default=2, choices=range(2, 10))
    parser.add_argument("--player-1", default="codex:gpt-6-astra")
    parser.add_argument("--player-2", default="claude:fable")
    parser.add_argument("--reply-timeout", type=float, default=60)
    parser.add_argument("--edit-seconds", type=float, default=240)
    parser.add_argument("--swap-sides", action="store_true", help="Switch characters each game; edit after every game.")
    parser.add_argument("--paired-games", action="store_true", help="With --swap-sides, wait for both assignments before editing.")
    args = parser.parse_args()
    print(encode(run_tool_demo(args.output, args.seed, args.max_steps, args.games,
                              [args.player_1, args.player_2], args.reply_timeout, args.edit_seconds, args.swap_sides, args.paired_games)))
