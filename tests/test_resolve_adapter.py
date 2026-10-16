import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
import resolve_adapter
from resolve_adapter import MediaImportError, ffmpeg_av1_encoder, import_media_items, select_mp4_codec, select_render_profile, set_item_property, source_frame_range


class TimelinePropertyTests(unittest.TestCase):
    def test_import_retries_a_missing_media_pool_file(self):
        class Item:
            def __init__(self, path):
                self.path = path
            def GetClipProperty(self, key):
                self.assert_key = key
                return self.path

        first, second = "C:/media/first.mp4", "C:/media/second.mp4"
        calls = []

        def add(rows):
            calls.append([row["media"] for row in rows])
            return [Item(first)] if len(rows) == 2 else [Item(second)]

        storage = SimpleNamespace(AddItemListToMediaPool=add)
        folder = SimpleNamespace(GetClipList=lambda: [])
        with patch("resolve_adapter.time.sleep"):
            items = import_media_items(storage, folder, [first, second], threading.Event(), lambda *_: None)
        self.assertEqual(2, len(items))
        self.assertEqual([[first, second], [second]], calls)

    def test_import_failure_names_missing_path_without_property_dump(self):
        missing = "C:/media/missing.mp4"
        storage = SimpleNamespace(AddItemListToMediaPool=lambda _rows: [])
        folder = SimpleNamespace(GetClipList=lambda: [])
        with patch("resolve_adapter.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "missing.mp4") as failure:
                import_media_items(storage, folder, [missing], threading.Event(), lambda *_: None)
        self.assertLess(len(str(failure.exception)), 1000)
        self.assertIsInstance(failure.exception, MediaImportError)
        self.assertEqual([missing], failure.exception.missing)
        self.assertEqual({}, failure.exception.imported)

    def test_connect_starts_resolve_when_it_is_closed(self):
        resolve = SimpleNamespace(GetVersionString=lambda: "21.1.1", GetProductName=lambda: "DaVinci Resolve Studio")
        api = SimpleNamespace(scriptapp=unittest.mock.Mock(side_effect=[None, None, resolve]))
        with patch.dict(sys.modules, {"DaVinciResolveScript": api}), \
                patch.object(resolve_adapter, "_auto_launch_supported", return_value=True), \
                patch.object(resolve_adapter, "_resolve_running", return_value=False), \
                patch.object(resolve_adapter, "_launch_resolve") as launch, \
                patch.object(resolve_adapter.time, "sleep"):
            self.assertIs(resolve, resolve_adapter.connect(require_validation=False, allow_launch=True))
            launch.assert_called_once()

    def test_passive_connect_does_not_launch_closed_resolve(self):
        api = SimpleNamespace(scriptapp=lambda _name: None)
        with patch.dict(sys.modules, {"DaVinciResolveScript": api}), \
                patch.object(resolve_adapter, "_auto_launch_supported", return_value=True), \
                patch.object(resolve_adapter, "_resolve_running", return_value=False), \
                patch.object(resolve_adapter, "_launch_resolve") as launch:
            with self.assertRaisesRegex(RuntimeError, "not running"):
                resolve_adapter.connect(require_validation=False)
            launch.assert_not_called()

    def test_connect_does_not_start_another_running_resolve(self):
        api = SimpleNamespace(scriptapp=lambda _name: None)
        with patch.dict(sys.modules, {"DaVinciResolveScript": api}), \
                patch.object(resolve_adapter, "_auto_launch_supported", return_value=True), \
                patch.object(resolve_adapter, "_resolve_running", return_value=True), \
                patch.object(resolve_adapter, "_launch_resolve") as launch:
            with self.assertRaisesRegex(RuntimeError, "Resolve is running"):
                resolve_adapter.connect(require_validation=False)
            launch.assert_not_called()

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

    def test_rejected_resolve_av1_uses_hardware_encoder_and_dnxhr(self):
        class Project:
            def GetRenderCodecs(self, format_name):
                return ({"AV1 8-bit - NVIDIA": "AV1YUV420_8_NVIDIA"} if format_name == "mp4"
                        else {"Avid DNxHR HQX 10-bit": "DNxHRHQX_10"})
            def SetCurrentRenderFormatAndCodec(self, _format, codec):
                return codec == "DNxHRHQX_10"
        with patch("resolve_adapter.ffmpeg_av1_encoder", return_value=("av1_nvenc", ["-preset", "p5"])):
            profile = select_render_profile(Project(), "av1")
        self.assertTrue(profile["intermediate"])
        self.assertEqual("mov", profile["format"])
        self.assertEqual("av1_nvenc", profile["encoder"])

    def test_av1_probe_never_chooses_a_cpu_encoder(self):
        trial = SimpleNamespace(returncode=1, stderr=b"NVIDIA encoder unavailable")
        with patch("resolve_adapter.subprocess.run", return_value=trial) as run:
            with self.assertRaisesRegex(RuntimeError, "NVIDIA AV1 hardware encoding failed"):
                ffmpeg_av1_encoder()
        self.assertIn("av1_nvenc", run.call_args.args[0])
        self.assertNotIn("libsvtav1", run.call_args.args[0])

    def test_resolve_software_av1_is_not_selected(self):
        project = SimpleNamespace(GetRenderCodecs=lambda _format: {"AV1 software": "AV1_CPU"})
        with self.assertRaisesRegex(RuntimeError, "does not offer AV1"):
            select_mp4_codec(project, "av1", apply=True)


if __name__ == "__main__":
    unittest.main()
