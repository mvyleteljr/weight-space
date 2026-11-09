"""Read accepted policies and saved agent context without running inference."""
from pathlib import Path
import json


def current_models(directory, status):
    """Resolve accepted agent policies, never an unsubmitted candidate revision."""
    directory = Path(directory)
    paths = [directory / 'initial.json'] * 2
    for i in range(2):
        initial = directory / f'initial-agent-{i+1}.json'
        if initial.exists():
            paths[i] = initial
    rounds = {r['after_game']: r['agents'] for r in status.get('edit_rounds', [])}
    after = status.get('editing_after_game')
    if after is not None:
        rounds[after] = status['agents']
    for after, agents in sorted(rounds.items()):
        folder = directory if after == 1 else directory / f'edit-{after}'
        for i, agent in enumerate(agents):
            path = folder / f'player-{i+1}.json'
            if agent.get('status') == 'submitted' and path.is_file():
                paths[i] = path
    return paths



def conversation_history(directory, status, agent):
    """Rebuild only this agent's conversation when a finished process is continued."""
    directory = Path(directory)
    records = []
    for entry in sorted(status.get("edit_rounds", []), key=lambda r: r["after_game"]):
        after = entry["after_game"]
        folder = (directory if after == 1 else directory / f"edit-{after}") / f"lab-{agent}"
        prompts = sorted(folder.glob("turn-*.prompt.txt"),
                         key=lambda p: int(p.name.split(".")[0].split("-")[1]))
        for prompt in prompts:
            if ".attempt-" in prompt.name:
                continue
            reply = prompt.with_name(prompt.name.replace(".prompt.txt", ".reply.txt"))
            records.append({"after_game": after, "request": prompt.read_text(),
                            "reply": reply.read_text() if reply.exists() else "No reply received."})
    return json.dumps(records, separators=(",", ":"))
