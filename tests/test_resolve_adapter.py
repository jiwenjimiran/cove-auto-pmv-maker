import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
from resolve_adapter import select_mp4_codec, set_item_property, source_frame_range


class TimelinePropertyTests(unittest.TestCase):
    def setUp(self):
        self.clip = SimpleNamespace(video_id=42, path="example.mp4", record_start=12.5, source_start=7.0)

    def test_retries_new_resolve_setter_after_timeline_item_initializes(self):
        class Item:
            attempts = 0
            def SetProperties(self, properties):
                self.attempts += 1
                return self.attempts == 3
            def GetProperties(self):
                return {"Scaling": 0, "RetimeAndScalingEnabled": True}

        item = Item()
        with patch("resolve_adapter.time.sleep"):
            set_item_property(item, "Scaling", 3.0, "pane scaling", self.clip, 2)
        self.assertEqual(item.attempts, 3)

    def test_project_fill_fallback_and_diagnostic_when_property_is_unavailable(self):
        class Item:
            def SetProperties(self, properties):
                return False
            def GetProperties(self):
                return {"Scaling": 0, "Pan": 0, "RetimeAndScalingEnabled": True}

        with patch("resolve_adapter.time.sleep"):
            set_item_property(Item(), "Scaling", 3.0, "pane scaling", self.clip, 2, project_fill=True)
            with self.assertRaisesRegex(RuntimeError, r"video 42 .*track 2.*Pan=100"):
                set_item_property(Item(), "Pan", 100, "pane position", self.clip, 2, project_fill=True)

    def test_older_resolve_uses_legacy_setter(self):
        class Item:
            def __init__(self):
                self.properties = {"Scaling": 0}
            def SetProperty(self, key, value):
                self.properties[key] = value
                return True
            def GetProperty(self):
                return self.properties

        item = Item()
        set_item_property(item, "Scaling", 3.0, "pane scaling", self.clip, 1)
        self.assertEqual(item.properties["Scaling"], 3.0)

    def test_source_ranges_use_source_fps_not_timeline_fps(self):
        start, end = source_frame_range(14.71, 0, 2.0, 23.976, 51306)
        self.assertEqual((start, end), (353, 401))
        self.assertNotEqual(start, round(14.71 * 30))

    def test_source_range_stays_inside_last_frame(self):
        self.assertEqual(source_frame_range(9, 0, 1, 24, 240), (216, 239))
        with self.assertRaisesRegex(ValueError, "outside the video"):
            source_frame_range(10, 0, 1, 24, 240)

    def test_mp4_codecs_use_resolve_identifiers_and_prefer_av1_eight_bit(self):
        class Project:
            def GetRenderCodecs(self, format_name):
                self_format = format_name
                assert self_format == "mp4"
                return {"AV1 10-bit - NVIDIA": "AV1YUV420_10_NVIDIA",
                        "AV1 8-bit - NVIDIA": "AV1YUV420_8_NVIDIA",
                        "H.264": "H264", "H.265": "H265"}
        project = Project()
        self.assertEqual("H264", select_mp4_codec(project, "h264")[1])
        self.assertEqual("H265", select_mp4_codec(project, "h265")[1])
        self.assertEqual("AV1YUV420_8_NVIDIA", select_mp4_codec(project, "av1")[1])

    def test_unavailable_codec_explains_available_choices(self):
        project = SimpleNamespace(GetRenderCodecs=lambda _format: {"H.264": "H264"})
        with self.assertRaisesRegex(RuntimeError, "does not offer AV1.*Available MP4 codecs: H.264"):
            select_mp4_codec(project, "av1")

    def test_listed_but_rejected_codec_fails_before_render(self):
        project = SimpleNamespace(
            GetRenderCodecs=lambda _format: {"AV1 8-bit - NVIDIA": "AV1YUV420_8_NVIDIA"},
            SetCurrentRenderFormatAndCodec=lambda _format, _codec: False)
        with self.assertRaisesRegex(RuntimeError, "lists AV1.*rejected every available AV1 encoder"):
            select_mp4_codec(project, "av1", apply=True)


if __name__ == "__main__":
    unittest.main()
