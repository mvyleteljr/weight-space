# HLS spectators

The main broadcast source is the **weight-editing viewer**. It renders recorded
network matches and agent-edit progress while providers run separately. One
FFmpeg process encodes the rendered output, and MediaMTX shares
that video with all spectators. Default output is video-only H.264 at 30 FPS,
with dimensions fitted inside 1280×720 (no upscaling, even pixels, aspect ratio
preserved within rounding). Local keyboard play is still the default.

## Broadcast weight-editing runs (primary workflow)

Run from the repository root after installing FFmpeg and starting Docker:

```sh
docker compose -f streaming/compose.yml up -d
uv run --no-project --python 3.13 --with pygame==2.6.1 python -m weight_space.viewer \
  --demo runs/YOUR_WEIGHT_EDITING_RUN --stream rtsp://127.0.0.1:8554/match-1
```

Open http://127.0.0.1:8080. This follows the run's game 1 → editing → game 2
presentation, with recorded matches replayed at game speed. Add `--headless` to
render on a server without a desktop; omit `--paused` for automatic progression.
The full viewer, including progress panels, is fitted to 922×720. It makes no
provider calls and doesn't modify models. See the root README for starting the
weight-editing workflow. There is one shared Arena engine, not a separate game.

## Start the optional keyboard/scripted game with Docker

Requirements: Python 3.12, FFmpeg with `libx264`, and a running Docker daemon.
Commands below run from the **weight-space repository root**.

```bash
python3 -m venv Street_Fighter/.venv
Street_Fighter/.venv/bin/python -m pip install -r Street_Fighter/docs/requirements.txt
docker compose -f streaming/compose.yml up -d
Street_Fighter/.venv/bin/python Street_Fighter/src/main.py --stream rtsp://127.0.0.1:8554/match-1
```

Open **http://127.0.0.1:8080**. Click Start Game in the desktop game window.
P1 uses A/D, W, R/T; P2 uses left/right, up, K/L. Spectators cannot control players.
The video contains menus, countdowns, gameplay and victory screens.

For a continuous demonstration without a window or an audio device:

```bash
Street_Fighter/.venv/bin/python Street_Fighter/src/main.py \
  --headless --demo --mute --stream rtsp://127.0.0.1:8554/match-1
```

`--demo` is a deterministic input script, **not AI inference**. It is visibly
labeled in the video. Do not run two publishers on the same match path; MediaMTX
rejects the second publisher. Stop the first game before switching modes.

Stop the game with Ctrl+C in its terminal, then stop services:

```bash
docker compose -f streaming/compose.yml down
```

## Without Docker

Download [MediaMTX v1.21.3](https://github.com/bluenviron/mediamtx/releases/tag/v1.21.3)
for your OS/architecture and verify the release checksum. Run these in separate
terminals, from the repository root:

```bash
# Terminal 1 (replace mediamtx with the downloaded executable path):
mediamtx streaming/mediamtx.yml

# Terminal 2:
python3 streaming/server.py

# Terminal 3:
Street_Fighter/.venv/bin/python Street_Fighter/src/main.py \
  --stream rtsp://127.0.0.1:8554/match-1
```

On the development machine used for initial verification the downloaded binary
is `/tmp/weight-space-mediamtx/mediamtx`; it is temporary and isn't in Git.
The frame writer uses POSIX pipes and currently supports macOS and Linux.

## What is running

```text
Pygame (60 FPS target)
  -> RGB copy, at most 60 FPS, resized only when necessary
  -> one pending frame (newest replaces old)
  -> paced worker, 30 FPS
  -> FFmpeg: H.264 / yuv420p / 2-second keyframes / no audio
  -> local RTSP over TCP :8554
  -> MediaMTX: regular fMP4 HLS, 2-second segments
  -> same-origin HTTP proxy + spectator page :8080
  -> embedded MediaMTX HLS player
```

Regular HLS deliberately buffers playback. Expect roughly 6–10 seconds of delay
including buffering and segment formation, with variation by browser and network;
this is not a measured external latency guarantee. Initial startup may also take
several seconds. HLS retains seven segments in memory. `hlsAlwaysRemux` prepares
segments before the first viewer arrives.

The frame writer has a 500 ms deadline. A stalled encoder is terminated and retried
after two seconds without stopping the game. The worker repeats the last image if
rendering pauses, and skips missed deadlines after major stalls rather than sending
an unlimited catch-up burst. A partial pipe write causes an encoder restart so RGB
frames never become misaligned. SIGINT/SIGTERM and normal exits clean up FFmpeg.

A single pending frame plus the worker's current frame bounds Python frame storage.
The OS pipe and FFmpeg also have their own buffers. No viewer starts an encoder or
another game. Frame replacements are expected: the game targets 60 FPS while the
stream sends 30. `repeats` indicates an output tick without a fresh captured frame.

Logs every ten seconds show render/feed FPS, average/max copy time, replaced
frames, repeated frames and encoder restarts. Feed FPS measures writes into FFmpeg;
use ffprobe and the browser to verify encoded output and playback separately.

## Multiple matches and 60 FPS

Publish each additional game to a distinct path, such as `match-2`, and open
`http://127.0.0.1:8080/?match=match-2`. Each match needs its own game and encoder.

Use `--stream-fps 60` to experiment with 60 FPS. The rendering loop still targets
60 FPS; measure actual rendering, encoding and browser frame drops on the intended
server before using that mode. `--size 1024x768` overrides the game window size;
the stream then becomes 960×720. `--mute` mutes host audio; streams always omit audio.

## External viewers

Local defaults bind ports to loopback. This implementation has **not yet been
verified over an external network or under real AI-agent load**.

For a trusted LAN test without Docker, start the spectator server with
`python3 streaming/server.py --bind 0.0.0.0` and visit `http://HOST_LAN_IP:8080`
from another device. With Docker, explicitly change only the spectator port mapping
to `0.0.0.0:8080:8080`. Keep the RTSP publisher and MediaMTX HLS ports private.

For Internet viewing, place an HTTPS reverse proxy in front of port 8080. Proxy
both `/` and `/live/` to this server, disable proxy buffering/caching for the live
routes, and apply whatever spectator access policy the event requires. The player
uses relative same-origin URLs, so external browsers never try to connect to their
own localhost. Do not expose :8554 or :8888 publicly; these local development
services have anonymous publishing/reading. No public deployment is configured.

An external acceptance test should run for at least ten minutes with both real
agents producing actions: measure render/feed FPS, repeated frames, browser dropped
frames/buffer stalls, stream latency and outbound bandwidth at the expected viewer
count. The encoder targets 2.5 Mbps (3 Mbps max); budget approximately that bandwidth
per viewer plus protocol overhead, and measure rather than assume server capacity.
Slow AI inference must run in separate processes and publish only its latest action;
never call a remote model synchronously inside `game_loop()` or `Fighter.move()`.
The weight-editing provider workflow is present, but real provider load and external-network streaming still need an acceptance test.

## Verification

```bash
Street_Fighter/.venv/bin/python -m unittest discover -s Street_Fighter/tests -v
Street_Fighter/.venv/bin/python streaming/smoke_test.py --mediamtx /path/to/mediamtx
```

The smoke test starts temporary services on separate loopback ports, decodes six
seconds with two simultaneous readers, restarts MediaMTX while the game continues,
and verifies HLS decoding resumes. It leaves logs/results in a printed temporary
directory and stops its own processes. It does not interrupt an existing match.

The player exposes a **Stream available** indicator based on playlist availability,
not a claim that playback has started; use the video controls or Reconnect player
if browser autoplay is blocked. The standard MediaMTX player handles reconnecting.

## References

- [MediaMTX browser and iframe playback](https://mediamtx.org/docs/read/web-browsers)
- [MediaMTX FFmpeg publishing](https://mediamtx.org/docs/publish/ffmpeg)
- [MediaMTX configuration](https://mediamtx.org/docs/references/configuration-file)
- [Pygame surface-to-bytes conversion](https://www.pygame.org/docs/ref/image.html#pygame.image.tobytes)

To exercise the primary weight-editing viewer with generated before/after model
fixtures (without provider calls), run:

```sh
Street_Fighter/.venv/bin/python streaming/smoke_test.py \
  --mediamtx /path/to/mediamtx --source viewer
```

This checks 922×720 output, two readers, and recovery through the same HLS path.
The fixture uses explicit test weights; it is not evidence of real agent performance.
