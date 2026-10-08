"""Render short fixtures through Resolve Studio. Requires local scripting access."""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from engine import audio_duration, beat_grid, choose_format, edit_plan, mix_audio, probe, run
from resolve_adapter import VALIDATION, connect, render


def main():
    resolve = connect(require_validation=False)
    with tempfile.TemporaryDirectory(prefix="pmv-smoke-") as folder:
        root = Path(folder)
        song = root / "song.wav"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=240:duration=7",
             "-c:a", "pcm_s16le", str(song)])
        sources = []
        for number, color in enumerate(("red", "green", "blue", "yellow", "cyan", "magenta"), 1):
            video = root / f"source-{number}.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color={color}:size=720x1280:rate=30:duration=7",
                 "-f", "lavfi", "-i", f"sine=frequency={300 + number * 150}:duration=7", "-c:v", "mpeg4", "-c:a", "aac", str(video)])
            sources.append({"id": number, "path": str(video), "duration": 7, "width": 720, "height": 1280,
                            "fps": 30, "segments": [{"id": number, "start": 0, "end": 7}], "tagOnly": True})
        beats = beat_grid(str(song), 0, 7)
        checks = []
        for style in ("rhythmic-polish", "high-energy", "cinematic"):
            for layout in ("three-pane", "full-screen"):
                for mode in ("muted", "mixed", "all"):
                    name = f"{style}-{layout}-{mode}"
                    work = root / name
                    work.mkdir()
                    options = {"style": style, "layout": layout, "sourceAudio": mode,
                               "pacing": 0.5, "beatAdherence": 0.8, "minClipSeconds": 1,
                               "maxClipSeconds": 3, "saveProject": False, "transitionFamilies": ["cut", "dissolve"],
                               "transitionIntensity": 0.35, "motionIntensity": 0.6,
                               "flashIntensity": 0.35 if style == "high-energy" else 0,
                               "glitchIntensity": 0.25 if style == "high-energy" else 0,
                               "colorTreatment": {"rhythmic-polish": "matched", "high-energy": "cool", "cinematic": "warm"}[style]}
                    clips = edit_plan(sources, beats, options, layout)
                    audio = mix_audio(str(song), clips, options, str(work), 7)
                    width, height, fps = choose_format(sources, layout, options)
                    output = work / (name + ".mp4")
                    render(clips, audio, str(output), width, height, fps, options, "", threading.Event(),
                           lambda percent, message: print(f"{name}: {percent:.0f}% {message}"), require_validation=False)
                    media = probe(output)
                    streams = media["streams"]
                    video = next(s for s in streams if s["codec_type"] == "video")
                    sound = next(s for s in streams if s["codec_type"] == "audio")
                    if video["width"] != width or video["height"] != height or video["codec_name"] != "h264":
                        raise RuntimeError(f"Unexpected video format for {name}: {video}")
                    if sound["codec_name"] != "aac" or not 6.7 < float(media["format"]["duration"]) < 7.3:
                        raise RuntimeError(f"Unexpected audio or duration for {name}: {sound}")
                    if layout == "three-pane":
                        frame, _ = run(["ffmpeg", "-v", "error", "-ss", "0.2", "-i", str(output),
                                        "-frames:v", "1", "-s", f"{width}x{height}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
                        center_y = height // 2
                        colors = [frame[(center_y * width + x) * 3:(center_y * width + x) * 3 + 3]
                                  for x in (width // 6, width // 2, width * 5 // 6)]
                        if not (colors[0][0] > colors[0][1] * 1.5 and colors[1][1] > colors[1][0] * 1.5
                                and colors[2][2] > colors[2][0] * 1.5):
                            raise RuntimeError(f"Three-pane crop failed for {name}: {colors}")
                    _, peak_log = run(["ffmpeg", "-hide_banner", "-i", str(output), "-af", "volumedetect", "-vn", "-f", "null", "-"])
                    if b"max_volume:" not in peak_log:
                        raise RuntimeError(f"Audio peak measurement failed for {name}")
                    checks.append({"name": name, "output": str(output), "duration": media["format"]["duration"]})
        print(json.dumps({"studio": resolve.GetProductName(), "version": resolve.GetVersionString(), "renders": checks}, indent=2))
        print("Inspect beat cuts, transition smoothness, flash/glitch accents, crop edges, and audio peaks before cleanup.")
        if input("Type VALIDATED to enable this Resolve version: ").strip() == "VALIDATED":
            VALIDATION.write_text(json.dumps({"product": resolve.GetProductName(), "version": resolve.GetVersionString(),
                                              "renders": len(checks)}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
