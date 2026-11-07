"""Fixed local launcher for Astra versus Fable. No browser-supplied commands."""

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import threading


class RunBusyError(Exception):
    pass


class RunManager:
    def __init__(self, repo, initial=None):
        self.repo = Path(repo).resolve()
        self.runs = self.repo / "runs"
        self.runs.mkdir(exist_ok=True)
        self.pointer = self.runs / ".frontend-current.json"
        self.directory = Path(initial).resolve() if initial else None
        self.process = None
        self.lock = threading.Lock()
        self.placeholder = None
        self.token = secrets.token_urlsafe(32)
        if initial is None and self.pointer.exists():
            name = json.loads(self.pointer.read_text())["run"]
            if Path(name).name != name or name in (".", ".."):
                raise ValueError("Invalid saved run name.")
            self.directory = self.runs / name

    def status(self):
        if self.directory:
            try:
                return json.loads((self.directory / "demo.json").read_text())
            except FileNotFoundError:
                pass
        return self.placeholder

    def active(self):
        if self.process is not None:
            return self.process.poll() is None
        status = self.status()
        return bool(status and status.get("phase") not in ("complete", "failed"))

    def start(self, games=6):
        if type(games) is not int or not 2 <= games <= 9:
            raise ValueError("Choose 2 to 9 games.")
        with self.lock:
            if self.active():
                raise RunBusyError("A run is already active.")
            uv = shutil.which("uv")
            if uv is None:
                raise ValueError("uv is unavailable on the host.")
            name = "astra-fable-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
            directory = self.runs / name
            seed = secrets.randbits(63)
            command = [uv, "run", "--project", str(self.repo), "python", "-m", "weight_space.tool_loop",
                       "--output", str(directory), "--seed", str(seed), "--games", str(games),
                       "--swap-sides", "--player-1", "codex:gpt-6-astra", "--player-2", "claude:fable"]
            logs = self.runs / ".launcher-logs"
            logs.mkdir(exist_ok=True)
            with (logs / f"{name}.log").open("w") as log:
                process = subprocess.Popen(command, cwd=self.repo, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            self.process, self.directory = process, directory
            self.placeholder = {"phase": "initializing", "seed": seed, "games_requested": games,
                                "games": [], "edit_rounds": [], "swap_sides": True, "paired_games": False,
                                "tally": {"wins": [0, 0], "draws": 0, "games": 0},
                                "agents": [{"name": "Astra", "status": "waiting"}, {"name": "Fable", "status": "waiting"}]}
            temporary = self.pointer.with_suffix(".tmp")
            temporary.write_text(json.dumps({"run": name, "seed": seed, "games": games}))
            temporary.replace(self.pointer)
            threading.Thread(target=self._watch, args=(process, directory, self.placeholder), daemon=True).start()
            return directory

    def _watch(self, process, directory, placeholder):
        code = process.wait()
        path = directory / "demo.json"
        status = json.loads(path.read_text()) if path.exists() else dict(placeholder)
        if status.get("phase") not in ("complete", "failed"):
            status.update(phase="failed", error=f"The experiment process ended before completion (exit {code}).")
            directory.mkdir(exist_ok=True)
            temporary = directory / "demo.tmp"
            temporary.write_text(json.dumps(status))
            temporary.replace(path)
