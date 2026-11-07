"""Exercise real HLS decoding, two readers, and recovery on temporary local ports.

Run with the game's venv: python streaming/smoke_test.py --mediamtx /path/to/mediamtx
Requires ffmpeg, ffprobe, MediaMTX 1.21.3. Does not use or interrupt the demo ports.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_stream(url, game):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if game.poll() is not None:
            raise RuntimeError('Game exited; inspect game.log')
        try:
            with urlopen(url, timeout=2) as response:
                if b'#EXTM3U' in response.read():
                    return
        except OSError:
            pass
        time.sleep(.5)
    raise RuntimeError('HLS playlist did not become ready')


def probe(url):
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-read_intervals', '%+6', '-count_frames',
        '-show_entries', 'stream=codec_name,codec_type,width,height,r_frame_rate,nb_read_frames',
        '-of', 'json', url,
    ], capture_output=True, text=True, check=True, timeout=30)
    streams = json.loads(result.stdout)['streams']
    assert len(streams) == 1, streams
    video = streams[0]
    assert (video['codec_name'], video['codec_type'], video['width'], video['height'], video['r_frame_rate']) == ('h264', 'video', 1280, 720, '30/1'), video
    assert int(video['nb_read_frames']) >= 175, video
    return video


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mediamtx', default=shutil.which('mediamtx'))
    args = parser.parse_args()
    if not args.mediamtx or not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('MediaMTX, ffmpeg and ffprobe are required')
    rtsp, hls, web = free_port(), free_port(), free_port()
    report_dir = Path(tempfile.mkdtemp(prefix='weight-space-hls-'))
    config = (ROOT / 'streaming/mediamtx.yml').read_text()
    config = config.replace('127.0.0.1:8554', f'127.0.0.1:{rtsp}').replace('127.0.0.1:8888', f'127.0.0.1:{hls}')
    config_path = report_dir / 'mediamtx.yml'
    config_path.write_text(config)
    children, logs = [], []

    def start(command, name):
        log = (report_dir / f'{name}.log').open('ab')
        logs.append(log)
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log)
        children.append(process)
        return process

    try:
        media = start([args.mediamtx, str(config_path)], 'media')
        start([sys.executable, 'streaming/server.py', '--port', str(web), '--hls-origin', f'http://127.0.0.1:{hls}'], 'web')
        game = start([sys.executable, 'Street_Fighter/src/main.py', '--headless', '--demo', '--mute', '--stream', f'rtsp://127.0.0.1:{rtsp}/match-test'], 'game')
        url = f'http://127.0.0.1:{web}/live/match-test/index.m3u8'
        wait_stream(url, game)
        print('HLS available; decoding with two simultaneous viewers...', flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            viewers = list(pool.map(probe, [url, url]))
        print('Both viewers decoded 720p/30 video. Restarting MediaMTX...', flush=True)
        stop(media)
        time.sleep(4)
        assert game.poll() is None, 'Publisher outage stopped gameplay'
        start([args.mediamtx, str(config_path)], 'media')
        wait_stream(url, game)
        recovered = probe(url)
        result = {'viewers': viewers, 'after_server_restart': recovered,
                  'external_connection_tested': False, 'real_ai_agents_tested': False}
        (report_dir / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(f'PASS: two viewers and automatic recovery. Evidence: {report_dir}', flush=True)
    finally:
        for process in reversed(children):
            stop(process)
        for log in logs:
            log.close()
        print(f'Logs: {report_dir}', flush=True)


if __name__ == '__main__':
    main()
