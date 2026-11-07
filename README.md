# Weight Space

## Street Fighter

Local two-player fighting game, adapted from [geekcomputers/Python](https://github.com/geekcomputers/Python/tree/master/Street_Fighter).

```bash
cd Street_Fighter
python3 -m venv .venv
.venv/bin/python -m pip install -r docs/requirements.txt
.venv/bin/python src/main.py
```

Player 1: A/D to move, W to jump, R/T to attack.
Player 2: left/right arrows to move, up arrow to jump, K/L to attack.

OpenCV's headless package handles image processing while Pygame provides the window.
See `Street_Fighter/LICENSE` and `Street_Fighter/UPSTREAM_LICENSE.md` for license notices.

## Watch a match in the browser

Start MediaMTX and the spectator server, then launch the game with streaming:

```bash
docker compose -f streaming/compose.yml up -d
Street_Fighter/.venv/bin/python Street_Fighter/src/main.py --stream rtsp://127.0.0.1:8554/match-1
```

Open **http://127.0.0.1:8080**. Requires a running Docker daemon and FFmpeg on the
host. The stream is silent 720p/30 HLS with a few seconds of playback delay.
Add `--headless --demo --mute` for a scripted demonstration.

See [streaming setup](streaming/README.md) for the native MediaMTX option,
recovery behavior, testing, additional matches and external viewing.
