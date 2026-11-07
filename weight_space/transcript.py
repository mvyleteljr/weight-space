"""Read public reply notes and tool results for the viewer. No provider calls."""

import json
from pathlib import Path
from .tool_loop import parse_calls


def read_replies(directory):
    directory = Path(directory)
    path = directory / "replies.json"
    if path.exists():
        return json.loads(path.read_text())
    # Older runs already saved complete replies. Show them without rerunning agents.
    replies = []
    events_path = directory / "tools.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
    cursor = 0
    for path in sorted(directory.glob("turn-*.reply.txt"), key=lambda p: int(p.name.split("-")[1].split(".")[0])):
        turn = int(path.name.split("-")[1].split(".")[0])
        text = path.read_text().strip()
        if text.startswith("```") and text.splitlines()[-1].strip() == "```":
            text = "\n".join(text.splitlines()[1:-1])
        try:
            packet = parse_calls(text)
            calls = []
            for call in packet["calls"]:
                if not isinstance(call, dict) or not isinstance(call.get("arguments"), dict):
                    continue
                result = None
                if cursor < len(events) and events[cursor]["tool"] == call.get("tool") \
                        and events[cursor]["arguments"] == call["arguments"]:
                    result = events[cursor]["result"]
                    cursor += 1
                calls.append({**call, "result": result})
            replies.append({"turn": turn,
                            "note": packet.get("note", ""), "calls": calls})
        except (ValueError, TypeError) as error:
            replies.append({"turn": turn, "note": "Reply format error: " + str(error), "calls": []})
    return replies


def reply_lines(replies):
    lines = []
    for entry in replies:
        lines.append(f"Reply {entry['turn']}: {entry['note']}")
        for call in entry["calls"]:
            tool, args, result = call["tool"], call["arguments"], call.get("result")
            if isinstance(result, dict) and "error" in result:
                detail = "ERROR: " + result["error"]
            elif tool == "test_inputs" and isinstance(result, dict):
                cases = result.get("cases", [])
                checked = [case for case in cases if case.get("matches_expected") is not None]
                detail = f"{len(cases)} inputs; {sum(c['matches_expected'] for c in checked)}/{len(checked)} expected actions matched"
            elif tool == "edit_weights":
                detail = f"{len(args.get('updates', []))} values set" + ("; reset all first" if args.get("zero_all") else "")
            elif tool == "submit":
                detail = args.get("reason", "")
            elif tool == "read_steps":
                detail = f"from step {args.get('start')}; count {args.get('count', 3)}; stride {args.get('stride', 1)}"
            elif tool == "inspect_step":
                detail = f"step {args.get('step')}; activations and scores"
            else:
                detail = "complete" if result is not None else "requested"
            if result is None and tool in ("edit_weights", "submit", "read_steps", "inspect_step"):
                detail += " (requested)"
            lines.append(f"  {tool}: {detail}")
        lines.append("")
    return lines
