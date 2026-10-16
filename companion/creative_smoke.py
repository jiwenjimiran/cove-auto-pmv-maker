"""Real media/Resolve fixture for all creative effect families and pane layouts."""
from pathlib import Path
import threading
from dataclasses import replace

from creative_edit import direct, prepare_creative_clips, time_knots
from engine import Clip, probe, run
from music_analysis import BeatGrid
from resolve_adapter import render


def check_creative(root, progress=None):
    import numpy as np
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cancel = threading.Event()
    sources = []
    for i in range(4):
        path = root / f"creative-source-{i}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=10",
             "-f", "lavfi", "-i", f"sine=frequency={220+i*100}:duration=10",
             "-vf", f"hue=h={i*50}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)])
        sources.append(path)
    song = root / "creative-song.wav"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=12", str(song)])
    beats = BeatGrid([i * .5 for i in range(25)], tempo=120,
                     strengths=[(i*.5, 1) for i in range(25)], energy=[(0, .9)])
    options = {"sourceAudio": "all", "style": "high-energy", "outputCodec": "h264",
               "transitionFamilies": ["cut"], "creativeManaged": True}
    results = []
    for role in ("full-screen", "grid", "three-pane"):
        count = 6 if role == "full-screen" else 4 if role == "grid" else 3
        clips = [Clip(i + 1, str(sources[i % 4]), .5, 2, i*2 if role == "full-screen" else 0,
                      0 if role == "full-screen" else i, None, True, layout_role=role) for i in range(count)]
        clips, plans = direct(clips, beats, options)
        for i, plan in enumerate(plans):
            plan["dominant"] = ("beatPunch", "impactRecoil", "speedRamps", "motionEcho", "rgbSplit", "freezeAccents")[i % 6]
            plan["hits"] = [(.25, 1), (1.25, 1)]
            plan["bloom"] = True
            plan["knots"] = time_knots(2, plan["hits"], plan["cue"], options, plan["dominant"])
        prepared = prepare_creative_clips(clips, plans, options, root / role, 30, cancel, progress or (lambda *_: None))
        output = root / f"creative-{role}.mp4"
        render(prepared, str(song), str(output), 640, 360, 30, dict(options, layoutModes=[role]), "", cancel,
               progress or (lambda *_: None), require_validation=False)
        info = probe(output)
        expected = 12 if role == "full-screen" else 2
        if abs(float(info["format"]["duration"]) - expected) > .15:
            raise RuntimeError(f"Creative {role} duration was incorrect")
        raw, _ = run(["ffmpeg", "-v", "error", "-ss", "0.7", "-i", str(output), "-frames:v", "1",
                      "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
        frame = np.frombuffer(raw, np.uint8).reshape(360, 640, 3)
        cells = [frame] if role == "full-screen" else [frame[:, i*640//3:(i+1)*640//3] for i in range(3)] if role == "three-pane" else [frame[y:y+180, x:x+320] for y in (0,180) for x in (0,320)]
        if any(float(cell.mean()) < 10 or float(cell.std()) < 10 for cell in cells):
            raise RuntimeError(f"Creative {role} rendered an empty pane")
        results.append({"name": f"creative-{role}", "output": str(output), "duration": expected})
    return results


if __name__ == "__main__":
    import sys, json
    print(json.dumps(check_creative(sys.argv[1], lambda p, m: print(f"{p:.1f}% {m}", flush=True)), indent=2))
