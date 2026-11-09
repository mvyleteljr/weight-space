"""Fixed local launcher for Astra versus Opus 5.5. No browser-supplied commands."""

from datetime import datetime, timezone
import json
import os
import signal
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
        self.autoplay = None
        self.continuing = False
        if initial is None:
            self._ready()

    def _ready(self):
        from weight_space.network import initialize, save
        self.continuing = False
        name = "ready-" + secrets.token_hex(6)
        self.directory = self.runs / name
        self.directory.mkdir()
        save(self.directory / "initial.json", initialize([33, 8, 18], zero=True))
        self.placeholder = {"phase": "ready", "games": [], "edit_rounds": [],
                            "tally": {"wins": [0, 0], "draws": 0, "games": 0},
                            "agents": [{"name": "Astra", "status": "ready"},
                                       {"name": "Opus 5.5", "status": "ready"}]}
        (self.directory / "demo.json").write_text(json.dumps(self.placeholder))
        return self.directory

    def reset(self):
        with self.lock:
            self.autoplay = None
            # Reset discards the run; it never applies pending environment requests.
            if self.process is not None and self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
            previous = self.directory
            status = self.status()
            if previous and status and status.get("phase") not in ("complete", "awaiting_approval"):
                status.update(phase="stopped", stop_reason="reset")
                status.pop("error", None)
                previous.mkdir(exist_ok=True)
                (previous / "demo.json").write_text(json.dumps(status))
            self.process = None
            self._ready()
        return self.prepare()

    def pause(self, paused):
        with self.lock:
            if not self.directory or not self.process or self.process.poll() is not None:
                raise RunBusyError("No active run.")
            marker = self.directory / "paused"
            if paused:
                marker.touch()
            else:
                self.autoplay = None
                marker.unlink(missing_ok=True)
            return self.directory

    def autoplay_game(self, session=None, after=0, policies=None):
        from streaming.autoplay import Autoplay
        with self.lock:
            status = self.status() or {}
            if status.get('phase') != 'complete' and (not status.get('paused') or status.get('phase') not in ('playing', 'editing', 'rematch')):
                raise RunBusyError('Pause training before starting autoplay.')
            if session is None:
                if policies is not None:
                    raise RunBusyError('Start autoplay before selecting a policy.')
                self.autoplay = Autoplay(self.directory, status)
                return self.autoplay.next(0)
            if self.autoplay is None or session != self.autoplay.id:
                raise RunBusyError('Autoplay has stopped.')
            return self.autoplay.next(after, policies)

    def stop_autoplay(self, session):
        with self.lock:
            if self.autoplay is not None and self.autoplay.id == session:
                self.autoplay = None

    def game_finished(self, run, number):
        with self.lock:
            if not self.directory or run != self.directory.name:
                raise ValueError("This is not the current run.")
            status = self.status() or {}
            if (type(number) is not int or status.get("phase") != "playing"
                    or status.get("viewing_game") != number):
                raise ValueError("This game is not being shown.")
            # A separate marker avoids racing the trainer's atomic status writes.
            (self.directory / f"viewed-{number}").touch()

    def status(self):
        if self.directory:
            try:
                status = json.loads((self.directory / "demo.json").read_text())
                if self.continuing:
                    if status.get('phase') != 'complete':
                        self.continuing = False
                    elif self.process is not None and self.process.poll() is None:
                        status['phase'] = 'editing'
                status["paused"] = (self.directory / "paused").exists()
                return status
            except FileNotFoundError:
                pass
        return self.placeholder

    def active(self):
        if (self.status() or {}).get("phase") == "awaiting_approval":
            return True  # A new run must not bypass the pending user decision.
        if self.process is not None:
            return self.process.poll() is None
        status = self.status()
        return bool(status and status.get("phase") not in ("ready", "complete", "failed", "stopped", "awaiting_approval"))

    def start(self):
        with self.lock:
            self.autoplay = None
            status = self.status() or {}
            if status.get('phase') == 'complete':
                return self._continue(status)
            if (self.status() or {}).get("phase") != "ready" or self.process is None or self.process.poll() is not None:
                raise RunBusyError("Initial policies are not ready.")
            (self.directory / "start").touch()
            return self.directory

    def can_start(self):
        status = self.status() or {}
        if status.get('phase') == 'complete':
            return bool(status.get('games')) and (self.process is None or self.process.poll() is not None)
        return status.get('phase') == 'ready' and self.process is not None and self.process.poll() is None

    def _continue(self, status):
        if not self.can_start():
            raise RunBusyError('The trainer is still finishing.')
        uv = shutil.which('uv')
        if uv is None:
            raise ValueError('uv is unavailable on the host.')
        command = [uv, 'run', '--project', str(self.repo), 'python', '-m', 'weight_space.tool_loop',
                   '--output', str(self.directory), '--continue-run', '--duration-seconds', '600', '--wait-for-viewer']
        logs = self.runs / '.launcher-logs'
        logs.mkdir(exist_ok=True)
        (self.directory / 'paused').unlink(missing_ok=True)
        with (logs / f'{self.directory.name}.log').open('a') as log:
            self.process = subprocess.Popen(command, cwd=self.repo, stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.continuing = True
        threading.Thread(target=self._watch, args=(self.process, self.directory, status), daemon=True).start()
        return self.directory

    def prepare(self, games=6):
        if type(games) is not int or not 2 <= games <= 9:
            raise ValueError("Choose 2 to 9 games.")
        with self.lock:
            if self.active():
                raise RunBusyError("A run is already active.")
            uv = shutil.which("uv")
            if uv is None:
                raise ValueError("uv is unavailable on the host.")
            name = "astra-opus-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
            directory = self.runs / name
            seed = secrets.randbits(63)
            command = [uv, "run", "--project", str(self.repo), "python", "-m", "weight_space.tool_loop",
                       "--output", str(directory), "--seed", str(seed), "--duration-seconds", "600",
                       "--zero-initial", "--wait-for-viewer", "--wait-for-start", "--random-sides", "--player-1", "codex:gpt-6-astra", "--player-2", "claude:claude-opus-5-5"]
            logs = self.runs / ".launcher-logs"
            logs.mkdir(exist_ok=True)
            with (logs / f"{name}.log").open("w") as log:
                process = subprocess.Popen(command, cwd=self.repo, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            self.process, self.directory = process, directory
            self.continuing = False
            self.placeholder = {"phase": "initializing", "seed": seed, "games_requested": games,
                                "games": [], "edit_rounds": [], "swap_sides": False, "random_sides": True, "paired_games": False,
                                "tally": {"wins": [0, 0], "draws": 0, "games": 0},
                                "agents": [{"name": "Astra", "status": "waiting"}, {"name": "Opus 5.5", "status": "waiting"}]}
            temporary = self.pointer.with_suffix(".tmp")
            temporary.write_text(json.dumps({"run": name, "seed": seed, "games": games}))
            temporary.replace(self.pointer)
            threading.Thread(target=self._watch, args=(process, directory, self.placeholder), daemon=True).start()
            return directory

    def _watch(self, process, directory, placeholder):
        code = process.wait()
        with self.lock:
            if process is not self.process:
                return
            path = directory / "demo.json"
            status = json.loads(path.read_text()) if path.exists() else dict(placeholder)
            if status.get("phase") not in ("complete", "failed", "stopped", "awaiting_approval"):
                status.update(phase="failed", error=f"The experiment process ended before completion (exit {code}).")
                directory.mkdir(exist_ok=True)
                temporary = directory / "demo.tmp"
                temporary.write_text(json.dumps(status))
                temporary.replace(path)
