"""Render short fixtures through Resolve Studio. Requires local scripting access."""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from engine import Clip, audio_duration, beat_grid, choose_format, edit_plan, mix_audio, probe, run
from resolve_adapter import VALIDATION, VALIDATION_SCHEMA, connect, render


def main(automated=False, progress=None, limit=None):
    resolve = connect(require_validation=False)
    if not resolve.GetProjectManager().GetCurrentDatabase():
        raise RuntimeError("Resolve has no active project library. Open an editable project from a local library in Resolve, then retry the compatibility check.")
    with tempfile.TemporaryDirectory(prefix="pmv-smoke-") as folder:
        root = Path(folder)
        song = root / "song.wav"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=240:duration=7",
             "-c:a", "pcm_s16le", str(song)])
        sources = []
        for number, color in enumerate(("red", "green", "blue", "yellow", "cyan", "magenta"), 1):
            video = root / f"source-{number}.mp4"
            source_width, source_height = (720, 1280) if number <= 3 else (1280, 720)
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color={color}:size={source_width}x{source_height}:rate=30:duration=7",
                 "-f", "lavfi", "-i", f"sine=frequency={300 + number * 150}:duration=7",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)])
            sources.append({"id": number, "path": str(video), "duration": 7, "width": source_width, "height": source_height,
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
                    if abs(width / height - 16 / 9) > 0.01:
                        raise RuntimeError(f"Expected a landscape 16:9 frame for {name}: {width}x{height}")
                    if sound["codec_name"] != "aac" or not 6.7 < float(media["format"]["duration"]) < 7.3:
                        raise RuntimeError(f"Unexpected audio or duration for {name}: {sound}")
                    if layout == "three-pane":
                        frame, _ = run(["ffmpeg", "-v", "error", "-ss", "0.2", "-i", str(output),
                                        "-frames:v", "1", "-s", f"{width}x{height}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
                        center_y = height // 2
                        colors = [frame[(center_y * width + x) * 3:(center_y * width + x) * 3 + 3]
                                  for x in (width // 30, width * 3 // 10, width * 11 // 30,
                                            width * 19 // 30, width * 7 // 10, width * 29 // 30)]
                        if not (all(color[0] > color[1] * 1.5 and color[0] > color[2] * 1.5 for color in colors[:2])
                                and all(color[1] > color[0] * 1.5 and color[1] > color[2] * 1.5 for color in colors[2:4])
                                and all(color[2] > color[0] * 1.5 and color[2] > color[1] * 1.5 for color in colors[4:])):
                            raise RuntimeError(f"Three-pane crop failed for {name}: {colors}")
                        second_time = clips[3].record_start + clips[3].duration / 2
                        later, _ = run(["ffmpeg", "-v", "error", "-ss", str(second_time), "-i", str(output),
                                        "-frames:v", "1", "-s", f"{width}x{height}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
                        later_colors = [later[(center_y * width + x) * 3:(center_y * width + x) * 3 + 3]
                                        for x in (width // 6, width // 2, width * 5 // 6)]
                        if not (later_colors[0][0] > 70 and later_colors[0][1] > 70 and later_colors[0][2] < 50
                                and later_colors[1][0] < 50 and later_colors[1][1] > 70 and later_colors[1][2] > 70
                                and later_colors[2][0] > 70 and later_colors[2][1] < 50 and later_colors[2][2] > 70):
                            raise RuntimeError(f"Landscape sources did not fill portrait panes for {name}: {later_colors}")
                    _, peak_log = run(["ffmpeg", "-hide_banner", "-i", str(output), "-af", "volumedetect", "-vn", "-f", "null", "-"])
                    if b"max_volume:" not in peak_log:
                        raise RuntimeError(f"Audio peak measurement failed for {name}")
                    checks.append({"name": name, "output": str(output), "duration": media["format"]["duration"]})
                    if progress:
                        progress(len(checks), 22, name)
                    if limit is not None and len(checks) >= limit:
                        return checks
        # Verify the new full-height crop and FlipX technique against an
        # asymmetric repeated source, so a property accepted but ignored by
        # Resolve cannot silently pass compatibility.
        pair = root / "mirror-source.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:size=640x720:rate=30:duration=7",
             "-f", "lavfi", "-i", "color=blue:size=640x720:rate=30:duration=7",
             "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]", "-map", "[v]", "-c:v", "libx264",
             "-preset", "ultrafast", str(pair)])
        mirror_output = root / "mirror-fixture.mp4"
        mirror_clips = [Clip(90, str(pair), 0, 7, 0, 0, None, False),
                        Clip(5, sources[4]["path"], 0, 7, 0, 1, None, False),
                        Clip(90, str(pair), 0, 7, 0, 2, None, False, .5, (), None, True)]
        render(mirror_clips, str(song), str(mirror_output), 1920, 1080, 30,
               {"layout": "three-pane", "selectionMode": "face", "style": "rhythmic-polish",
                "colorTreatment": "natural", "transitionFamilies": ["cut"]}, "", threading.Event(),
               lambda percent, message: None, require_validation=False)
        frame, _ = run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(mirror_output),
                        "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
        left = frame[(540 * 1920 + 480) * 3:(540 * 1920 + 480) * 3 + 3]
        right = frame[(540 * 1920 + 1760) * 3:(540 * 1920 + 1760) * 3 + 3]
        if left == right:
            raise RuntimeError("Resolve did not visually mirror the repeated outside pane")
        checks.append({"name": "full-height-mirror", "output": str(mirror_output), "duration": probe(mirror_output)["format"]["duration"]})
        if progress:
            progress(len(checks), 22, "full-height-mirror")
        # The grid geometry and both Fusion expansion paths are required by
        # schema 4. Check rendered pixels, not merely accepted API properties.
        landscape = [sources[3], sources[4], sources[5],
                     {"id": 90, "path": str(pair)}]
        for role, expansion in (("grid", False), ("grid", True), ("three-pane", True)):
            name = role + ("-expansion" if expansion else "-tiles")
            members = landscape if role == "grid" else sources[:3]
            expansion_pane = len(members) - 1
            fixtures = [Clip(int(source["id"]), source["path"], 0, 2, 0, index, None, False, .5,
                             layout_role=role) for index, source in enumerate(members)]
            if expansion:
                fixtures.extend(Clip(int(source["id"]), source["path"], 2, .5, 2, index, None, False, .5,
                                     layout_role=role, underlay=True)
                                for index, source in enumerate(members))
                fixtures.append(Clip(int(members[expansion_pane]["id"]), members[expansion_pane]["path"], 2, 2, 2, 0, None, False, .5,
                                     layout_role="full-screen", expansion_from=expansion_pane,
                                     expansion_duration=.5, expansion_layout=role))
            output = root / (name + ".mp4")
            render(fixtures, str(song), str(output), 640, 360, 30,
                   {"layoutModes": [role, "full-screen"] if expansion else [role], "selectionMode": "center",
                    "style": "rhythmic-polish", "colorTreatment": "natural", "transitionFamilies": ["cut"]},
                   "", threading.Event(), lambda percent, message: None, require_validation=False)
            def sample(seconds, x, y):
                raw, _ = run(["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(output),
                              "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
                at = (y * 640 + x) * 3
                return tuple(raw[at:at + 3])
            centers = [(160, 90), (480, 90), (160, 270), (480, 270)] if role == "grid" else [
                (105, 180), (320, 180), (535, 180)]
            first = [sample(1, x, y) for x, y in centers]
            if any(max(pixel) < 65 for pixel in first) or len(set(first)) != len(centers):
                raise RuntimeError(f"{name} did not render distinct visible cells: {first}")
            if expansion:
                last = [sample(3, x, y) for x, y in centers]
                if any(max(abs(a - b) for a, b in zip(pixel, last[0])) > 8 for pixel in last[1:]) or (
                        role == "three-pane" and last[0][2] < 80):
                    raise RuntimeError(f"{name} did not expand its cell to the full frame: {last}")
            checks.append({"name": name, "output": str(output),
                           "duration": probe(output)["format"]["duration"]})
            if progress:
                progress(len(checks), 22, name)
        print(json.dumps({"studio": resolve.GetProductName(), "version": resolve.GetVersionString(), "renders": checks}, indent=2))
        print("Inspect beat cuts, transition smoothness, flash/glitch accents, crop edges, and audio peaks before cleanup.")
        if automated or input("Type VALIDATED to enable this Resolve version: ").strip() == "VALIDATED":
            VALIDATION.write_text(json.dumps({"product": resolve.GetProductName(), "version": resolve.GetVersionString(), "schema": VALIDATION_SCHEMA,
                                              "renders": len(checks)}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
