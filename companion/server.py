"""Run in the signed-in Windows session: python server.py --token <random-secret>."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
import traceback
import uuid
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from engine import audio_duration, beat_grid, choose_format, edit_plan, mix_audio, output_stem, prepare_audio, reserve_output
from resolve_adapter import connect, render

JOBS = {}
LOCK = threading.Lock()
RENDER_LOCK = threading.Lock()
TOKEN = ""


def health():
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        return {"ok": False, "error": "Missing tools: " + ", ".join(missing)}
    try:
        resolve = connect()
        product = resolve.GetProductName()
        version = resolve.GetVersionString()
        if "Studio" not in product:
            return {"ok": False, "error": "DaVinci Resolve Studio is required", "product": product, "version": version}
        return {"ok": True, "product": product, "version": version, "ytDlp": shutil.which("yt-dlp") is not None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def preflight(payload):
    sources = payload.get("sources") or []
    if not sources:
        raise ValueError("Select at least one source video")
    for source in sources:
        path = source.get("path", "")
        if not Path(path).is_file():
            raise ValueError("Resolve cannot read source: " + path)
    audio = payload.get("audio") or {}
    if audio.get("kind") == "youtube":
        if shutil.which("yt-dlp") is None:
            raise ValueError("yt-dlp is required for YouTube audio")
    elif not Path(audio.get("path", "")).is_file():
        raise ValueError("Resolve cannot read backing audio: " + audio.get("path", ""))
    folder = Path(payload.get("outputFolder") or "")
    if not folder.is_absolute():
        raise ValueError("Output folder must be absolute")
    folder.mkdir(parents=True, exist_ok=True)
    if not os.access(folder, os.W_OK):
        raise ValueError("Output folder is not writable")
    if payload.get("projectFolder"):
        project_folder = Path(payload["projectFolder"])
        if not project_folder.is_absolute():
            raise ValueError("Project folder must be absolute")
        project_folder.mkdir(parents=True, exist_ok=True)
    return sources


def do_job(job_id, payload):
    state = JOBS[job_id]
    cancelled = state["cancelEvent"]
    marker = None
    output_path = None

    def update(progress, message):
        state.update(progress=progress, message=message)

    with RENDER_LOCK:
        try:
            if cancelled.is_set():
                raise InterruptedError("Cancelled before starting")
            state["state"] = "running"
            update(1, "Checking Resolve and media paths")
            status = health()
            if not status["ok"]:
                raise RuntimeError(status["error"])
            sources = preflight(payload)
            options = payload.get("options") or {}
            options["layout"] = options.get("layout", "three-pane")
            width, height, fps = choose_format(sources, options["layout"], options)
            with TemporaryDirectory(prefix="pmvmaker-") as temp:
                update(5, "Preparing backing song")
                song = prepare_audio(payload["audio"], temp, cancelled)
                full = audio_duration(song)
                trim_start = float(options.get("songTrimStart") or 0)
                trim_end = float(options.get("songTrimEnd") or full)
                if trim_start < 0 or trim_end > full or trim_end - trim_start < 2:
                    raise ValueError("Song trim must leave at least two seconds")
                update(12, "Analyzing beats and phrases")
                beats = beat_grid(song, trim_start, trim_end, cancelled)
                update(25, "Analyzing source footage")
                clips = edit_plan(sources, beats, options, options["layout"], cancelled)
                if cancelled.is_set():
                    raise InterruptedError("Cancelled")
                used_video_ids = sorted({c.video_id for c in clips})
                used_segment_ids = sorted({c.segment_id for c in clips if c.segment_id is not None})
                stem = output_stem(sources, clips, payload.get("launchName"))
                output_path, marker = reserve_output(payload["outputFolder"], stem, payload.get("projectFolder", ""),
                                                     bool(options.get("saveProject")))
                update(40, "Mixing source accents and backing song")
                mix = mix_audio(song, clips, options, temp, beats[-1], trim_start, cancelled)
                update(52, "Building Resolve timeline")
                render(clips, mix, output_path, width, height, fps, options, payload.get("projectFolder", ""), cancelled, update)
                state.update(state="complete", progress=100, message="PMV rendered", outputPath=output_path,
                             usedVideoIds=used_video_ids, usedSegmentIds=used_segment_ids)
        except InterruptedError:
            state.update(state="cancelled", message="Render cancelled")
        except Exception as exc:
            state.update(state="failed", error=str(exc), message="Render failed")
            traceback.print_exc()
        finally:
            if marker:
                marker.unlink(missing_ok=True)
            if output_path and state["state"] != "complete":
                Path(output_path).unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        raw = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        import hmac
        bearer = self.headers.get("Authorization", "")
        if not hmac.compare_digest(bearer, "Bearer " + TOKEN):
            self.reply(401, {"error": "Unauthorized"})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        path = urlparse(self.path).path
        if path == "/health":
            return self.reply(200, health())
        if path.startswith("/jobs/"):
            state = JOBS.get(path.split("/")[-1])
            if state is None:
                return self.reply(404, {"error": "Job not found"})
            return self.reply(200, {k: v for k, v in state.items() if k != "cancelEvent"})
        self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if not self.authorized():
            return
        path = urlparse(self.path).path
        if path not in ("/jobs", "/preflight"):
            return self.reply(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4_000_000:
                raise ValueError("Invalid job size")
            payload = json.loads(self.rfile.read(length))
            preflight(payload)
            if path == "/preflight":
                return self.reply(200, {"ok": True})
            job_id = uuid.uuid4().hex
            state = {"id": job_id, "state": "queued", "progress": 0, "message": "Queued",
                     "outputPath": None, "usedVideoIds": [], "usedSegmentIds": [], "error": None,
                     "cancelEvent": threading.Event()}
            JOBS[job_id] = state
            threading.Thread(target=do_job, args=(job_id, payload), daemon=True).start()
            self.reply(202, {k: v for k, v in state.items() if k != "cancelEvent"})
        except Exception as exc:
            self.reply(400, {"error": str(exc)})

    def do_DELETE(self):
        if not self.authorized():
            return
        path = urlparse(self.path).path
        if not path.startswith("/jobs/"):
            return self.reply(404, {"error": "Not found"})
        state = JOBS.get(path.split("/")[-1])
        if state is None:
            return self.reply(404, {"error": "Job not found"})
        state["cancelEvent"].set()
        self.reply(202, {"message": "Cancellation requested"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=os.environ.get("COVE_PMV_TOKEN", ""))
    args = parser.parse_args()
    if len(args.token) < 24:
        parser.error("Provide a random token of at least 24 characters via --token or COVE_PMV_TOKEN")
    TOKEN = args.token
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
