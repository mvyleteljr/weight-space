"""Replay data, web assets, optional HLS proxy, and an opt-in local launcher.

Use a production HTTPS reverse proxy in front of this server for remote viewers.
The launcher requires a loopback bind and same-origin requests.
"""
import argparse
import gzip
import json
import mimetypes
import os
import re
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen

WEB = Path(__file__).resolve().parent / "web"


class ReplayStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.cache = {}
        self.lock = threading.Lock()
        self.audio_lock = threading.Lock()

    def status(self):
        return json.loads((self.directory / "demo.json").read_text())

    def game(self, number):
        status = self.status()
        entry = next((g for g in status.get("games", []) if g["number"] == number), None)
        if entry is None:
            raise ValueError("This game is not ready.")
        with self.lock:
            if number not in self.cache:
                name = {1: "before", 2: "after"}.get(number, f"game-{number}")
                folder = self.directory / name
                manifest = json.loads((folder / "manifest.json").read_text())
                rows = [json.loads(line) for line in (folder / "steps.jsonl").read_text().splitlines()]
                frames = [row["state"] for row in rows]
                from weight_space.network import load, architecture
                from .policy_activity import recorded_activity
                models = [load(folder/f'player-{player}.json') for player in (1,2)]
                stride = 1  # Keep each diagram decision aligned with its exact rendered game tick.
                activity = recorded_activity(models, rows, stride)
                from Street_Fighter.src.arena import ending_states
                ending = ending_states(frames[-1]) if frames else []
                if ending:
                    frames[-1]["ending_complete"] = False
                    frames.extend(ending)
                self.cache[number] = {"number": number, "player_agents": entry.get("player_agents", [1, 2]),
                                      "fps": manifest["game"]["fps"], "initial_state": manifest["initial_state"],
                                      "frames": frames, "result": entry["result"],
                                      "networks": [architecture(model, include_connections=True) for model in models],
                                      "activity": activity, "activity_stride": stride, "decision_frames": len(rows),
                                      "audio_url": f"/api/games/{number}/audio.wav?run={self.directory.name}"}
            return self.cache[number]

    def audio(self, number):
        from .game_audio import render
        game = self.game(number)
        folder = self.directory / {1: "before", 2: "after"}.get(number, f"game-{number}")
        path = folder / 'spectator-audio-v1.wav'
        with self.audio_lock:
            if not path.exists():
                rows = [json.loads(line) for line in (folder/'steps.jsonl').read_text().splitlines()]
                render(path, rows, len(game['frames'])/game['fps'], game['fps'])
        return path

    def replies(self, after):
        status = self.status()
        allowed = {entry["after_game"] for entry in status.get("edit_rounds", [])}
        if status.get("editing_after_game"):
            allowed.add(status["editing_after_game"])
        if after not in allowed:
            raise ValueError("This edit round is not available.")
        agents = next((entry["agents"] for entry in status.get("edit_rounds", [])
                       if entry["after_game"] == after), status.get("agents", []))
        folder = self.directory if after == 1 else self.directory / f"edit-{after}"
        records = []
        for index, agent in enumerate(agents, 1):
            path = folder / f"lab-{index}" / "replies.json"
            replies = json.loads(path.read_text()) if path.exists() else []
            notes = []
            for entry in replies:
                calls = []
                for call in entry.get("calls", []):
                    result, args = call.get("result"), call.get("arguments", {})
                    item = {"tool": call["tool"], "done": result is not None,
                            "reason": args.get("reason"), "updates": len(args.get("updates", []))}
                    if isinstance(result, dict):
                        item.update({key: result[key] for key in ("error", "revision") if key in result})
                        if "cases" in result:
                            item["tests"] = [{key: case.get(key) for key in
                                              ("action", "expected_action", "matches_expected")} for case in result["cases"]]
                    calls.append(item)
                notes.append({"turn": entry["turn"], "note": entry["note"], "calls": calls})
            records.append({"agent": agent, "replies": notes})
        return {"after_game": after, "agents": records}


    def policy_history(self):
        from weight_space.network import architecture, load
        from weight_space.checkpoint import lab_directories
        status = self.status()
        rounds = sorted({entry["after_game"] for entry in status.get("edit_rounds", [])}
                        | ({status["editing_after_game"]} if status.get("editing_after_game") is not None else set()))
        histories = []
        for index, agent in enumerate(status.get("agents", []), 1):
            snapshots = []
            requests = []
            for after in rounds:
                for attempt, folder in enumerate(lab_directories(self.directory, after, index)):
                    prefix = str(after) if not attempt else f"{after}:recovery-{attempt}"
                    request_path = folder / "context-requests.json"
                    if request_path.exists():
                        requests.extend(json.loads(request_path.read_text()))
                    start = folder / "revision-0.json"
                    if not start.exists():
                        continue
                    round_agents = next((r["agents"] for r in status.get("edit_rounds", []) if r["after_game"] == after), status["agents"])
                    outcome = round_agents[index-1].get("status", "waiting")
                    summaries = {}
                    def summary(revision):
                        if revision not in summaries:
                            path = folder / f"revision-{revision}.json"
                            # Revision files are immutable after publication.
                            cache_key = (str(path), path.stat().st_mtime_ns)
                            with self.lock:
                                if cache_key not in self.cache:
                                    self.cache[cache_key] = architecture(load(path), include_connections=True)
                                summaries[revision] = self.cache[cache_key]
                        return summaries[revision]
                    revision = 0
                    snapshots.append({"id": f"{prefix}:start", "after_game": after, "turn": 0,
                                      "lab_directory": str(folder.relative_to(self.directory)), "revision": 0, "architecture": summary(0), "stage": "starting policy",
                                      "note": "Policy carried into this editing round.", "calls": []})
                    path = folder / "replies.json"
                    replies = json.loads(path.read_text()) if path.exists() else []
                    for reply in replies:
                        calls = reply.get("calls", [])
                        for ci, call in enumerate(calls or [{}]):
                            result = call.get("result") or {}
                            result = result if isinstance(result, dict) else {}
                            value = result.get("revision")
                            if type(value) is int and value >= 0 and (folder / f"revision-{value}.json").exists():
                                revision = value
                            tool = call.get("tool", "reply")
                            stage = "candidate"
                            if tool == "submit" and result and "error" not in result:
                                stage = "submitted"
                            elif tool in ("test_inputs", "test_sequence") and "cases" in result:
                                stage = "tested candidate"
                            if outcome in ("kept_previous", "failed", "stopped") and stage != "submitted":
                                stage = "not adopted" if revision else "starting policy"
                            args = call.get("arguments", {})
                            snapshots.append({"id": f"{prefix}:{reply['turn']}:{ci}", "after_game": after,
                                "lab_directory": str(folder.relative_to(self.directory)), "turn": reply["turn"], "revision": revision, "architecture": summary(revision),
                                "stage": stage, "note": reply.get("note", ""),
                                "calls": [{"tool": tool, "reason": args.get("reason"),
                                           "updates": len(args.get("updates", [])), "error": result.get("error"),
                                           "done": call.get("result") is not None,
                                           "tests": [{key: c.get(key) for key in ("action", "expected_action", "matches_expected")}
                                                     for c in result.get("cases", [])]}]})
            if not snapshots:
                path = self.directory / f"initial-agent-{index}.json"
                if not path.exists():
                    path = self.directory / "initial.json"
                if path.exists():
                    snapshots.append({"id": "initial", "after_game": 0, "turn": 0, "revision": 0,
                        "architecture": architecture(load(path), include_connections=True), "stage": "starting policy",
                        "note": "Zeroed policy. Initializing agents.", "calls": []})
            histories.append({"agent": agent, "snapshots": snapshots, "context_requests": requests})
        return {"agents": histories}

    def policy_model(self, agent_index, snapshot_id):
        """Resolve a displayed snapshot, never a browser-supplied file path."""
        if type(agent_index) is not int or agent_index not in (0, 1) or not isinstance(snapshot_id, str):
            raise ValueError('Invalid policy selection.')
        histories = self.policy_history()['agents']
        if agent_index >= len(histories):
            raise ValueError('Unknown agent.')
        snapshot = next((s for s in histories[agent_index]['snapshots'] if s['id'] == snapshot_id), None)
        if snapshot is None:
            raise ValueError('Unknown policy revision.')
        if snapshot['id'] == 'initial':
            path = self.directory / f'initial-agent-{agent_index+1}.json'
            if not path.exists():
                path = self.directory / 'initial.json'
        else:
            after = snapshot['after_game']
            folder = self.directory if after == 1 else self.directory / f'edit-{after}'
            lab = self.directory / snapshot["lab_directory"] if "lab_directory" in snapshot else folder / f'lab-{agent_index+1}'
            path = lab / f'revision-{snapshot["revision"]}.json'
        from weight_space.network import load
        return load(path)


class SpectatorHandler(BaseHTTPRequestHandler):
    def send_audio(self, path):
        size = path.stat().st_size
        start, end = 0, size-1
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
            if not match or not any(match.groups()):
                self.send_error(416)
                return
            first, last = match.groups()
            if first:
                start, end = int(first), min(size-1, int(last)) if last else size-1
            else:
                start = max(0, size-int(last))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
        self.send_response(206 if requested else 200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(end-start+1))
        if requested:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as audio:
            audio.seek(start)
            remaining = end-start+1
            while remaining:
                chunk = audio.read(min(65536, remaining))
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def send_json(self, value):
        body = json.dumps(value, allow_nan=False).encode()
        compressed = len(body) > 4096 and 'gzip' in self.headers.get('Accept-Encoding', '')
        if compressed:
            body = gzip.compress(body, compresslevel=1)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header('Vary', 'Accept-Encoding')
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            manager = getattr(self.server, "run_manager", None)
            if manager:
                if urlsplit("http://" + self.headers.get("Host", "")).hostname not in ("127.0.0.1", "localhost", "::1"):
                    self.send_error(403)
                    return
                if manager.directory and (self.server.replay_store is None or self.server.replay_store.directory != manager.directory):
                    self.server.replay_store = ReplayStore(manager.directory)
                if path == "/api/autoplay/audio.wav":
                    query = parse_qs(urlsplit(self.path).query)
                    session = manager.autoplay
                    if session is None or query.get('session', [''])[0] != session.id:
                        self.send_error(409, 'Autoplay has stopped')
                        return
                    try:
                        self.send_audio(session.store.audio(int(query.get('game', ['0'])[0])))
                    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
                        self.send_error(404, 'Autoplay audio unavailable')
                    return
                if path == "/api/run":
                    from Street_Fighter.src.arena import Arena
                    self.send_json({"initial_state": Arena(max_steps=1800).state(), "run": manager.directory.name if manager.directory else None,
                                    "demo": manager.status(), "can_start": manager.can_start(), "run_token": manager.token})
                    return
            store = getattr(self.server, "replay_store", None)
            if store is None:
                self.send_error(404, "No replay run is configured")
                return
            try:
                if path == "/api/run":
                    self.send_json({"run": store.directory.name, "demo": store.status(), "can_start": False})
                elif re.fullmatch(r"/api/games/[1-9][0-9]{0,4}", path):
                    self.send_json(store.game(int(path.rsplit("/", 1)[1])))
                elif re.fullmatch(r"/api/games/[1-9][0-9]{0,4}/audio.wav", path):
                    query = parse_qs(urlsplit(self.path).query)
                    if query.get('run', [''])[0] != store.directory.name:
                        self.send_error(409, 'This is not the current run')
                        return
                    try:
                        self.send_audio(store.audio(int(path.split('/')[3])))
                    except (RuntimeError, OSError, subprocess.SubprocessError):
                        self.send_error(503, 'Game audio unavailable; check FFmpeg and audio assets')
                elif path == "/api/policy-history":
                    self.send_json(store.policy_history() if (store.directory / "demo.json").exists() else {"agents": []})
                elif path == "/api/replies":
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(store.replies(int(query.get("after", ["0"])[0])))
                else:
                    self.send_error(404)
            except (ValueError, FileNotFoundError):
                self.send_error(404, "Replay data is not ready")
            return
        assets = {"/assets/background.jpg": "bg1.jpg", "/assets/grimes-sprites-large.png": "grimes-sprites-large.png",
                  "/assets/shoggoth-sprites-large.png": "shoggoth-sprites-large.png"}
        if path in assets:
            asset = self.server.assets_root / assets[path]
            # Keep the public URL stable; prefer an optional animated background.
            if path == "/assets/background.jpg":
                animated = self.server.assets_root / "anthropic-church-animated-1000x600.apng"
                if animated.is_file():
                    asset = animated
            if not asset.is_file():
                self.send_error(404)
                return
            body = asset.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png" if asset.suffix == ".apng" else mimetypes.guess_type(asset.name)[0])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/live/"):
            # Fixed upstream; no user-provided hostname or open proxy.
            target = self.server.hls_origin + self.path[len("/live"):]
            request = Request(target, headers={"Range": self.headers.get("Range", "")})
            try:
                with urlopen(request, timeout=10) as response:
                    body = response.read()
                    self.send_response(response.status)
                    for key in ("Content-Type", "Content-Range", "Accept-Ranges"):
                        if response.headers.get(key):
                            self.send_header(key, response.headers[key])
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            except HTTPError as error:
                self.send_error(error.code, "Stream is not ready")
            except (URLError, TimeoutError, OSError):
                self.send_error(503, "Stream is reconnecting")
            return
        filename = {"/": "index.html", "/app.js": "app.js", "/audio.js": "audio.js", "/status.js": "status.js", "/network.js": "network.js", "/style.css": "style.css"}.get(path)
        if filename is None:
            self.send_error(404)
            return
        body = (WEB / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        manager = getattr(self.server, "run_manager", None)
        if self.path not in ("/api/runs", "/api/reset", "/api/game-finished", "/api/pause", "/api/resume", "/api/autoplay", "/api/autoplay-next", "/api/autoplay-policies", "/api/autoplay-stop") or manager is None:
            self.send_error(403, "Run creation is not enabled")
            return
        from streaming.run_control import RunBusyError
        host = self.headers.get("Host", "")
        if (urlsplit("http://" + host).hostname not in ("127.0.0.1", "localhost", "::1")
                or self.headers.get("Origin") != "http://" + host
                or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
                or not secrets.compare_digest(self.headers.get("X-Run-Token", ""), manager.token)):
            self.send_error(403, "Use the local frontend to start a run")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Invalid request size.")
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/autoplay-stop':
                if (not isinstance(body, dict) or set(body) != {'session'}
                        or not isinstance(body['session'], str) or not 1 <= len(body['session']) <= 100):
                    raise ValueError('Supply the autoplay session.')
                manager.stop_autoplay(body['session'])
                self.send_json({'ok': True})
                return
            if self.path == '/api/autoplay-policies':
                if not isinstance(body, dict) or set(body) != {'session', 'after', 'policies'}:
                    raise ValueError('Supply the autoplay session, previous game, and policy selections.')
                if not isinstance(body['policies'], list) or len(body['policies']) != 2 or any(
                    p is not None and (not isinstance(p, str) or len(p) > 100) for p in body['policies']
                ):
                    raise ValueError('Supply two policy selections.')
                self.send_json(manager.autoplay_game(body['session'], body['after'], body['policies']))
                return
            if self.path == "/api/autoplay-next":
                if not isinstance(body, dict) or set(body) != {'session', 'after'}:
                    raise ValueError('Supply the autoplay session and previous game.')
                self.send_json(manager.autoplay_game(body['session'], body['after']))
                return
            if self.path == "/api/autoplay":
                if body != {}:
                    raise ValueError('No options are required.')
                self.send_json(manager.autoplay_game())
                return
            if self.path == "/api/game-finished":
                if not isinstance(body, dict) or set(body) != {"run", "game"}:
                    raise ValueError("Supply the run and game.")
                manager.game_finished(body["run"], body["game"])
                self.send_json({"ok": True})
                return
            if body != {}:
                raise ValueError("No options are required.")
            if self.path in ("/api/pause", "/api/resume"):
                directory = manager.pause(self.path == "/api/pause")
            else:
                directory = manager.reset() if self.path == "/api/reset" else manager.start()
            self.server.replay_store = ReplayStore(directory)
            self.send_json({"run": directory.name})
        except RunBusyError as error:
            self.send_error(409, str(error))
        except (ValueError, OSError) as error:
            self.send_error(400, str(error))

    def log_message(self, format, *args):
        # HLS makes frequent requests; leave success logs quiet.
        if len(args) > 1 and str(args[1]) not in ("200", "206", "304"):
            super().log_message(format, *args)


def configure_runs(server, repo, *, allow_new_runs=False, demo=None):
    """Reopen the selected training run; --demo remains a read-only selector."""
    server.run_manager = None
    if allow_new_runs:
        from streaming.run_control import RunManager
        server.run_manager = RunManager.reopen(repo)
        server.replay_store = ReplayStore(server.run_manager.directory)
    else:
        server.replay_store = ReplayStore(demo) if demo else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--hls-origin", default="http://127.0.0.1:8888")
    parser.add_argument("--demo", type=Path, default=os.environ.get("WEIGHT_SPACE_DEMO"),
                        help="Saved run for read-only viewing; ignored with --allow-new-runs.")
    parser.add_argument("--assets", type=Path, default=WEB.parent.parent / "Street_Fighter/assets/images")
    parser.add_argument("--allow-new-runs", action="store_true", help="Restore saved training and enable local controls; Reset starts fresh.")
    args = parser.parse_args()
    if args.allow_new_runs and args.bind not in ("127.0.0.1", "localhost"):
        parser.error("Run creation requires a loopback bind address.")
    origin = urlsplit(args.hls_origin)
    if origin.scheme not in ("http", "https") or not origin.hostname or origin.path not in ("", "/"):
        parser.error("--hls-origin must be an HTTP(S) origin without a path")
    server = ThreadingHTTPServer((args.bind, args.port), SpectatorHandler)
    server.hls_origin = args.hls_origin.rstrip("/")
    server.assets_root = args.assets.resolve()
    if args.allow_new_runs:
        # Host execution preserves the CLI subscription login; no credentials enter Docker or the browser.
        import sys
        sys.path.insert(0, str(WEB.parent.parent))
    configure_runs(server, WEB.parent.parent, allow_new_runs=args.allow_new_runs, demo=args.demo)
    print(f"Spectator page: http://{args.bind}:{args.port}", flush=True)
    import signal
    def stop_server(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if server.run_manager is not None:
            server.run_manager.close()
