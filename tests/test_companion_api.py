import json
import gzip
import sys
import tempfile
import threading
import time
import types
import unittest
from dataclasses import asdict
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
import server
import render_worker
from engine import Clip


class CompanionApiTests(unittest.TestCase):
    def test_render_worker_restores_face_tracks(self):
        clip = Clip(42, "source.mp4", 10.0, 3.0, 0.0, 0, None, False,
                    face_track=((0.0, 0.4), (2.0, 0.6)))
        with tempfile.TemporaryDirectory() as root, patch.object(render_worker, "render") as mocked:
            render_worker.run({"clips": [asdict(clip)], "audioPath": "song.wav",
                               "outputPath": "out.mp4", "width": 1920, "height": 1080,
                               "fps": 30, "options": {}, "projectFolder": "",
                               "cancelPath": str(Path(root) / "cancel"), "requireValidation": True})
            restored = mocked.call_args.args[0][0]
            self.assertEqual(clip, restored)

    def test_resolve_worker_keeps_companion_http_responsive(self):
        server.TOKEN = "a" * 32
        listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        serving = threading.Thread(target=listener.serve_forever, daemon=True)
        serving.start()
        try:
            with tempfile.TemporaryDirectory() as root:
                script = Path(root) / "fake_worker.py"
                script.write_text('import json, sys, time\n'
                                  'from pathlib import Path\n'
                                  'assert json.loads(Path(sys.argv[1]).read_text())["width"] == 1920\n'
                                  'print(json.dumps({"progress": 52.2, "message": "Importing media"}), flush=True)\n'
                                  'time.sleep(0.5)\n', encoding="utf-8")
                started = threading.Event()
                errors = []
                updates = []

                def progress(percent, message):
                    updates.append((percent, message))
                    started.set()

                def run():
                    try:
                        server.run_resolve_worker([], "song.wav", "out.mp4", 1920, 1080, 30,
                                                  {}, "", threading.Event(), progress, root,
                                                  worker_script=script)
                    except Exception as exc:
                        errors.append(exc)

                runner = threading.Thread(target=run)
                runner.start()
                self.assertTrue(started.wait(5), "Child process did not begin Resolve import")
                request = Request(f"http://127.0.0.1:{listener.server_port}/ready",
                                  headers={"Authorization": "Bearer " + server.TOKEN})
                self.assertTrue(json.load(urlopen(request, timeout=2))["ok"])
                runner.join(5)
                self.assertFalse(runner.is_alive())
                self.assertEqual([], errors)
                self.assertIn((52.2, "Importing media"), updates)
        finally:
            listener.shutdown()
            listener.server_close()

    def test_resolve_worker_failure_includes_child_error(self):
        with tempfile.TemporaryDirectory() as root:
            script = Path(root) / "failed_worker.py"
            script.write_text('import sys\nprint("Resolve import failed", file=sys.stderr)\nsys.exit(1)\n',
                              encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Resolve import failed"):
                server.run_resolve_worker([], "song.wav", "out.mp4", 1920, 1080, 30,
                                          {}, "", threading.Event(), lambda *_: None, root,
                                          worker_script=script)

    def test_resolve_worker_cancellation_reaches_child(self):
        with tempfile.TemporaryDirectory() as root:
            script = Path(root) / "cancel_worker.py"
            script.write_text('import json, sys, time\n'
                              'from pathlib import Path\n'
                              'cancel = Path(json.loads(Path(sys.argv[1]).read_text())["cancelPath"])\n'
                              'print(json.dumps({"progress": 52.2, "message": "Importing media"}), flush=True)\n'
                              'while not cancel.exists(): time.sleep(0.02)\n'
                              'sys.exit(2)\n', encoding="utf-8")
            cancelled = threading.Event()

            def progress(_percent, _message):
                cancelled.set()

            with self.assertRaises(InterruptedError):
                server.run_resolve_worker([], "song.wav", "out.mp4", 1920, 1080, 30,
                                          {}, "", cancelled, progress, root, worker_script=script)

    def test_gzipped_submission_retry_returns_original_job(self):
        server.TOKEN = "a" * 32
        server.JOBS.clear()
        server.SUBMISSION_IDS.clear()
        listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.server_port}"
        raw = json.dumps({"sources": [{"id": 1}], "padding": "x" * 5_000_000}).encode()
        self.assertGreater(len(raw), 4_000_000)
        payload = gzip.compress(raw)
        self.assertLess(len(payload), 4_000_000)
        headers = {"Authorization": "Bearer " + server.TOKEN,
                   "Content-Type": "application/json", "Content-Encoding": "gzip",
                   "X-PMV-Request-Id": "a" * 32}
        try:
            with patch.object(server, "preflight", return_value=[]) as preflight, \
                    patch.object(server, "do_job"):
                first = json.load(urlopen(Request(base + "/jobs", data=payload, method="POST", headers=headers), timeout=2))
                second = json.load(urlopen(Request(base + "/jobs", data=payload, method="POST", headers=headers), timeout=2))
                self.assertEqual(first["id"], second["id"])
                self.assertEqual(1, len(server.JOBS))
                preflight.assert_called_once()
        finally:
            listener.shutdown()
            listener.server_close()
            server.JOBS.clear()
            server.SUBMISSION_IDS.clear()

    def test_preflight_accepts_hardware_av1_when_resolve_rejects_native_codec(self):
        class Project:
            def GetRenderCodecs(self, format_name):
                return ({"AV1 8-bit - NVIDIA": "AV1YUV420_8_NVIDIA"} if format_name == "mp4"
                        else {"Avid DNxHR HQX 10-bit": "DNxHRHQX_10"})
            def GetCurrentRenderFormatAndCodec(self):
                return {}
            def SetCurrentRenderFormatAndCodec(self, _format, codec):
                return codec == "DNxHRHQX_10"
        project = Project()
        deleted = []
        manager = types.SimpleNamespace(
            GetCurrentProject=lambda: None,
            CreateProject=lambda _name: project,
            CloseProject=lambda _project: True,
            DeleteProject=lambda name: deleted.append(name))
        resolve = types.SimpleNamespace(GetProjectManager=lambda: manager)
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.mp4"
            audio = Path(root) / "song.wav"
            source.touch()
            audio.touch()
            payload = {"sources": [{"path": str(source)}], "audio": {"path": str(audio)},
                       "outputFolder": root, "outputCodec": "av1"}
            with patch.object(server, "connect", return_value=resolve), \
                    patch("resolve_adapter.ffmpeg_av1_encoder", return_value=("av1_nvenc", ["-preset", "p5"])):
                self.assertEqual(payload["sources"], server.preflight(payload))
        self.assertEqual(1, len(deleted))

    def test_job_diagnostics_have_ordered_cursor_and_bounded_history(self):
        state = {"id": "job", "state": "running", "progress": 33, "message": "Matching faces",
                 "cancelEvent": threading.Event(), "eventLock": threading.Lock(),
                 "eventSequence": 0, "events": []}
        server.log_job_event(state, "Scanning video 42")
        server.log_job_event(state, "Selected slice", "info")
        first = server.job_snapshot(state, 0)
        self.assertEqual([1, 2], [event["sequence"] for event in first["events"]])
        self.assertNotIn("cancelEvent", first)
        self.assertEqual([], server.job_snapshot(state, 2)["events"])
        for number in range(4001):
            server.log_job_event(state, f"event {number}")
        self.assertEqual(4000, len(state["events"]))
        expired = server.job_snapshot(state, 0)
        self.assertIn("expired", expired["events"][0]["message"])
        self.assertLessEqual(len(expired["events"]), 250)

    def test_face_reference_upload_is_authenticated_and_cleaned(self):
        server.TOKEN = "a" * 32
        listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.server_port}"
        try:
            with tempfile.TemporaryDirectory() as root, patch.object(server, "REFERENCE_ROOT", Path(root)):
                headers = {"Authorization": "Bearer " + server.TOKEN, "X-PMV-Performer-Id": "42"}
                with self.assertRaises(HTTPError) as denied:
                    urlopen(Request(base + "/references", data=b"portrait", method="POST"), timeout=2)
                self.assertEqual(401, denied.exception.code)
                denied.exception.close()
                reference_id = json.load(urlopen(Request(base + "/references", data=b"portrait", method="POST",
                                                        headers=headers), timeout=2))["referenceId"]
                self.assertEqual(b"portrait", (Path(root) / reference_id).read_bytes())
                result = server.face_references([{"performerId": 42, "referenceId": reference_id}])
                self.assertEqual(42, result[0]["performerId"])
                urlopen(Request(base + "/references/" + reference_id, method="DELETE", headers=headers), timeout=2)
                self.assertFalse((Path(root) / reference_id).exists())
        finally:
            listener.shutdown()
            listener.server_close()

    def test_validation_runs_from_authenticated_api(self):
        server.TOKEN = "a" * 32
        server.VALIDATION_STATE.update(state="idle", progress=0, message="Not run", error=None)
        listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.server_port}"
        headers = {"Authorization": "Bearer " + server.TOKEN}
        fake = types.ModuleType("smoke")
        fake.main = lambda automated, progress: progress(18, 18, "fixture")
        try:
            with patch.dict(sys.modules, {"smoke": fake}):
                request = Request(base + "/validation", data=b"", method="POST", headers=headers)
                self.assertIn(json.load(urlopen(request, timeout=2))["state"], ("queued", "running", "complete"))
                for _ in range(50):
                    state = json.load(urlopen(Request(base + "/validation", headers=headers), timeout=2))
                    if state["state"] == "complete":
                        break
                    time.sleep(0.02)
                self.assertEqual(state["state"], "complete")
                self.assertEqual(state["progress"], 100)
        finally:
            listener.shutdown()
            listener.server_close()

    def test_authenticated_preflight_rejects_missing_media_and_accepts_paths(self):
        server.TOKEN = "a" * 32
        listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.server_port}"
        try:
            with self.assertRaises(HTTPError) as denied_ready:
                urlopen(base + "/ready", timeout=2)
            self.assertEqual(denied_ready.exception.code, 401)
            denied_ready.exception.close()
            ready = Request(base + "/ready", headers={"Authorization": "Bearer " + server.TOKEN})
            self.assertTrue(json.load(urlopen(ready, timeout=2))["ok"])
            with tempfile.TemporaryDirectory() as root:
                source = Path(root) / "source.mp4"
                audio = Path(root) / "song.wav"
                source.write_bytes(b"fixture")
                audio.write_bytes(b"fixture")
                payload = {"sources": [{"path": str(source)}], "audio": {"kind": "cove", "path": str(audio)},
                           "outputFolder": str(Path(root) / "output")}

                def request(token):
                    return Request(base + "/preflight", data=json.dumps(payload).encode(), method="POST",
                                   headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})

                with self.assertRaises(HTTPError) as denied:
                    urlopen(request("bad"), timeout=2)
                self.assertEqual(denied.exception.code, 401)
                denied.exception.close()
                self.assertTrue(json.load(urlopen(request(server.TOKEN), timeout=2))["ok"])
                legacy = Path(root) / "E030 - Sandra.WMV"
                legacy.write_bytes(b"existing Windows Media fixture")
                payload["sources"] = [{"path": str(legacy)}]
                self.assertTrue(json.load(urlopen(request(server.TOKEN), timeout=2))["ok"])
                payload["options"] = {"reencodeIncompatibleContainers": False}
                with self.assertRaises(HTTPError) as unsupported:
                    urlopen(request(server.TOKEN), timeout=2)
                self.assertEqual(unsupported.exception.code, 400)
                self.assertIn("Windows Media", json.load(unsupported.exception)["error"])
                unsupported.exception.close()
                payload["sources"] = [{"path": str(source)}]
                source.unlink()
                with self.assertRaises(HTTPError) as missing:
                    urlopen(request(server.TOKEN), timeout=2)
                self.assertEqual(missing.exception.code, 400)
                missing.exception.close()
        finally:
            listener.shutdown()
            listener.server_close()

    def test_folder_picker_requires_auth_and_returns_dialog_selection(self):
        server.TOKEN = "a" * 32
        listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.server_port}"
        payload = json.dumps({"initialPath": "C:\\Music", "title": "Choose music folder"}).encode()
        try:
            with patch.object(server, "pick_folder", return_value={"path": "C:\\Music"}) as dialog:
                with self.assertRaises(HTTPError) as denied:
                    urlopen(Request(base + "/pick-folder", data=payload, method="POST"), timeout=2)
                self.assertEqual(denied.exception.code, 401)
                denied.exception.close()
                request = Request(base + "/pick-folder", data=payload, method="POST",
                                  headers={"Authorization": "Bearer " + server.TOKEN})
                self.assertEqual(json.load(urlopen(request, timeout=2))["path"], "C:\\Music")
                dialog.assert_called_once_with("C:\\Music", "Choose music folder")
        finally:
            listener.shutdown()
            listener.server_close()

    def test_uploaded_song_is_accepted_for_job_and_removed(self):
        server.TOKEN = "a" * 32
        listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.server_port}"
        headers = {"Authorization": "Bearer " + server.TOKEN, "X-PMV-Extension": ".mp3"}
        try:
            with tempfile.TemporaryDirectory() as root, patch.object(server, "UPLOAD_ROOT", Path(root)), \
                    patch.object(server, "audio_duration", return_value=10):
                request = Request(base + "/uploads", data=b"audio fixture", method="POST", headers=headers)
                upload_id = json.load(urlopen(request, timeout=2))["uploadId"]
                uploaded = server.uploaded_song(upload_id)
                self.assertEqual(uploaded.read_bytes(), b"audio fixture")
                source = Path(root) / "source.mp4"
                source.write_bytes(b"video fixture")
                payload = {"sources": [{"path": str(source)}], "audio": {"kind": "upload", "uploadId": upload_id},
                           "outputFolder": str(Path(root) / "output")}
                server.preflight(payload)
                self.assertEqual(payload["audio"]["path"], str(uploaded))
                delete = Request(base + "/uploads/" + upload_id, method="DELETE", headers=headers)
                self.assertTrue(json.load(urlopen(delete, timeout=2))["deleted"])
                self.assertFalse(uploaded.exists())
        finally:
            listener.shutdown()
            listener.server_close()


if __name__ == "__main__":
    unittest.main()
