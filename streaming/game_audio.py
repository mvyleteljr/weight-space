"""Render the original game's sounds against recorded attack-start timestamps."""
from array import array
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess
import sys
import wave

SAMPLE_RATE = 44100
ASSETS = Path(__file__).resolve().parents[1] / 'Street_Fighter/assets/audio'


@lru_cache(maxsize=3)
def decode(path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('FFmpeg is required for game audio.')
    result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(path),
        '-f', 's16le', '-acodec', 'pcm_s16le', '-ac', '1', '-ar', str(SAMPLE_RATE), 'pipe:1'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True)
    samples = array('h', result.stdout)
    if sys.byteorder != 'little':
        samples.byteswap()
    if not samples:
        raise ValueError('Empty sound asset.')
    return samples


def mix(music, effects, events, duration, rate=SAMPLE_RATE):
    """Mix at the Python game's volumes; events contain seconds and player IDs."""
    count = round(duration * rate)
    samples = array('i', (int(music[i % len(music)] * .5 * min(1, i / (5 * rate)))
                          for i in range(count)))
    for seconds, player in events:
        start = round(seconds * rate)
        effect, volume = effects[player-1], (.5 if player == 1 else .75)
        for i in range(min(len(effect), max(0, count-start))):
            samples[start+i] += int(effect[i] * volume)
    return array('h', (max(-32768, min(32767, sample)) for sample in samples))


def render(path, rows, duration, fps=60):
    events = [(index / fps, player) for index, row in enumerate(rows, 1)
              for player in row.get('attacks_started', [])]
    samples = mix(decode(ASSETS/'music.mp3'),
                  [decode(ASSETS/'sword.wav'), decode(ASSETS/'magic.wav')], events, duration)
    if sys.byteorder != 'little':
        samples.byteswap()
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    with wave.open(str(temporary), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(samples.tobytes())
    temporary.replace(path)
    return path
