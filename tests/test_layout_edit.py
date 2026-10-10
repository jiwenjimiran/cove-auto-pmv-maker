import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))

from layout_edit import edit_plan
from music_analysis import BeatGrid
from engine import choose_format, layout_modes
from face_analysis import FaceAnalyzer


def source(ident, portrait=False, segments=None):
    return {"id": ident, "path": f"source-{ident}.mp4", "duration": 120,
            "width": 1080 if portrait else 1920, "height": 1920 if portrait else 1080,
            "fps": 30, "segments": segments or [], "tagOnly": segments is not None}


BEATS = BeatGrid([float(i) for i in range(33)], bars=tuple(range(0, 32, 4)),
                 phrases=(16, 24), meter=4)
OPTIONS = {"selectionMode": "center", "maxClipSeconds": 6,
           "minClipSeconds": 1, "sampledClipsProgress": True, "rotatedClipLengthSeconds": 60,
           "cycleLongerClipIntoSegments": True,
           "transitionFamilies": ["cut"]}


class LayoutEditTests(unittest.TestCase):
    def plan(self, sources, layout, **overrides):
        options = {**OPTIONS, **overrides}
        with patch("source_picker.scene_ranges", side_effect=lambda path, start, duration, cancel: [(start, start + duration)]):
            return edit_plan(sources, BEATS, options, layout)

    def test_grid_uses_four_distinct_landscape_videos_and_staggers_opening(self):
        clips = self.plan([source(i) for i in range(1, 6)] + [source(6, portrait=True)], "grid")
        self.assertEqual({0}, {c.pane for c in clips if c.record_start == 0})
        self.assertEqual({3}, {c.pane for c in clips if c.record_start == 4})
        self.assertEqual({1}, {c.pane for c in clips if c.record_start == 8})
        for t in (13, 17, 25):
            active = [c for c in clips if c.record_start <= t < c.record_start + c.duration]
            self.assertEqual(4, len(active))
            self.assertEqual(4, len({c.video_id for c in active}))
            self.assertNotIn(6, {c.video_id for c in active})

    def test_hybrid_changes_layout_only_on_phrases_and_expands_visible_cell(self):
        clips = self.plan([source(i) for i in range(1, 6)], "grid-full")
        active_grid = [c for c in clips if c.layout_role == "grid" and c.record_start <= 16 < c.record_start + c.duration]
        self.assertEqual(4, len(active_grid))
        first_full = next(c for c in clips if c.layout_role == "full-screen" and c.record_start == 16)
        self.assertIsNotNone(first_full.expansion_from)
        expanded = active_grid[first_full.expansion_from]
        self.assertEqual(expanded.video_id, first_full.video_id)
        self.assertAlmostEqual(expanded.source_start + 16 - expanded.record_start, first_full.source_start)
        self.assertEqual(4, len([c for c in clips if c.underlay and c.record_start == 16]))
        self.assertEqual({"grid"}, {c.layout_role for c in clips if c.record_start == 24 and not c.underlay})

    def test_grid_and_full_never_includes_portrait_panes(self):
        clips = self.plan([source(i) for i in range(1, 6)], "full-screen",
                          layoutModes=["grid", "full-screen"])
        self.assertEqual({"grid", "full-screen"}, {c.layout_role for c in clips})

    def test_grid_never_uses_face_slice_even_when_saved_selection_is_face(self):
        with patch("face_analysis.FaceAnalyzer") as analyzer:
            clips = self.plan([source(i) for i in range(1, 6)], "full-screen",
                              layoutModes=["grid", "full-screen"], selectionMode="face",
                              fullSelectionMode="face")
        analyzer.assert_not_called()
        self.assertEqual({"grid", "full-screen"}, {clip.layout_role for clip in clips})

    def test_triple_portrait_expands_when_continuous_footage_exists(self):
        clips = self.plan([source(i) for i in range(1, 6)], "full-screen",
                          layoutModes=["three-pane", "full-screen"])
        first_full = next(c for c in clips if c.layout_role == "full-screen" and c.record_start == 16)
        self.assertIsNotNone(first_full.expansion_from)
        self.assertEqual("three-pane", first_full.expansion_layout)

    def test_grid_expansion_corner_varies_across_random_seeds(self):
        corners = set()
        for seed in range(12):
            clips = self.plan([source(i) for i in range(1, 6)], "full-screen",
                              layoutModes=["grid", "full-screen"], randomSeed=seed)
            first_full = next(c for c in clips if c.layout_role == "full-screen" and c.record_start == 16)
            corners.add(first_full.expansion_from)
        self.assertGreaterEqual(len(corners), 3)

    def test_all_three_checked_modes_appear(self):
        clips = self.plan([source(i) for i in range(1, 6)], "full-screen",
                          layoutModes=["grid", "three-pane", "full-screen"])
        self.assertEqual({"grid", "three-pane", "full-screen"},
                         {c.layout_role for c in clips})

    def test_no_checked_modes_defaults_to_full_screen(self):
        self.assertEqual(["full-screen"], layout_modes({"layoutModes": [], "layout": "grid"}))

    def test_performer_match_threshold_never_below_fifty_five_percent(self):
        self.assertEqual(0.55, FaceAnalyzer(threshold=0.45).threshold)
        self.assertEqual(0.7, FaceAnalyzer(threshold=0.7).threshold)

    def test_performer_match_rejects_unlinked_faces_before_decoding_video(self):
        matcher = FaceAnalyzer()
        matcher.recognizer = object()
        matcher.reference_ids = [42]
        matcher.reference_vectors = __import__("numpy").ones((1, 128), dtype="float32")
        reasons = []
        self.assertIsNone(matcher.analyze_match("missing.mp4", 0, 2, 0.5, True,
                                                rejection=reasons.append, allowed_performer_ids=[]))
        self.assertEqual(["video has no linked performer to match"], reasons)
        self.assertIsNone(matcher.analyze_match("missing.mp4", 0, 2, 0.5, True,
                                                rejection=reasons.append, allowed_performer_ids=[99]))
        self.assertIn("linked performers have no selected reference face", reasons)

    def test_segment_intervals_limit_all_selected_source_time(self):
        segments = [{"id": 1, "start": 40, "end": 100}]
        clips = self.plan([source(i, segments=segments) for i in range(1, 5)], "grid")
        self.assertTrue(clips)
        for clip in clips:
            self.assertGreaterEqual(clip.source_start, 40)
            self.assertLessEqual(clip.source_start + clip.duration, 100.1)

    def test_grid_requires_four_eligible_landscape_videos(self):
        with self.assertRaisesRegex(ValueError, "four eligible landscape"):
            self.plan([source(1), source(2), source(3), source(4, portrait=True)], "grid")

    def test_portrait_only_hybrid_still_renders_landscape(self):
        width, height, _ = choose_format([source(1, portrait=True)], "three-pane-full", OPTIONS)
        self.assertGreater(width, height)


if __name__ == "__main__":
    unittest.main()
