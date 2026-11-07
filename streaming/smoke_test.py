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


def probe(url, expected_size=(1280, 720)):
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-read_intervals', '%+6', '-count_frames',
        '-show_entries', 'stream=codec_name,codec_type,width,height,r_frame_rate,nb_read_frames',
        '-of', 'json', url,
    ], capture_output=True, text=True, check=True, timeout=30)
    streams = json.loads(result.stdout)['streams']
    assert len(streams) == 1, streams
    video = streams[0]
    assert (video['codec_name'], video['codec_type'], video['width'], video['height'], video['r_frame_rate']) == ('h264', 'video', *expected_size, '30/1'), video
    assert int(video['nb_read_frames']) >= 175, video
    return video


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mediamtx', default=shutil.which('mediamtx'))
    parser.add_argument('--source', choices=('scripted', 'viewer'), default='scripted')
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
        destination = f'rtsp://127.0.0.1:{rtsp}/match-test'
        expected_size = (1280, 720)
        if args.source == 'viewer':
            # Real model matches, with explicit fixture weights; no provider calls.
            sys.path.insert(0, str(ROOT))
            from weight_space.game import match
            from weight_space.network import initialize, save
            from Street_Fighter.src.arena import encode_action
            fixture = report_dir / 'viewer-fixture'
            fixture.mkdir()
            models = [fixture / 'one.json', fixture / 'two.json']
            model = initialize([31, 18], zero=True)
            for path in models:
                save(path, model)
            match(*models, fixture / 'before', max_steps=180)
            for index, path in enumerate(models):
                edited = initialize([31, 18], zero=True)
                edited['layers'][0]['bias'][encode_action(move=1 if index == 0 else -1, attack=1)] = 1
                path.write_text(json.dumps(edited))
            match(*models, fixture / 'after', max_steps=180)
            (fixture / 'demo.json').write_text(json.dumps({'phase': 'complete', 'agents': [
                {'name': name, 'status': 'complete', 'reason': 'Validation fixture, not a provider response'}
                for name in ('Fixture 1', 'Fixture 2')]}))
            command = [sys.executable, '-m', 'weight_space.viewer', '--demo', str(fixture), '--headless', '--stream', destination]
            expected_size = (922, 720)
        else:
            command = [sys.executable, 'Street_Fighter/src/main.py', '--headless', '--demo', '--mute', '--stream', destination]
        game = start(command, 'game')
        url = f'http://127.0.0.1:{web}/live/match-test/index.m3u8'
        wait_stream(url, game)
        print('HLS available; decoding with two simultaneous viewers...', flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            viewers = list(pool.map(lambda target: probe(target, expected_size), [url, url]))
        print('Both viewers decoded 720p/30 video. Restarting MediaMTX...', flush=True)
        stop(media)
        time.sleep(4)
        assert game.poll() is None, 'Publisher outage stopped gameplay'
        start([args.mediamtx, str(config_path)], 'media')
        wait_stream(url, game)
        recovered = probe(url, expected_size)
        result = {'source': args.source, 'viewers': viewers, 'after_server_restart': recovered,
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
