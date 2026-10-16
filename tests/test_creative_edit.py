import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
from engine import Clip, probe, run
from music_analysis import BeatGrid
from creative_edit import FEATURES, direct, image_effect, prepare_creative_clips, time_knots


class CreativeTests(unittest.TestCase):
    def test_retime_stays_in_selected_range_and_has_exact_endpoints(self):
        for effect in (None, "speedRamps", "freezeAccents"):
            knots = time_knots(3, [(1, 1)], {"peak": 2, "motion": 1}, {}, effect)
            self.assertEqual((0, 0), knots[0])
            self.assertEqual((3, 3), knots[-1])
            self.assertTrue(all(a[1] <= b[1] for a, b in zip(knots, knots[1:])))
            self.assertTrue(all(0 <= source <= 3 for _, source in knots))

    def test_disabled_sections_and_global_cooldown(self):
        clips = [Clip(i + 1, f"{i}.mp4", 0, 2, i * 2, 0, None, True) for i in range(8)]
        beats = BeatGrid([i * .5 for i in range(33)], tempo=120,
                         strengths=[(i * .5, 1) for i in range(33)], energy=[(0, 1)])
        cue = {"peak": 1, "motion": 1, "direction": 1, "luma": 112, "sharpness": 60}
        with patch("creative_edit.analyze_shot", return_value=cue):
            _, plans = direct(clips, beats, {key: False for key in FEATURES})
            self.assertTrue(all(plan["dominant"] is None for plan in plans))
            self.assertTrue(all(not plan["drift"] and not plan["color"] for plan in plans))
            _, plans = direct(clips, beats, {"speedRamps": False, "freezeAccents": False})
            self.assertTrue(all(plan["dominant"] not in ("speedRamps", "freezeAccents") for plan in plans))

    def test_all_effects_produce_pixels_and_preserve_frame_shape(self):
        import numpy as np
        frame = np.zeros((90, 160, 3), np.uint8)
        frame[15:65, 30:100] = (210, 160, 230)
        for effect in ("beatPunch", "impactRecoil", "motionEcho", "rgbSplit", None):
            plan = {"hits": [(0, 1)], "strength": 1, "dominant": effect, "drift": True,
                    "scale": .035, "direction": 1, "color": True, "bloom": True, "cue": {"luma": 100}}
            result = image_effect(frame, .05, 2, plan, previous=np.roll(frame, 5, axis=1))
            self.assertEqual(frame.shape, result.shape)
            self.assertEqual(np.uint8, result.dtype)
            self.assertGreater(np.abs(result.astype(float) - frame).sum(), 100)

    def test_real_effect_video_with_retimed_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=3",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-c:a", "aac", str(source)])
            clip = Clip(1, str(source), .3, 2, 0, 0, None, True)
            beat = BeatGrid([0, .5, 1, 1.5, 2], tempo=120, strengths=[(.5, 1), (1, 1)], energy=[(0, 1)])
            clips, plans = direct([clip], beat, {})
            for effect in ("speedRamps", "freezeAccents"):
                plans[0]["dominant"] = effect
                plans[0]["knots"] = time_knots(2, [(1, 1)], plans[0]["cue"], {}, effect)
                result = prepare_creative_clips(clips, plans, {}, Path(folder) / effect, 30,
                                               threading.Event(), lambda *_: None)
                info = probe(result[0].path)
                self.assertAlmostEqual(2, float(info["format"]["duration"]), delta=.08)
                self.assertTrue(any(row["codec_type"] == "audio" for row in info["streams"]))
                self.assertEqual(0, result[0].source_start)


if __name__ == "__main__":
    unittest.main()
