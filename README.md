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
