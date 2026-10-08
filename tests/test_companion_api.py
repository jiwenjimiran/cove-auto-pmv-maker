import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
import server


class CompanionApiTests(unittest.TestCase):
    def test_authenticated_preflight_rejects_missing_media_and_accepts_paths(self):
        server.TOKEN = "a" * 32
        listener = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{listener.server_port}"
        try:
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


if __name__ == "__main__":
    unittest.main()
