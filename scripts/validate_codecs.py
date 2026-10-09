"""Render short MP4 fixtures with each selectable Resolve codec."""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))

from engine import Clip, probe, run
from resolve_adapter import render


with tempfile.TemporaryDirectory(prefix="pmv-codecs-") as folder:
    root = Path(folder)
    video = root / "source.mp4"
    audio = root / "song.wav"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=640x360:rate=30:duration=2", "-c:v", "libx264", str(video)])
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=2", "-c:a", "pcm_s16le", str(audio)])
    clip = Clip(1, str(video), 0, 2, 0, 0, None, False, .5, layout_role="full-screen")
    for codec, expected in (("h264", "h264"), ("h265", "hevc"), ("av1", "av1")):
        output = root / f"{codec}.mp4"
        print(f"Rendering {codec}", flush=True)
        options = {"layoutModes": ["full-screen"], "outputCodec": codec,
                   "style": "rhythmic-polish", "colorTreatment": "natural",
                   "transitionFamilies": ["cut"]}
        try:
            render([clip], str(audio), str(output), 640, 360, 30, options, "",
                   threading.Event(), lambda pct, msg: print(f"{pct:.0f}% {msg}", flush=True),
                   require_validation=False)
        except RuntimeError as exc:
            if codec == "av1" and "rejected every available AV1 encoder" in str(exc):
                print(f"AV1 unavailable on this Resolve installation: {exc}", flush=True)
                continue
            raise
        stream = next(s for s in probe(output)["streams"] if s["codec_type"] == "video")
        print(f"{codec}: {stream['codec_name']}, {output.stat().st_size} bytes", flush=True)
        assert stream["codec_name"] == expected
