from array import array
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from streaming.game_audio import mix, render, SAMPLE_RATE


class AudioTests(unittest.TestCase):
    def test_attack_timing_character_volume_looping_and_saturation(self):
        samples=mix([1000], [[1000,1000],[2000]], [(.2,1),(.5,2)],1,rate=10)
        self.assertEqual(len(samples),10)
        self.assertEqual(samples[0],0)  # five-second music fade-in
        self.assertEqual(samples[2],520)
        self.assertEqual(samples[3],530)
        self.assertEqual(samples[4],40)
        self.assertEqual(samples[5],1550)
        clipped=mix([0],[[32767],[-32768]],[(0,1)]*4+[(.1,2)]*4,1,rate=10)
        self.assertEqual(clipped[0],32767)
        self.assertEqual(clipped[1],-32768)

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg is required to decode game assets')
    def test_original_audio_assets_render_to_playback_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path=render(Path(directory)/'audio.wav',[{'attacks_started':[1,2]}],.5)
            with wave.open(str(path),'rb') as audio:
                self.assertEqual(audio.getnframes(),SAMPLE_RATE//2)
                self.assertEqual(audio.getframerate(),SAMPLE_RATE)
                self.assertEqual(audio.getsampwidth(),2)
                self.assertTrue(any(array('h',audio.readframes(audio.getnframes()))))
