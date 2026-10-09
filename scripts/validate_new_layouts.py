"""Render short color fixtures in Resolve and inspect grid and expansion frames."""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))

from engine import Clip, probe, run
from resolve_adapter import render


def frame(path, seconds):
    raw, _ = run(["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(path),
                  "-frames:v", "1", "-vf", "scale=640:360", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
    def rgb(x, y):
        pos = (y * 640 + x) * 3
        return tuple(raw[pos:pos + 3])
    return rgb


with tempfile.TemporaryDirectory(prefix="pmv-layouts-") as folder:
    root = Path(folder)
    colors = ["red", "green", "blue", "yellow"]
    videos = []
    for color in colors:
        path = root / f"{color}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             f"color={color}:size=640x360:rate=30:duration=5", "-c:v", "libx264",
             "-preset", "ultrafast", str(path)])
        videos.append(path)
    audio = root / "song.wav"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
         "-c:a", "pcm_s16le", str(audio)])

    def make(role, expansion=False):
        count = 4 if role == "grid" else 3
        clips = [Clip(i + 1, str(videos[i]), 0, 2, 0, i, None, False, .5,
                      layout_role=role) for i in range(count)]
        if expansion:
            clips.extend(Clip(i + 1, str(videos[i]), 2, .5, 2, i, None, False, .5,
                              layout_role=role, underlay=True) for i in range(count))
            chosen = count - 1
            clips.append(Clip(chosen + 1, str(videos[chosen]), 2, 2, 2, 0, None, False, .5,
                              layout_role="full-screen", expansion_from=chosen,
                              expansion_duration=.5, expansion_layout=role))
        return clips

    for role, expansion in (("grid", False), ("grid", True), ("three-pane", True)):
        name = f"{role}-{'expansion' if expansion else 'plain'}"
        output = root / f"{name}.mp4"
        options = {"layoutModes": [role, "full-screen"] if expansion else [role], "selectionMode": "center",
                   "style": "rhythmic-polish", "colorTreatment": "natural", "transitionFamilies": ["cut"]}
        print("Rendering", name, flush=True)
        render(make(role, expansion), str(audio), str(output), 640, 360, 30, options, "",
               threading.Event(), lambda pct, msg: print(f"{pct:.0f}% {msg}", flush=True),
               require_validation=False)
        assert float(probe(output)["format"]["duration"]) >= (3.9 if expansion else 1.9)
        pixels = frame(output, 1)
        sample = [(160, 90), (480, 90), (160, 270), (480, 270)] if role == "grid" else [
            (105, 180), (320, 180), (535, 180)]
        print(name, "cells:", [pixels(*point) for point in sample], flush=True)
        if expansion:
            middle = [frame(output, 2.25)(*point) for point in sample]
            full = [frame(output, 3)(*point) for point in sample]
            print(name, "expansion 2.25s:", middle, flush=True)
            print(name, "full 3s:", full, flush=True)
            assert all(max(abs(a - b) for a, b in zip(pixel, full[0])) < 10 for pixel in full)
            expected = (252, 252, 0) if role == "grid" else (0, 0, 254)
            assert max(abs(a - b) for a, b in zip(full[0], expected)) < 15
