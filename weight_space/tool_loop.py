"""A data-only tool protocol over subscription CLI calls. No returned code runs."""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import math
import random
import re
from pathlib import Path
import time
import threading

from .demo import PAIRINGS, publish
from .game import match
from .lab import WeightLab, TOOLS
from .network import encode, fingerprint, initialize, load, save
from .providers import complete, ProviderSession
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
    if not isinstance(packet["calls"], list) or not 1 <= len(packet["calls"]) <= 8:
        raise ValueError("Return 1 to 8 tool calls.")
    for call in packet["calls"]:
        if not isinstance(call, dict) or set(call) != {"tool", "arguments"} \
                or not isinstance(call["tool"], str) or not isinstance(call["arguments"], dict):
            raise ValueError("Each call needs a tool name and an arguments object.")
    return packet


AGENT_CONTEXT_PATH = Path(__file__).resolve().parents[1] / "docs" / "agent-context.md"


def prompt_summary(info, *, include_interface=False, current_only=False):
    """Keep decision-relevant state; omit duplicate results and diagram metadata."""
    keys = ("revision", "calls_left", "test_cases_left", "edits_left", "seconds_left")
    summary = {key: info[key] for key in keys}
    arch = info["architecture"]
    summary["architecture"] = {key: arch[key] for key in
        ("inputs", "outputs", "parameters", "sha256", "action_feedback", "memory_size")}
    summary["architecture"]["layers"] = [{key: layer[key] for key in
        ("inputs", "width", "type", "activation", "parameters")} for layer in arch["layers"]]
    if not current_only:
        summary.update({key: info[key] for key in
            ("player", "completed_game", "next_player", "next_game", "recorded_steps", "match_dimensions")})
        summary["recording_summary"] = [dict(record, reason=source["result"]["reason"])
            for record, source in zip(info["recording_summary"], info["recordings"])]
        prior = info["prior_submission"]
        summary["prior_submission"] = ({key: prior[key] for key in
            ("reason", "after_sha256", "changed_parameters", "architecture_changed", "tests") if key in prior}
            if prior else None)
        if info["context_requests"]:
            summary["context_requests"] = info["context_requests"]
    if include_interface:
        summary["interface"] = {key: info["interface"][key] for key in ("fps", "width", "height", "actions")}
        summary["input_index"] = info["input_index"]
    return summary


def single_reply_context(lab):
    """Supply the data needed to edit without a read/response round trip."""
    indices = set()
    if lab.rows:
        indices.update(round(i * (len(lab.rows)-1) / 11) for i in range(12))
        for recording in lab.recording_summary():
            for event in recording["contact_events"]:
                indices.update(i for i in (event["step"]-1, event["step"], event["step"]+1)
                               if 0 <= i < len(lab.rows))
    samples = []
    for i in sorted(indices):
        row = lab.rows[i]
        samples.append({"index": i, "game": row["recorded_game"], "your_player": row["recorded_player"],
                        "inputs_before": row["observations"][row["recorded_player"]-1],
                        "actions": row["actions"],
                        "health_after": [f["health"] for f in row["state"]["fighters"]]})
    return {"reply_limit": 1, "current_policy": lab.initial,
            "sampled_steps": samples, "samples_are_not_a_contiguous_sequence": True}


def prompt_for(lab, history, turn):
    # Read the editable source for every request; exact rendered prompts are logged.
    template = AGENT_CONTEXT_PATH.read_text(encoding="utf-8")
    values = {
        "REPLY_NUMBER": str(turn),
        "RUN_PHASE": ("INITIALIZATION BEFORE GAME 1. No games have been played in this run."
                      if lab.game_number == 0 else
                      f"Review game {lab.game_number} to prepare for game {lab.game_number + 1}. "
                      "Weights carry forward within this run. The before-game-1 instructions no longer apply."),
        "TOOLS": json.dumps(TOOLS, separators=(',', ':')),
        "CURRENT_SUMMARY": json.dumps(prompt_summary(lab.info({}), include_interface=True), separators=(',', ':')),
        "ROUND_START_WEIGHTS": json.dumps(lab.initial if lab.game_number > 1 else None, separators=(',', ':')),
        "TOOL_HISTORY": json.dumps(history, separators=(',', ':'), allow_nan=False),
    }
    # Substitute once, so braces in user prose or inserted JSON are never evaluated.
    def substitute(match):
        name = match.group(1)
        if name not in values:
            raise ValueError(f"Unknown agent-context placeholder: {name}")
        return values[name]
    rendered = re.sub(r"\{\{([A-Z_]+)\}\}", substitute, template)
    if getattr(lab, "single_reply", False):
        rendered += "\n# One-reply input bundle\n" + json.dumps(single_reply_context(lab), separators=(',', ':'))
    return rendered


def session_prompt(lab, history, turn, session):
    context = AGENT_CONTEXT_PATH.read_text(encoding="utf-8")
    if session.context_text is None or not session.session_id:
        return prompt_for(lab, history, turn), context, "initial"
    new_round = session.round != lab.game_number
    info = lab.info({})
    summary = prompt_summary(info, current_only=not new_round)
    updates = history[0 if new_round else session.history_sent:]
    payload = {
        "phase": "before_game_1" if lab.game_number == 0 else "between_games",
        "completed_game": lab.game_number, "reply": turn,
        "response_deadline_seconds": min(120, info.get("seconds_left") or 120),
        "summary": summary,
        "tool_results": [entry.get("tool_results", entry) for entry in updates],
    }
    if getattr(lab, "single_reply", False):
        payload["single_reply_context"] = single_reply_context(lab)
    instructions = ""
    if context != session.context_text:
        # Send revised instructions once, without replaying old dynamic payloads.
        instructions = "REVISED INSTRUCTIONS (replace previous instructions):\n" + re.sub(
            r"\{\{([A-Z_]+)\}\}", "[provided in the current update]", context) + "\n"
    notice = ("New round: use the active policy identified below; discard unsubmitted edits. "
              "Edit/test counters reset. Use the supplied current policy.\n" if new_round else "")
    return (instructions + notice + "UPDATE ONLY. Continue in the same JSON tool protocol.\n" +
            json.dumps(payload, separators=(',', ':'), allow_nan=False), context, "update")


class SingleReplyError(Exception):
    """The single proposal was invalid; retain the active policy."""


class ReviewPending(Exception):
    """Another agent requested an environment review; stop new work."""


def check_review(lab):
    if getattr(lab, "review_event", None) is not None and lab.review_event.is_set():
        raise ReviewPending("Training paused for environment review.")


def run_agent(lab, provider, model_id, max_seconds=240, reply_timeout=120):
    history = []
    replies = []
    timeout_retries = 0
    deadline = time.monotonic() + max_seconds
    single = getattr(lab, "single_reply", False)
    for turn in range(1, 2 if single else 11):
        check_review(lab)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("The editing time budget expired.")
        lab.seconds_left = remaining
        progress = {"status": "request_pending", "turn": turn, "revision": lab.revision,
                    "tool_calls": lab.calls, "test_cases": lab.test_cases,
                    "request_started_at": time.time(), "reply_timeout": min(reply_timeout, remaining)}
        publish(lab.directory / "progress.json", progress)
        session = getattr(lab, "provider_session", None)
        if session is not None:
            prompt, sent_context, prompt_kind = session_prompt(lab, history, turn, session)
        else:
            prompt, sent_context, prompt_kind = prompt_for(lab, history, turn), None, "stateless"
        (lab.directory / f"turn-{turn}.prompt.txt").write_text(prompt)
        while True:
            check_review(lab)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("The editing time budget expired.")
            progress.update(request_started_at=time.time(), reply_timeout=min(reply_timeout, remaining),
                            timeout_retries=timeout_retries)
            publish(lab.directory / "progress.json", progress)
            attempt_prompt = ("Previous request was interrupted. No tools from its response were applied. "
                              "Respond to this request again; do not assume any proposed edits executed.\n" + prompt
                              if session is not None and session.interrupted else prompt)
            (lab.directory / f"turn-{turn}.attempt-{timeout_retries}.prompt.txt").write_text(attempt_prompt)
            try:
                text, metadata = complete(provider, model_id, attempt_prompt, min(reply_timeout, remaining),
                                          16000 if single else 4000, quick=True, reasoning_effort="high" if model_id == "claude-opus-5-5" else "medium",
                                          output_schema=TOOL_REPLY_SCHEMA if provider in ("codex", "claude") else None,
                                          **({"session": session} if session is not None else {}))
                if session is not None:
                    session.context_text, session.round, session.history_sent = sent_context, lab.game_number, len(history)
                    session.interrupted = False
                    metadata.update(prompt_kind=prompt_kind, prompt_characters=len(attempt_prompt))
                    publish(lab.directory / "session.json", {"provider": provider, "model": model_id,
                        "session_id": session.session_id, "requests": session.requests})
                break
            except TimeoutError:
                check_review(lab)
                retry = not single and timeout_retries == 0 and deadline - time.monotonic() > 0
                note = ("The reply timed out. Retrying once with the same inputs." if retry else
                        "The reply timed out. Keep the weights from the last game.")
                replies.append({"turn": turn, "note": note, "calls": []})
                publish(lab.directory / "replies.json", replies)
                if not retry:
                    raise
                timeout_retries += 1
        (lab.directory / f"turn-{turn}.reply.txt").write_text(text)
        (lab.directory / f"turn-{turn}.provider.json").write_text(encode(metadata))
        check_review(lab)
        try:
            packet = parse_calls(text)
        except (ValueError, TypeError) as error:
            history.append({"invalid_reply": text[:2000], "error": str(error)})
            replies.append({"turn": turn, "note": "Reply format error: " + str(error), "calls": []})
            publish(lab.directory / "replies.json", replies)
            if single:
                raise SingleReplyError(str(error)) from error
            continue
        if single and packet["calls"][-1]["tool"] not in ("submit", "request_context"):
            raise SingleReplyError("The single reply must end with submit or request_context.")
        entry = {"turn": turn, "note": packet["note"],
                 "calls": [{**call, "result": None} for call in packet["calls"]]}
        replies.append(entry)
        publish(lab.directory / "replies.json", replies)
        results = []
        for index, call in enumerate(packet["calls"]):
            check_review(lab)
            result = lab.dispatch(call["tool"], call["arguments"])
            entry["calls"][index]["result"] = result
            publish(lab.directory / "replies.json", replies)
            results.append({"tool": call["tool"], "result": result})
            if single and "error" in result:
                raise SingleReplyError(result["error"])
            if call["tool"] == "request_context" and "error" not in result:
                if getattr(lab, "review_event", None) is not None:
                    lab.review_event.set()
                return {"awaiting_approval": True, "requests": lab.context_requests}
            if lab.submitted:
                submission = json.loads((lab.directory / "submission.json").read_text())
                if single:
                    submission["tests"] = [r for r in results if r["tool"] in ("test_inputs", "test_sequence")]
                return submission
        history.append({"agent": packet, "tool_results": results})
    if single:
        raise SingleReplyError("The single reply did not submit a policy.")
    raise ValueError("Reply budget exhausted before submission.")


def game_directory(number):
    return {1: "before", 2: "after"}.get(number, f"game-{number}")


def player_spec(value):
    provider, separator, model = value.partition(":")
    if provider not in ("codex", "claude", "tinfoil") or not separator or not model:
        raise ValueError("Use codex:model, claude:model, or tinfoil:model.")
    names = {"gpt-6-astra": "Astra", "fable": "Fable", "claude-opus-5-5": "Opus 5.5", "gpt-6-luna": "Luna",
             "deepseek-v4-1-flash": "DeepSeek Flash", "gemma4-31b": "Gemma 4"}
    return names.get(model, model), provider, model


def run_tool_demo(output, seed=42, max_steps=1800, games=2, players=None,
                  reply_timeout=120, edit_seconds=240, swap_sides=False, paired_games=False,
                  duration_seconds=None, resume_from=None, prepare_agents=False, persistent_sessions=True,
                  zero_initial=False, wait_for_viewer=False, wait_for_start=False, single_reply=False, random_sides=False):
    if type(games) is not int or not 2 <= games <= 9:
        raise ValueError("Choose 2 to 9 games.")
    if random_sides and (swap_sides or paired_games):
        raise ValueError("Random assignments cannot be combined with fixed side swaps or paired games.")
    if paired_games and (not swap_sides or games < 4 or games % 2):
        raise ValueError("Paired games need side swaps and 4, 6, or 8 games.")
    if not 0 < reply_timeout <= 600 or not 0 < edit_seconds <= 3600:
        raise ValueError("Use positive time limits: replies up to 600 seconds; edits up to 3600 seconds.")
    if duration_seconds is not None and (not math.isfinite(duration_seconds) or not 0 < duration_seconds <= 3600):
        raise ValueError("Training duration must be positive and at most 3600 seconds.")
    started = time.monotonic()
    deadline = started + duration_seconds if duration_seconds is not None else None
    agents = tuple(player_spec(value) for value in players) if players else PAIRINGS["astra-opus"]
    if len(agents) != 2:
        raise ValueError("Supply exactly two players.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    status = {"phase": "initializing", "mode": "input-tools", "seed": seed,
              "max_steps": max_steps, "pairing": "custom" if players else "astra-opus", "games_requested": games,
              "reply_timeout": reply_timeout, "edit_seconds": edit_seconds,
              "duration_seconds": duration_seconds, "started_at": time.time(),
              "ends_at": time.time() + duration_seconds if deadline is not None else None,
              "swap_sides": swap_sides, "random_sides": random_sides,
              "paired_games": paired_games,
              "tally": {"wins": [0, 0], "draws": 0, "games": 0},
              "games": [], "edit_rounds": [],
              "agents": [{"name": name, "player": i + 1, "provider": provider,
                          "model": model, "status": "waiting"}
                         for i, (name, provider, model) in enumerate(agents)]}
    publish(output / "demo.json", status)
    sessions = [ProviderSession(provider, model) if persistent_sessions and provider in ("codex", "claude") else None
                for _, provider, model in agents]
    try:
        initial = initialize([31, 8, 18], seed=seed, zero=zero_initial)
        save(output / "initial.json", initial)
        status["initial_sha256"] = fingerprint(initial)
        current = [output / "initial.json"] * 2
        if resume_from is not None:
            previous = Path(resume_from)
            previous_status = json.loads((previous / "demo.json").read_text())
            if [(a["provider"], a["model"]) for a in previous_status["agents"]] != [(a[1], a[2]) for a in agents]:
                raise ValueError("Resume requires the same agents in the same order.")
            last_game = previous_status["games"][-1]
            for slot, agent_number in enumerate(last_game["player_agents"], 1):
                path = output / f"initial-agent-{agent_number}.json"
                save(path, load(previous / last_game["directory"] / f"player-{slot}.json"))
                current[agent_number - 1] = path
            status["resumed_from"] = str(previous)


        def wait_if_paused():
            nonlocal deadline
            paused_at = time.monotonic()
            while (output / "paused").exists():
                time.sleep(0.1)
            elapsed = time.monotonic() - paused_at
            if deadline is not None:
                deadline += elapsed
                status["ends_at"] += elapsed

        orders = {}
        assignment_rng = random.Random(seed)
        def order_for(number):
            if number not in orders:
                swapped = bool(assignment_rng.getrandbits(1)) if random_sides else swap_sides and number % 2 == 0
                orders[number] = [2, 1] if swapped else [1, 2]
            return orders[number]

        def play(number):
            wait_if_paused()
            order = order_for(number)
            directory = game_directory(number)
            result = match(current[order[0] - 1], current[order[1] - 1], output / directory, max_steps)
            status["games"].append({"number": number, "directory": directory, "result": result,
                                    "player_agents": order,
                                    "edit_after_game": number if not paired_games or number % 2 == 0 else None})
            if number in (1, 2):
                status[game_directory(number)] = result
            if wait_for_viewer:
                status.update(phase="playing", viewing_game=number)
            publish(output / "demo.json", status)
            if wait_for_viewer:
                while not (output / f"viewed-{number}").exists():
                    wait_if_paused()
                    time.sleep(0.1)
            if result["winner"] is None:
                status["tally"]["draws"] += 1
            else:
                status["tally"]["wins"][order[result["winner"] - 1] - 1] += 1
            status["tally"]["games"] += 1
            publish(output / "demo.json", status)

        if not prepare_agents:
            play(1)
            if paired_games:
                play(2)
        prior = [None, None]
        completed_game = 0 if prepare_agents else (2 if paired_games else 1)
        while (time.monotonic() < deadline if deadline is not None else completed_game < games):
            wait_if_paused()
            if deadline is not None:
                status["games_requested"] = completed_game + (2 if paired_games else 1)
            round_budget = min(edit_seconds, max(0, deadline - time.monotonic())) if deadline is not None else edit_seconds
            if round_budget <= 0:
                break
            next_order = order_for(completed_game + 1)
            status["next_player_agents"] = next_order
            status.update(phase="preparing_agents" if completed_game == 0 else "editing", editing_after_game=completed_game)
            status["agents"] = [{"name": name, "player": i + 1, "provider": provider,
                                 "model": model, "status": "waiting"}
                                for i, (name, provider, model) in enumerate(agents)]
            edit_dir = output if completed_game == 1 else output / f"edit-{completed_game}"
            if completed_game == 0:
                labs = [WeightLab(current[i], None, edit_dir / f"lab-{i + 1}", next_order.index(i + 1) + 1, 0) for i in range(2)]
            else:
                source_game = completed_game - 1 if paired_games else completed_game
                source_order = status["games"][source_game - 1]["player_agents"]
                labs = [WeightLab(current[i], output / game_directory(source_game),
                                  edit_dir / f"lab-{i + 1}", source_order.index(i + 1) + 1, completed_game, prior[i],
                                  [(output / game_directory(completed_game), 2 - i, completed_game)] if paired_games else None)
                        for i in range(2)]
            review_event = threading.Event()
            for i, lab in enumerate(labs):
                lab.single_reply = single_reply
                lab.review_event = review_event
                lab.provider_session = sessions[i]
                lab.next_player = next_order.index(i + 1) + 1
            publish(output / "demo.json", status)
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = {pool.submit(run_agent, lab, provider, model, round_budget, min(reply_timeout, round_budget)): index
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
                            if result.get("awaiting_approval"):
                                review_event.set()
                                status.update(phase="awaiting_approval", stop_reason="environment_change_requested")
                                status.setdefault("approval_requests", []).append({"agent": agents[index][0],
                                    "after_game": completed_game, "requests": result["requests"]})
                                status["agents"][index].update(status="awaiting_approval")
                                publish(output / "approval-request.json", {"status": "awaiting_user_approval",
                                    "requests": status["approval_requests"], "changes_applied": False})
                                continue
                            current[index] = edit_dir / f"player-{index + 1}.json"
                            save(current[index], load(labs[index].directory / "submitted.json"))
                            prior[index] = result
                            status["agents"][index].update(result, status="submitted")
                        except ReviewPending:
                            status["agents"][index].update(status="paused_for_review")
                        except (TimeoutError, SingleReplyError) as error:
                            # Only submitted models can become current. Discard this round's
                            # candidate, including edits made before a later reply timed out.
                            status["agents"][index].update(status="update_rejected" if isinstance(error, SingleReplyError) else "kept_previous", error=str(error),
                                note="Update not submitted. The previous policy remains active.",
                                active_sha256=fingerprint(load(current[index])))
                        except Exception as error:
                            status["agents"][index].update(status="failed", error=str(error))
                    publish(output / "demo.json", status)
            if review_event.is_set():
                status.update(phase="awaiting_approval", games_requested=len(status["games"]),
                              elapsed_seconds=time.monotonic() - started)
                status["edit_rounds"].append({"after_game": completed_game, "agents": status["agents"]})
                return status
            if any(agent["status"] == "failed" for agent in status["agents"]):
                raise ValueError("An agent did not finish the input-test loop. See its saved tool log.")
            status["edit_rounds"].append({"after_game": completed_game, "agents": status["agents"]})
            if wait_for_start and completed_game == 0:
                # A timeout is acceptable later, but Start requires both initial submissions.
                if any(agent["status"] != "submitted" for agent in status["agents"]):
                    raise ValueError("Initial policies were not submitted by both agents. Reset to retry.")
                status.update(phase="ready", ends_at=None)
                publish(output / "demo.json", status)
                while not (output / "start").exists():
                    time.sleep(0.1)
                started = time.monotonic()
                deadline = started + duration_seconds if duration_seconds is not None else None
                status.update(started_at=time.time(),
                              ends_at=time.time() + duration_seconds if deadline is not None else None)
            status["phase"] = "rematch"
            publish(output / "demo.json", status)
            play(completed_game + 1)
            if paired_games:
                play(completed_game + 2)
            completed_game += 2 if paired_games else 1
        status["elapsed_seconds"] = time.monotonic() - started
        status["stop_reason"] = "duration_elapsed" if deadline is not None else "game_limit"
        status["games_requested"] = len(status["games"])
        status["phase"] = "complete"
        return status
    except Exception as error:
        status.update(phase="failed", error=str(error))
        raise
    finally:
        publish(output / "demo.json", status)
        for session in sessions:
            if session is not None:
                session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=1800)
    parser.add_argument("--games", type=int, default=None, choices=range(2, 10))
    parser.add_argument("--duration-seconds", type=float, help="Wall-clock training budget; defaults to 600 unless --games is supplied.")
    parser.add_argument("--resume-from", type=Path, help="Carry the same agents’ last played weights into this run.")
    parser.add_argument("--player-1", default="codex:gpt-6-astra")
    parser.add_argument("--player-2", default="claude:claude-opus-5-5")
    parser.add_argument("--reply-timeout", type=float, default=120)
    parser.add_argument("--edit-seconds", type=float, default=240)
    parser.add_argument("--swap-sides", action="store_true", help="Switch characters each game; edit after every game.")
    parser.add_argument("--paired-games", action="store_true", help="With --swap-sides, wait for both assignments before editing.")
    parser.add_argument("--zero-initial", action="store_true", help="Start with zero weights and biases.")
    parser.add_argument("--wait-for-viewer", action="store_true", help="Wait for the browser to finish each game before updating agents.")
    parser.add_argument("--wait-for-start", action="store_true", help="Initialize agents, then wait for Start before gameplay.")
    parser.add_argument("--random-sides", action="store_true", help="Randomly assign characters before each game.")
    args = parser.parse_args()
    print(encode(run_tool_demo(args.output, args.seed, args.max_steps, args.games or 2,
                              [args.player_1, args.player_2], args.reply_timeout, args.edit_seconds, args.swap_sides, args.paired_games,
                              args.duration_seconds if args.duration_seconds is not None else (None if args.games else 600),
                              args.resume_from, prepare_agents=True,
                              zero_initial=args.zero_initial, wait_for_viewer=args.wait_for_viewer, wait_for_start=args.wait_for_start, single_reply=True, random_sides=args.random_sides)))
