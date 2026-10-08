import json
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
import server


class CompanionApiTests(unittest.TestCase):
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
