import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from streaming import FramePublisher, StreamConfig, encoder_command, output_size


class StreamingTests(unittest.TestCase):
    def test_dimensions_preserve_aspect_without_upscaling(self):
        self.assertEqual(output_size((2560, 1440)), (1280, 720))
        self.assertEqual(output_size((1024, 768)), (960, 720))
        self.assertEqual(output_size((640, 480)), (640, 480))
        self.assertEqual(output_size((1920, 1200)), (1152, 720))
        self.assertEqual(output_size((1001, 601)), (1000, 600))

    def test_rejects_invalid_destinations_and_rates(self):
        for url in ('https://example.com/a', 'rtsp://host', 'rtsp:///match-1'):
            with self.assertRaises(ValueError):
                StreamConfig(url)
        with self.assertRaises(ValueError):
            StreamConfig('rtsp://localhost/match-1', fps=120)

    def test_encoder_is_video_only_with_two_second_keyframes(self):
        cmd = encoder_command(StreamConfig('rtsp://localhost/match-1'), (1280, 720))
        self.assertIn('-an', cmd)
        self.assertEqual(cmd[cmd.index('-g') + 1], '60')
        self.assertEqual(cmd[cmd.index('-framerate') + 1], '30')
        self.assertEqual(cmd[cmd.index('-rtsp_transport') + 1], 'tcp')

    def test_stalled_encoder_does_not_block_capture_or_shutdown(self):
        # A real child with a pipe that never drains exercises kernel backpressure.
        command = [sys.executable, '-c', 'import time; time.sleep(30)']
        config = StreamConfig('rtsp://localhost/match-1', ffmpeg=sys.executable,
                              write_timeout=.1, retry_delay=.05)
        with patch('streaming.encoder_command', return_value=command):
            publisher = FramePublisher(config, (1280, 720))
            try:
                surface = pygame.Surface((1280, 720))
                deadline = time.monotonic() + 1
                samples = []
                while time.monotonic() < deadline:
                    started = time.monotonic()
                    publisher.capture(surface)
                    samples.append(time.monotonic() - started)
                    self.assertLessEqual(len(publisher.pending), 1)
                    time.sleep(.01)
                self.assertLess(max(samples), .15)
                self.assertGreater(publisher.restarts, 0)
                self.assertGreater(publisher.dropped, 0)
            finally:
                publisher.close()
            self.assertFalse(publisher.thread.is_alive())

    def test_repeats_last_frame_when_renderer_pauses(self):
        command = [sys.executable, '-c', 'import sys; sys.stdin.buffer.read()']
        with patch('streaming.encoder_command', return_value=command):
            publisher = FramePublisher(StreamConfig('rtsp://localhost/match-1', ffmpeg=sys.executable), (64, 64))
            try:
                publisher.capture(pygame.Surface((64, 64)))
                time.sleep(.3)
                self.assertGreaterEqual(publisher.sent, 5)
                self.assertGreaterEqual(publisher.repeated, 4)
            finally:
                publisher.close()
            self.assertFalse(publisher.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
