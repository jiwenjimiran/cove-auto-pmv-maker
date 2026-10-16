import math
import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
from engine import Clip, audio_duration, beat_grid, mix_audio, prepare_audio, run


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class MediaPipelineTests(unittest.TestCase):
    def test_video_audio_extraction_and_three_audio_modes(self):
        with tempfile.TemporaryDirectory() as root:
            song = str(Path(root) / "song.wav")
            video = str(Path(root) / "source.mp4")
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
                 "-c:a", "pcm_s16le", song])
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:size=320x180:rate=30:duration=3",
                 "-f", "lavfi", "-i", "sine=frequency=660:duration=3", "-c:v", "mpeg4", "-c:a", "aac", video])
            extracted = prepare_audio({"kind": "video", "path": video}, root)
            self.assertGreater(audio_duration(extracted), 2.9)
            self.assertGreater(len(beat_grid(song, 0, 3)), 2)
            clip = Clip(1, video, 0, 1.5, 0.5, 0, None, True)
            measurements = {}
            late_source_levels = {}
            early_source_levels = {}
            for mode in ("muted", "mixed", "all"):
                folder = Path(root) / mode
                folder.mkdir()
                output = mix_audio(song, [clip], {"sourceAudio": mode}, str(folder), 3)
                with wave.open(output, "rb") as stream:
                    self.assertEqual(stream.getframerate(), 48000)
                    self.assertAlmostEqual(stream.getnframes() / stream.getframerate(), 3, delta=0.03)
                    raw = stream.readframes(stream.getnframes())
                import array
                values = array.array("h")
                values.frombytes(raw)
                measurements[mode] = sum(abs(v) for v in values) / len(values)
                # Measure the source's 660 Hz tone separately from the backing
                # song. All must retain it beyond Some's short accent window.
                def source_level(start, end):
                    samples = values[int(start * 48000) * 2:int(end * 48000) * 2:2]
                    real = sum(v * math.cos(2 * math.pi * 660 * n / 48000) for n, v in enumerate(samples))
                    imag = sum(v * math.sin(2 * math.pi * 660 * n / 48000) for n, v in enumerate(samples))
                    return math.hypot(real, imag) / len(samples)
                early_source_levels[mode] = source_level(0.6, 0.8)
                late_source_levels[mode] = source_level(1.4, 1.6)
                self.assertLessEqual(max(abs(v) for v in values), 32767)
            self.assertGreater(measurements["mixed"], measurements["muted"])
            self.assertGreater(measurements["all"], measurements["mixed"])
            self.assertGreater(early_source_levels["mixed"], early_source_levels["muted"] + 100)
            self.assertLess(late_source_levels["muted"], 5)
            self.assertLess(late_source_levels["mixed"], 5)
            self.assertGreater(late_source_levels["all"], 100)

    def test_long_mix_keeps_accents_after_eighty_cuts(self):
        with tempfile.TemporaryDirectory() as root:
            song = str(Path(root) / "song.wav")
            video = str(Path(root) / "source.mp4")
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=10", song])
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=blue:size=320x180:rate=30:duration=1",
                 "-f", "lavfi", "-i", "sine=frequency=660:duration=1", "-c:v", "mpeg4", "-c:a", "aac", video])
            clips = [Clip(1, video, 0, 0.1, index * 0.11, 0, None, True) for index in range(81)]
            output = mix_audio(song, clips, {"sourceAudio": "all"}, root, 10)
            self.assertAlmostEqual(audio_duration(output), 10, delta=0.05)


if __name__ == "__main__":
    unittest.main()
