"""Short Resolve Studio prototype for the full-height mirrored portrait pair."""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))

from engine import Clip, probe, run
from resolve_adapter import render


with tempfile.TemporaryDirectory(prefix="pmv-mirror-") as folder:
    root = Path(folder)
    pair = root / "pair.mp4"
    center = root / "center.mp4"
    audio = root / "song.wav"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:size=640x720:rate=30:duration=3",
         "-f", "lavfi", "-i", "color=blue:size=640x720:rate=30:duration=3",
         "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]", "-map", "[v]", "-c:v", "libx264",
         "-preset", "ultrafast", str(pair)])
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=green:size=1280x720:rate=30:duration=3",
         "-c:v", "libx264", "-preset", "ultrafast", str(center)])
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:a", "pcm_s16le", str(audio)])
    clips = [Clip(1, str(pair), 0, 3, 0, 0, None, False, .5),
             Clip(2, str(center), 0, 3, 0, 1, None, False, .5),
             Clip(1, str(pair), 0, 3, 0, 2, None, False, .5, (), None, True)]
    output = root / "mirror.mp4"
    options = {"layout": "three-pane", "selectionMode": "face", "style": "rhythmic-polish",
               "colorTreatment": "natural", "transitionFamilies": ["cut"]}
    render(clips, str(audio), str(output), 1920, 1080, 30, options, "", threading.Event(),
           lambda percent, message: print(f"{percent:.0f}% {message}"), require_validation=False)
    info = probe(output)
    assert float(info["format"]["duration"]) > 2.8
    raw, _ = run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(output), "-frames:v", "1",
                  "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
    def pixel(x, y):
        return tuple(raw[(y * 1920 + x) * 3:(y * 1920 + x) * 3 + 3])
    print("left", pixel(480, 540), "center", pixel(960, 540), "right", pixel(1760, 540))
    if pixel(480, 540) == pixel(1760, 540):
        raise RuntimeError("Resolve did not mirror the repeated outside pane")
