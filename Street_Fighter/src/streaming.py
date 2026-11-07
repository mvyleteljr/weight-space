"""Video-only Pygame -> FFmpeg -> RTSP publisher (macOS/Linux).

Only capture() touches Pygame. A single-slot mailbox hands immutable RGB bytes
to a paced worker; neither the encoder nor the network can block the game loop.
"""
import logging
import os
import select
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit

log = logging.getLogger("stream")


def output_size(size):
    """Fit within 1280x720 without upscaling; H.264 requires even dimensions."""
    width, height = size
    if min(size) < 2:
        raise ValueError("Surface dimensions must be at least 2 pixels")
    scale = min(1, 1280 / width, 720 / height)
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


@dataclass(frozen=True)
class StreamConfig:
    url: str
    fps: int = 30
    ffmpeg: str = "ffmpeg"
    write_timeout: float = 0.5
    retry_delay: float = 2.0

    def __post_init__(self):
        parsed = urlsplit(self.url)
        if parsed.scheme != "rtsp" or not parsed.hostname or parsed.path in ("", "/"):
            raise ValueError("Stream URL must be rtsp://host:port/match-name")
        if self.fps not in (30, 60):
            raise ValueError("Stream FPS must be 30 or 60")
        if self.write_timeout <= 0 or self.retry_delay <= 0:
            raise ValueError("Timeouts must be positive")


def encoder_command(config, size):
    return [
        config.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{size[0]}x{size[1]}", "-framerate", str(config.fps),
        "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-tune", "zerolatency", "-threads", "2", "-pix_fmt", "yuv420p",
        "-b:v", "2500k", "-maxrate", "3000k", "-bufsize", "3000k",
        "-g", str(config.fps * 2), "-keyint_min", str(config.fps * 2),
        "-sc_threshold", "0", "-bf", "0", "-f", "rtsp",
        "-rtsp_transport", "tcp", config.url,
    ]


class FramePublisher:
    def __init__(self, config, surface_size):
        if os.name != "posix":
            raise RuntimeError("Streaming currently supports macOS and Linux")
        if not shutil.which(config.ffmpeg):
            raise RuntimeError("FFmpeg is missing. Install FFmpeg or omit --stream.")
        self.config = config
        self.size = output_size(surface_size)
        # deque append/popleft are atomic on CPython. No encoder-held locks.
        self.pending = deque(maxlen=1)
        self.stop = threading.Event()
        self.next_capture = 0.0
        self.captured = self.dropped = self.sent = self.repeated = self.restarts = 0
        self.presented = 0
        self.capture_seconds = 0.0
        self.max_capture_ms = 0.0
        self.thread = threading.Thread(target=self._run, name="frame-publisher", daemon=True)
        self.thread.start()

    def capture(self, surface):
        """Call after drawing; bounded copy, never a pipe or network write."""
        import pygame
        self.presented += 1
        now = time.monotonic()
        if self.stop.is_set() or now < self.next_capture:
            return
        # Capture up to game cadence so the encoder can select a fresh frame
        # even when the 30 FPS deadline falls between two game frames.
        period = 1 / 60
        self.next_capture = max(self.next_capture + period, now)
        frame = surface
        if frame.get_size() != self.size:
            frame = pygame.transform.scale(frame, self.size)
        pixels = pygame.image.tobytes(frame, "RGB")
        if self.pending:
            self.dropped += 1
        self.pending.append(pixels)
        self.captured += 1
        elapsed = time.monotonic() - now
        self.capture_seconds += elapsed
        self.max_capture_ms = max(self.max_capture_ms, elapsed * 1000)

    def _write_frame(self, process, frame):
        """Finish a frame or restart the pipe; never leave partial RGB frames."""
        view = memoryview(frame)
        deadline = time.monotonic() + self.config.write_timeout
        fd = process.stdin.fileno()
        while view:
            if self.stop.is_set():
                raise InterruptedError("Publisher stopping")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Encoder fell behind")
            if process.poll() is not None:
                raise BrokenPipeError("Encoder exited")
            if not select.select([], [fd], [], min(remaining, 0.05))[1]:
                continue
            try:
                written = os.write(fd, view)
            except BlockingIOError:
                continue
            if not written:
                raise BrokenPipeError("Encoder pipe closed")
            view = view[written:]

    @staticmethod
    def _terminate(process):
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        if process.stdin:
            process.stdin.close()

    def _run(self):
        process = None
        frame = None
        period = 1 / self.config.fps
        deadline = time.monotonic()
        report_at = deadline
        previous_sent = previous_presented = 0
        log.info("Video publisher: %sx%s at %s FPS; no audio", *self.size, self.config.fps)
        try:
            while not self.stop.is_set():
                if self.stop.wait(max(0, deadline - time.monotonic())):
                    break
                fresh = False
                try:
                    frame = self.pending.popleft()
                    fresh = True
                except IndexError:
                    pass
                if frame is None:
                    deadline = time.monotonic() + period
                    continue
                try:
                    if process is None:
                        process = subprocess.Popen(
                            encoder_command(self.config, self.size), stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, bufsize=0,
                        )
                        os.set_blocking(process.stdin.fileno(), False)
                    self._write_frame(process, frame)
                    self.sent += 1
                    self.repeated += int(not fresh)
                except (OSError, TimeoutError) as error:
                    self._terminate(process)
                    process = None
                    if self.stop.is_set():
                        break
                    self.restarts += 1
                    log.warning("Encoder unavailable (%s); retrying in %.1fs", type(error).__name__, self.config.retry_delay)
                    self.stop.wait(self.config.retry_delay)
                    # Restart from the newest available image, never replay an old queue.
                    frame = None
                    deadline = time.monotonic()
                    continue
                now = time.monotonic()
                if now - report_at >= 10:
                    elapsed = now - report_at
                    log.info("render=%.1f FPS feed=%.1f FPS capture_avg=%.2fms capture_max=%.2fms dropped=%d repeats=%d restarts=%d",
                             (self.presented - previous_presented) / elapsed,
                             (self.sent - previous_sent) / elapsed,
                             1000 * self.capture_seconds / max(1, self.captured),
                             self.max_capture_ms, self.dropped, self.repeated, self.restarts)
                    previous_sent, previous_presented = self.sent, self.presented
                    report_at = now
                # Small scheduling jitter is corrected on the next tick. A major
                # stall resets timing rather than producing a catch-up burst.
                deadline += period
                if now > deadline + period:
                    deadline = now + period
        finally:
            self._terminate(process)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)
        self.pending.clear()
