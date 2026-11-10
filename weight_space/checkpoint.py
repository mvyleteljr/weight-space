"""Read accepted policies and saved agent context without running inference."""
from pathlib import Path
import json
from contextlib import contextmanager
import fcntl


@contextmanager
def training_lock(directory):
    directory = Path(directory).resolve()
    locks = directory.parent / '.training-locks'
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / (directory.name + '.lock')).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This run still has an active trainer; stop it before restarting.') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def lab_directories(directory, after, agent):
    """Include interrupted initialization attempts without overwriting their logs."""
    base = Path(directory) if after == 1 else Path(directory) / f'edit-{after}'
    first = base / f'lab-{agent}'
    return ([first] if first.exists() else []) + sorted(
        base.glob(f'lab-{agent}-recovery-*'), key=lambda p: int(p.name.rsplit('-', 1)[1]))


def editing_rounds(status):
    rounds = {entry['after_game']: entry['agents'] for entry in status.get('edit_rounds', [])}
    after = status.get('editing_after_game')
    if after is not None:
        rounds[after] = status['agents']
    return rounds


def current_models(directory, status, *, recover=False):
    """Resolve accepted agent policies, never an unsubmitted candidate revision."""
    directory = Path(directory)
    paths = [directory / 'initial.json'] * 2
    for i in range(2):
        initial = directory / f'initial-agent-{i+1}.json'
        if initial.exists():
            paths[i] = initial
    rounds = editing_rounds(status)
    for after, agents in sorted(rounds.items()):
        folder = directory if after == 1 else directory / f'edit-{after}'
        for i, agent in enumerate(agents):
            path = folder / f'player-{i+1}.json'
            if agent.get('status') == 'submitted' and path.is_file():
                paths[i] = path
            # A process can stop between writing a submission and publishing status.
            for lab in lab_directories(directory, after, i + 1) if recover else []:
                if (lab / 'submitted.json').exists() and (lab / 'submission.json').exists():
                    paths[i] = lab / 'submitted.json'
    return paths



def conversation_history(directory, status, agent):
    """Rebuild only this agent's conversation, including an interrupted update."""
    directory = Path(directory)
    records = []
    for after in sorted(editing_rounds(status)):
        for folder in lab_directories(directory, after, agent):
            prompts = sorted(folder.glob("turn-*.prompt.txt"),
                             key=lambda p: int(p.name.split(".")[0].split("-")[1]))
            for prompt in prompts:
                if ".attempt-" in prompt.name:
                    continue
                reply = prompt.with_name(prompt.name.replace(".prompt.txt", ".reply.txt"))
                records.append({"after_game": after, "request": prompt.read_text(),
                                "reply": reply.read_text() if reply.exists() else "No reply received."})
    return json.dumps(records, separators=(",", ":"))
