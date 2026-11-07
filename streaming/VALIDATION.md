# Local verification — 2026-11-07

Environment: macOS ARM64, Python 3.12.7, Pygame 2.6.1, FFmpeg 8.0.1,
MediaMTX 1.21.3 (official release SHA-256 verified).

- Real Pygame scripted match → RGB pipe → H.264 encoder → RTSP → MediaMTX
  → HLS proxy → embedded browser player: visibly playing.
- Browser video state: 1280×720, `paused=false`, `readyState=4`, advancing playback.
- Two concurrent ffprobe readers each decoded 180 frames over six seconds,
  H.264 / 1280×720 / 30 FPS. Each reported exactly one video stream, no audio.
- MediaMTX was terminated for four seconds during the integration test. The game
  remained running. After MediaMTX restarted, publishing recovered automatically;
  the post-restart probe again decoded 180 frames over six seconds.
- Normal ten-second demo samples: approximately 53–54 rendered FPS and 29.7–30.0
  frames/sec fed to FFmpeg. Frame copy averaged roughly 1.4 ms. Replaced pending
  frames are expected when the rendering rate exceeds the broadcast rate.
- Tests cover aspect ratio/even dimensions, bad configuration, video-only encoder
  arguments, a real child process that never drains its pipe, bounded frame storage,
  frame repetition during renderer pauses, shutdown, keyboard controls, and attack
  animation state after releasing a key.
- Compose configuration parses successfully. Docker services were not executed
  because the Docker daemon was not running; native services were tested instead.

This is a local functional baseline, not a capacity benchmark. No external-network,
real AI inference, 60 FPS, or large-viewer-load acceptance test has been completed.
Browser dropped-frame counters were unavailable in the embedded browser.

Reproduce using the commands in [README.md](README.md). The integration runner
writes its own JSON result and service logs to a temporary directory and cleans up
its child processes.

## Merge validation

Merged upstream `9eab9c0` into the streaming branch. The shared Arena, JSON-model
validation, weight-editing providers and tool loop are preserved unchanged.
The renderer keeps upstream's Pygame-only implementation; OpenCV/NumPy are no
longer game requirements. The scripted test now emits Arena action IDs instead
of running a separate combat implementation.

- Upstream suite: 37 tests pass in the locked uv environment.
- Streaming/scripted-input suite: 8 tests pass.
- Shared game display smoke test passes.
- Scripted shared-Arena HLS: two readers and MediaMTX restart recovery pass.
- The weight-editing viewer supports `--stream`, `--stream-fps` and `--headless`
  while preserving `--demo RUN_DIRECTORY`, replay controls and edit panels.
- Weight-editing viewer HLS fixture: both readers decoded 180 H.264 frames in
  six seconds at 922×720/30 FPS; decoding resumed after MediaMTX restarted.
  These were local model-match fixtures, not live provider runs.
