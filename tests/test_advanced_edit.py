import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))

from advanced_edit import edit_plan
from music_analysis import BeatGrid
from engine import beat_grid
from source_picker import permitted_ranges, SourceCursor


def source(ident, duration=200, segments=None, tag_only=False):
    return {"id": ident, "path": f"source-{ident}.mp4", "duration": duration,
            "width": 1920, "height": 1080, "fps": 30,
            "segments": segments or [], "tagOnly": tag_only}


class AdvancedEditTests(unittest.TestCase):
    def test_beat_grid_tracks_bars_and_phrase_from_accents(self):
        import numpy as np
        sample_rate = 11025
        samples = np.zeros(sample_rate * 18, dtype=np.int16)
        for index, seconds in enumerate(np.arange(0, 18, .5)):
            first = round(seconds * sample_rate)
            samples[first:first + 110] = 14000 if index % 4 == 0 else 6000
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "beats.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(samples.tobytes())
            grid = beat_grid(str(path), 0, 18)
        self.assertGreater(len(grid), 25)
        self.assertGreaterEqual(len(grid.bars), 6)
        self.assertTrue(grid.phrases)
        self.assertAlmostEqual(120, grid.tempo, delta=10)

    def test_timestamp_bounds_progressive_bands_and_tag_restriction(self):
        options = {"minimumTimestampSeconds": 20, "endBufferSeconds": 30,
                   "sampledClipsProgress": True, "maxClipSeconds": 5}
        ranges = permitted_ranges(source(1), options)
        self.assertEqual(20, len(ranges))
        self.assertEqual(20, ranges[0].start)
        self.assertEqual(170, ranges[-1].end)
        tagged = source(2, segments=[{"id": 8, "start": 10, "end": 40},
                                     {"id": 9, "start": 160, "end": 195}], tag_only=True)
        self.assertEqual([(20, 40, 8), (160, 170, 9)],
                         [(r.start, r.end, r.segment_id) for r in permitted_ranges(tagged, options, True)])

    def test_source_cursor_cycles_within_window_then_advances(self):
        options = {"sampledClipsProgress": True, "maxClipSeconds": 2,
                   "rotatedClipLengthSeconds": 10, "cycleLongerClipIntoSegments": True}
        with patch("source_picker.scene_ranges", side_effect=lambda path, start, duration, cancel: [(start, start + duration)]):
            cursor = SourceCursor(source(1, duration=100), options)
            first = cursor.next(2)
            second = cursor.next(2)
            self.assertAlmostEqual(first[0] + 2, second[0])
            for _ in range(3):
                cursor.next(2)
            next_band = cursor.next(2)
            self.assertGreaterEqual(next_band[0], 5)

    def test_bar_cadence_mirror_and_full_song(self):
        beats = BeatGrid([float(i) for i in range(17)], bars=(0, 4, 8, 12), phrases=(8,), meter=4)
        options = {"layout": "three-pane", "selectionMode": "center", "sampledClipsProgress": True,
                   "mirrorRepeatedSource": True, "maxClipSeconds": 5, "minClipSeconds": 1,
                   "rotatedClipLengthSeconds": 20, "cycleLongerClipIntoSegments": True}
        with patch("source_picker.scene_ranges", side_effect=lambda path, start, duration, cancel: [(start, start + duration)]):
            clips = edit_plan([source(1, duration=200)], beats, options, "three-pane")
        self.assertEqual({0, 1, 2}, {clip.pane for clip in clips})
        self.assertAlmostEqual(16, max(c.record_start + c.duration for c in clips))
        for left in [clip for clip in clips if clip.pane == 0]:
            right = next(c for c in clips if c.pane == 2 and c.record_start == left.record_start)
            self.assertTrue(right.mirrored)
            self.assertAlmostEqual(left.source_start, right.source_start)
        at_four = [c for c in clips if c.record_start == 4]
        self.assertEqual({0, 2}, {c.pane for c in at_four})
        # The center continues through this bar without a timeline cut.
        center = next(c for c in clips if c.pane == 1)
        self.assertGreater(center.duration, 4)

    def test_two_sources_keep_center_unique_and_outside_pair_mirrored(self):
        beats = BeatGrid([float(i) for i in range(9)], bars=(0, 2, 4, 6), phrases=(4,), meter=4)
        options = {"layout": "three-pane", "selectionMode": "center", "sampledClipsProgress": True,
                   "mirrorRepeatedSource": True, "maxClipSeconds": 4, "minClipSeconds": 1,
                   "rotatedClipLengthSeconds": 10, "cycleLongerClipIntoSegments": True}
        with patch("source_picker.scene_ranges", side_effect=lambda path, start, duration, cancel: [(start, start + duration)]):
            clips = edit_plan([source(1), source(2)], beats, options, "three-pane")
        for time in (0, 2, 4, 6):
            active = {pane: next(c for c in clips if c.pane == pane and c.record_start <= time < c.record_start + c.duration)
                      for pane in (0, 1, 2)}
            self.assertEqual(active[0].video_id, active[2].video_id)
            self.assertNotEqual(active[0].video_id, active[1].video_id)
            self.assertTrue(active[2].mirrored)
        outside_before = next(c for c in clips if c.pane == 0 and c.record_start <= 2 < c.record_start + c.duration)
        outside_phrase = next(c for c in clips if c.pane == 0 and c.record_start <= 4 < c.record_start + c.duration)
        self.assertNotEqual(outside_before.video_id, outside_phrase.video_id)

    def test_large_library_only_decodes_selected_source_windows(self):
        beats = BeatGrid([float(i) for i in range(13)], bars=(0, 3, 6, 9), phrases=(9,), meter=4)
        options = {"layout": "full-screen", "sampledClipsProgress": True,
                   "maxClipSeconds": 4, "minClipSeconds": 1, "rotatedClipLengthSeconds": 10}
        with patch("source_picker.scene_ranges", side_effect=lambda path, start, duration, cancel: [(start, start + duration)]) as scenes:
            clips = edit_plan([source(i) for i in range(1, 101)], beats, options, "full-screen")
        self.assertLess(scenes.call_count, 20)
        self.assertEqual(12, max(c.record_start + c.duration for c in clips))

    def test_three_sources_change_one_pane_on_bar_and_all_on_phrase(self):
        beats = BeatGrid([float(i) for i in range(9)], bars=(0, 2, 4, 6), phrases=(4,), meter=4)
        options = {"layout": "three-pane", "selectionMode": "center", "sampledClipsProgress": True,
                   "mirrorRepeatedSource": True, "maxClipSeconds": 4, "minClipSeconds": 1,
                   "rotatedClipLengthSeconds": 10}
        with patch("source_picker.scene_ranges", side_effect=lambda path, start, duration, cancel: [(start, start + duration)]):
            clips = edit_plan([source(1), source(2), source(3)], beats, options, "three-pane")
        self.assertEqual({0}, {c.pane for c in clips if c.record_start == 2})
        self.assertEqual({0, 1, 2}, {c.pane for c in clips if c.record_start == 4})

    def test_face_match_logs_performer_range_and_similarity(self):
        beats = BeatGrid([float(i) for i in range(5)], bars=(0,), phrases=(), meter=4)
        options = {"layout": "three-pane", "selectionMode": "face", "matchSelectedPerformers": True,
                   "maxClipSeconds": 5, "minClipSeconds": 1, "sampledClipsProgress": True,
                   "rotatedClipLengthSeconds": 10}
        messages = []
        with patch("source_picker.scene_ranges", side_effect=lambda path, start, duration, cancel: [(start, start + duration)]), \
                patch("face_analysis.FaceAnalyzer") as analyzer:
            analyzer.return_value.references = {42: [object()]}
            analyzer.return_value.analyze_match.return_value = (((0.0, 0.5),), 42, 0.68)
            clips = edit_plan([source(1), source(2), source(3)], beats, options, "three-pane",
                              references=[{"performerId": 42, "performerName": "Ada"}], log=messages.append)
        self.assertEqual(3, len(clips))
        selected = [message for message in messages if message.startswith("Selected slice")]
        self.assertEqual(3, len(selected))
        self.assertIn("with Ada at 68% match confidence", selected[0])
        self.assertIn("source ", selected[0])
        self.assertIn("song 0:00–0:04", selected[0])
        self.assertTrue(any(message.startswith("Scanning video") for message in messages))


if __name__ == "__main__":
    unittest.main()
