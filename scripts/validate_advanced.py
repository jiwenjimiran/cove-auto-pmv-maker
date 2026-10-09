"""End-to-end Resolve fixture for scene sampling and pane cadence."""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))

from advanced_edit import edit_plan
from engine import choose_format, mix_audio, probe, run
from music_analysis import BeatGrid
from resolve_adapter import render


with tempfile.TemporaryDirectory(prefix="pmv-advanced-") as folder:
    root = Path(folder)
    song = root / "song.wav"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
         "-c:a", "pcm_s16le", str(song)])
    sources = []
    for ident, color in ((1, "red"), (2, "green")):
        video = root / f"video-{ident}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             f"color={color}:size=1280x720:rate=30:duration=8",
             "-f", "lavfi", "-i", f"sine=frequency={ident * 300}:duration=8",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", str(video)])
        sources.append({"id": ident, "path": str(video), "duration": 8,
                        "width": 1280, "height": 720, "fps": 30, "segments": [], "tagOnly": False})
    beats = BeatGrid([float(i) for i in range(9)], bars=(0, 2, 4, 6), phrases=(4,), meter=4)
    options = {"layout": "three-pane", "selectionMode": "center", "style": "rhythmic-polish",
               "sourceAudio": "mixed", "sampledClipsProgress": True, "mirrorRepeatedSource": True,
               "cycleLongerClipIntoSegments": True, "rotatedClipLengthSeconds": 8,
               "minClipSeconds": 1, "maxClipSeconds": 4, "transitionFamilies": ["cut"],
               "colorTreatment": "natural"}
    clips = edit_plan(sources, beats, options, "three-pane", progress=lambda percent, message: print(message))
    for when in (0, 2, 4, 6):
        panes = {pane: next(c for c in clips if c.pane == pane and c.record_start <= when < c.record_start + c.duration)
                 for pane in (0, 1, 2)}
        assert panes[0].video_id == panes[2].video_id != panes[1].video_id
        assert panes[0].source_start == panes[2].source_start
        assert panes[2].mirrored
    mixed = mix_audio(str(song), clips, options, str(root), 8)
    width, height, fps = choose_format(sources, "three-pane", options)
    output = root / "advanced.mp4"
    render(clips, mixed, str(output), width, height, fps, options, "", threading.Event(),
           lambda percent, message: print(f"{percent:.0f}% {message}"), require_validation=False)
    info = probe(output)
    assert float(info["format"]["duration"]) > 7.7
    print(f"Advanced edit rendered {len(clips)} clips at {width}x{height}/{fps}fps")
