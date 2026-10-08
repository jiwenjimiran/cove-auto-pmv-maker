import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
from engine import Clip, choose_format, edit_plan, output_stem, reserve_output


class EngineTests(unittest.TestCase):
    def source(self, ident, *, height=1080, fps=30, performers=(), studio=None, segments=()):
        return {"id": ident, "path": "fixture.mp4", "duration": 100, "width": int(height * 16 / 9), "height": height,
                "fps": fps, "performerIds": list(performers), "performerNames": [f"P{x}" for x in performers],
                "studioId": studio, "studioName": f"S{studio}" if studio else None, "segments": list(segments)}

    def test_output_format_uses_every_source(self):
        sources = [self.source(1, height=720, fps=60), self.source(2, height=720, fps=60)]
        self.assertEqual(choose_format(sources, "three-pane", {}), (720, 1280, 60))
        portrait = [{**sources[0], "width": 720, "height": 1280}, {**sources[1], "width": 720, "height": 1280}]
        self.assertEqual(choose_format(portrait, "three-pane", {}), (720, 1280, 60))
        sources.append(self.source(3, height=2160, fps=30))
        self.assertEqual(choose_format(sources, "full-screen", {}), (1920, 1080, 30))
        self.assertEqual(choose_format(sources, "full-screen", {"outputWidth": 1280, "outputHeight": 720, "outputFps": 60}), (1280, 720, 60))

    def test_edit_plan_covers_sources_and_uses_three_independent_panes(self):
        sources = [self.source(i) for i in range(1, 7)]
        # Timed ranges avoid invoking ffmpeg in this planning test.
        for source in sources:
            source["segments"] = [{"id": source["id"], "start": 1, "end": 80}]
            source["tagOnly"] = True
        beats = [x * 0.5 for x in range(81)]
        clips = edit_plan(sources, beats, {"style": "high-energy"}, "three-pane")
        self.assertEqual({c.video_id for c in clips}, set(range(1, 7)))
        self.assertEqual({c.pane for c in clips}, {0, 1, 2})
        self.assertEqual({c.video_id for c in clips if c.record_start == 0}, {1, 2, 3})
        self.assertAlmostEqual(max(c.record_start + c.duration for c in clips), beats[-1])

    def test_tag_name_uses_only_used_timed_segments(self):
        segment = {"id": 8, "start": 2, "end": 9, "tagId": 3, "tagName": "Beat"}
        sources = [self.source(1, segments=[segment]), self.source(2, segments=[segment])]
        clips = [Clip(1, "a", 2, 3, 0, 0, 8, False), Clip(2, "b", 2, 3, 3, 0, 8, False)]
        self.assertEqual(output_stem(sources, clips), "PMVMAKER_Beat")
        self.assertEqual(output_stem(sources, clips, "A/B"), "PMVMAKER_A_B")
        performers = [self.source(1, performers=(1, 2)), self.source(2, performers=(1, 2, 3))]
        self.assertEqual(output_stem(performers, clips), "PMVMAKER_P1_P2")

    def test_collision_reservations(self):
        with tempfile.TemporaryDirectory() as root:
            first, marker_a = reserve_output(root, "PMVMAKER_Multi")
            second, marker_b = reserve_output(root, "PMVMAKER_Multi")
            self.assertEqual(Path(first).name, "PMVMAKER_Multi.mp4")
            self.assertEqual(Path(second).name, "PMVMAKER_Multi(1).mp4")
            marker_a.unlink(); marker_b.unlink()
            (Path(root) / "PMVMAKER_Multi.drp").write_text("fixture")
            project_safe, marker_c = reserve_output(root, "PMVMAKER_Multi", save_project=True)
            self.assertEqual(Path(project_safe).name, "PMVMAKER_Multi(1).mp4")
            marker_c.unlink()

    def test_large_studio_uses_only_sources_the_song_can_show(self):
        sources = [self.source(i) for i in range(1, 10001)]
        for source in sources:
            source["segments"] = [{"id": source["id"], "start": 0, "end": 40}]
            source["tagOnly"] = True
        beats = [x * 0.5 for x in range(241)]
        clips = edit_plan(sources, beats, {}, "full-screen")
        self.assertLess(len({clip.video_id for clip in clips}), 1000)
        self.assertAlmostEqual(max(c.record_start + c.duration for c in clips), 120)

    def test_tag_edit_never_spills_outside_a_timed_segment(self):
        source = self.source(1, segments=[{"id": 1, "start": 2, "end": 3}])
        source["tagOnly"] = True
        with self.assertRaisesRegex(ValueError, "no timed segment long enough"):
            edit_plan([source], [0, 3], {"minClipSeconds": 2, "maxClipSeconds": 3}, "full-screen")


if __name__ == "__main__":
    unittest.main()
