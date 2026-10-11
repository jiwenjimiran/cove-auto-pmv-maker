import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))

from engine import Clip, probe, run
from media_compat import prepare_resolve_clips, remux_rejected_containers
import server


class MediaCompatibilityTests(unittest.TestCase):
    def test_selected_wmv_ranges_become_importable_h264_mp4(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "E030 - Sandra.WMV"
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
                 "-t", "5", "-c:v", "wmv2", str(source)])
            clips = [Clip(1, str(source), 0.5, 1.5, 0, 0, None, False),
                     Clip(1, str(source), 1.2, 1.0, 2, 0, None, False),
                     Clip(1, str(source), 3.5, 1.0, 4, 0, None, False)]
            original_size = source.stat().st_size
            messages = []
            converted = prepare_resolve_clips(clips, Path(root) / "converted", threading.Event(),
                                              lambda _, message: messages.append(message))
            self.assertEqual(2, len(list((Path(root) / "converted").glob("*.mp4"))))
            self.assertEqual(converted[0].path, converted[1].path)
            self.assertNotEqual(converted[1].path, converted[2].path)
            self.assertAlmostEqual(converted[0].source_start, 0)
            self.assertAlmostEqual(converted[1].source_start, 0.7)
            self.assertAlmostEqual(converted[2].source_start, 0)
            self.assertEqual(source.stat().st_size, original_size)
            for clip in converted:
                info = probe(clip.path)
                self.assertEqual("h264", next(s["codec_name"] for s in info["streams"]
                                              if s["codec_type"] == "video"))
                self.assertGreaterEqual(float(info["format"]["duration"]),
                                        clip.source_start + clip.duration - 0.1)
            self.assertTrue(any("Re-encoding Windows Media range" in message for message in messages))

    def test_job_keeps_project_media_and_cleans_temporary_media(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "source.wmv"
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25",
                 "-t", "4", "-c:v", "wmv2", str(source)])
            song = root / "song.wav"
            song.write_bytes(b"song fixture")
            output_folder, project_folder = root / "output", root / "projects"
            output_folder.mkdir()
            project_folder.mkdir()
            converted_paths = []

            def mix(_song, _clips, _options, temp, *_args):
                path = Path(temp) / "mix.wav"
                path.write_bytes(b"mix fixture")
                return str(path)

            def worker(clips, audio_path, output_path, *_args, **_kwargs):
                self.assertEqual(1, len(clips))
                self.assertTrue(Path(clips[0].path).is_file())
                self.assertTrue(Path(audio_path).is_file())
                converted_paths.append((Path(clips[0].path), Path(audio_path)))
                Path(output_path).write_bytes(b"render fixture")

            for save_project in (False, True):
                job_id = "abc12345" if save_project else "def12345"
                state = {"cancelEvent": threading.Event(), "eventLock": threading.Lock(),
                         "eventSequence": 0, "events": [], "state": "queued", "progress": 0}
                server.JOBS[job_id] = state
                options = {"layout": "full-screen", "layoutModes": ["full-screen"],
                           "saveProject": save_project, "reencodeIncompatibleContainers": True}
                payload = {"sources": [{"id": 1, "path": str(source), "duration": 4, "width": 160,
                                        "height": 120, "fps": 25, "segments": []}],
                           "audio": {"kind": "cove", "path": str(song)}, "options": options,
                           "outputFolder": str(output_folder), "projectFolder": str(project_folder),
                           "skipSetupChecks": True}
                try:
                    with patch.object(server, "health", return_value={"ok": True}), \
                            patch.object(server, "audio_duration", return_value=2), \
                            patch.object(server, "beat_grid", return_value=[0, 2]), \
                            patch.object(server, "mix_audio", side_effect=mix), \
                            patch.object(server, "run_resolve_worker", side_effect=worker), \
                            patch("advanced_edit.edit_plan", return_value=[
                                Clip(1, str(source), 0.5, 2, 0, 0, None, False)]):
                        server.do_job(job_id, payload)
                    self.assertEqual("complete", state["state"], state.get("error"))
                    video_path, audio_path = converted_paths[-1]
                    self.assertEqual(save_project, video_path.exists())
                    self.assertEqual(save_project, audio_path.exists())
                    self.assertTrue(Path(state["outputPath"]).exists())
                finally:
                    server.JOBS.pop(job_id, None)

    def test_misnamed_hevc_is_remuxed_without_reencoding(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "HEVC Scene.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=24",
                 "-t", "5", "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error",
                 "-f", "matroska", str(source)])
            original_size = source.stat().st_size
            clip = Clip(9, str(source), 2, 1.5, 0, 0, None, False)
            messages = []
            repaired, paths = remux_rejected_containers([clip], [str(source)], root / "repaired",
                                                        threading.Event(),
                                                        lambda _, message: messages.append(message))
            self.assertEqual(1, len(paths))
            self.assertNotEqual(repaired[0].path, str(source))
            self.assertEqual(original_size, source.stat().st_size)
            result = probe(repaired[0].path)
            self.assertIn("mp4", result["format"]["format_name"])
            self.assertEqual("hevc", next(s["codec_name"] for s in result["streams"]
                                          if s["codec_type"] == "video"))
            self.assertLess(float(result["format"]["start_time"]), 0.2)
            self.assertGreaterEqual(float(result["format"]["duration"]),
                                    repaired[0].source_start + repaired[0].duration - 0.1)
            self.assertFalse(list((root / "repaired").glob("*-raw.mp4")))
            self.assertTrue(any("without re-encoding" in message for message in messages))

    def test_rejected_mp4_with_matching_container_is_not_remuxed(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "normal.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=24",
                 "-t", "2", "-c:v", "libx264", str(source)])
            clip = Clip(10, str(source), 0.2, 1, 0, 0, None, False)
            repaired, paths = remux_rejected_containers([clip], [str(source)], Path(root) / "repaired",
                                                        threading.Event(), lambda *_: None)
            self.assertEqual([], list(paths))
            self.assertIs(clip, repaired[0])


if __name__ == "__main__":
    unittest.main()
