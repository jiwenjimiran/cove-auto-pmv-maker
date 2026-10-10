"""Resolve Studio 20.3.1 scripting bridge. All API calls happen on one worker thread."""
from __future__ import annotations

import os
import sys
import time
import re
import json
import uuid
import math
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from engine import layout_modes, option_range, probe, run

MODULES = Path(os.environ.get("RESOLVE_SCRIPT_API", r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting")) / "Modules"
VALIDATION = Path(__file__).with_name("validated-version.json")
VALIDATION_SCHEMA = 5
sys.path.insert(0, str(MODULES))


def connect(require_validation=True):
    try:
        import DaVinciResolveScript as api
        resolve = api.scriptapp("Resolve")
    except Exception as exc:
        raise RuntimeError(f"Resolve scripting API unavailable: {exc}") from exc
    if resolve is None:
        raise RuntimeError("Resolve did not accept the scripting connection. Select Local in Resolve Preferences > System > General, save, then restart the PMV engine in Cove settings.")
    version = resolve.GetVersionString()
    product = resolve.GetProductName()
    if "Studio" not in product:
        raise RuntimeError(f"DaVinci Resolve Studio is required; found {product!r}")
    fields = tuple(int(x) for x in re.findall(r"\d+", version or "")[:3])
    if len(fields) < 3 or fields < (20, 3, 1):
        raise RuntimeError(f"Resolve Studio 20.3.1 or later is required; found {version!r}")
    if require_validation:
        try:
            validated = json.loads(VALIDATION.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            validated = {}
        if validated.get("version") != version or validated.get("product") != product or validated.get("schema") != VALIDATION_SCHEMA:
            raise RuntimeError(f"Resolve {version} needs the PMV render compatibility check. Run it from Auto PMV Maker settings in Cove.")
    return resolve


def check(ok, label):
    if not ok:
        raise RuntimeError(f"Resolve rejected {label}")
    return ok


def set_item_property(item, key, value, label, clip, track_index, project_fill=False):
    """Resolve may expose an appended timeline item before its filters accept edits."""
    def set_single(property_key, property_value):
        modern = getattr(item, "SetProperties", None)
        return modern({property_key: property_value}) if callable(modern) else item.SetProperty(property_key, property_value)

    def get_all():
        modern = getattr(item, "GetProperties", None)
        return (modern() if callable(modern) else item.GetProperty()) or {}

    last_result = None
    for attempt in range(4):
        last_result = set_single(key, value)
        if last_result:
            return
        properties = get_all()
        current = properties.get(key)
        if current == value or (isinstance(current, (int, float)) and isinstance(value, (int, float))
                                and abs(current - value) < 0.001):
            return
        if key == "Scaling" and properties.get("RetimeAndScalingEnabled") is False:
            set_single("RetimeAndScalingEnabled", True)
        if attempt < 3:
            time.sleep((0.1, 0.25, 0.5)[attempt])
    properties = get_all()
    if (key == "Scaling" and project_fill and properties.get("Scaling") == 0
            and properties.get("RetimeAndScalingEnabled") is not False):
        # SCALE_USE_PROJECT inherits timelineInputResMismatchBehavior=scaleToCrop.
        # Some media items reject a per-item override even though project scaling works.
        return
    raise RuntimeError(
        f"Resolve rejected {label} for video {clip.video_id} ({Path(clip.path).name}), "
        f"track {track_index}, timeline {clip.record_start:.2f}s, source {clip.source_start:.2f}s: "
        f"{key}={value!r}; current={properties.get(key)!r}, "
        f"RetimeAndScalingEnabled={properties.get('RetimeAndScalingEnabled')!r}, result={last_result!r}")


def media_key(path):
    # Resolve may expand Windows 8.3 names while Python keeps the short path.
    return os.path.normcase(os.path.realpath(path))


def source_frame_range(source_start, offset, length, source_fps, source_frames):
    """Convert edit seconds to source frames; Resolve interprets these in source timebase."""
    if source_fps <= 0 or source_frames <= 0:
        raise ValueError("Source video has no valid frame rate or frame count")
    start = round((source_start + offset) * source_fps)
    if start < 0 or start >= source_frames:
        raise ValueError(f"Source position {source_start + offset:.3f}s is outside the video")
    # Resolve's inclusive endFrame produces a timeline item up to two frames
    # shorter than the nominal duration when a 23.976 source enters a 30 fps
    # timeline. One extra source frame covers the cut without a black gap.
    count = min(source_frames - start, max(1, math.ceil(length * source_fps) + 1))
    return start, start + count - 1


def source_luma(path):
    # A tiny decode sample gives a stable brightness target without copying the master.
    try:
        _, log = run(["ffmpeg", "-hide_banner", "-i", path, "-t", "2", "-vf",
                      "fps=1,scale=64:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                      "-an", "-f", "null", "-"])
        values = [float(x) for x in re.findall(rb"lavfi\.signalstats\.YAVG=([0-9.]+)", log)]
        return sum(values) / len(values) if values else 112.0
    except Exception:
        return 112.0


def grade(item, treatment, luma):
    if treatment == "natural":
        return
    balance = max(0.82, min(1.18, 112.0 / max(30.0, luma))) if treatment == "matched" else 1.0
    rgb = {"warm": (1.04, 1.0, 0.96), "cool": (0.96, 1.0, 1.04)}.get(treatment, (1.0, 1.0, 1.0))
    check(item.SetCDL({"NodeIndex": "1", "Slope": " ".join(f"{channel*balance:.3f}" for channel in rgb),
                       "Offset": "0 0 0", "Power": "1 1 1", "Saturation": "1"}), "color treatment")


def select_mp4_codec(project, requested, apply=False):
    """Use the codec identifiers exposed by this Resolve installation."""
    labels = {"h264": "H.264", "h265": "H.265", "av1": "AV1"}
    if requested not in labels:
        raise ValueError("Choose H.264, H.265, or AV1 for MP4 rendering")
    available = project.GetRenderCodecs("mp4") or {}
    def matches(label, value):
        combined = re.sub(r"[^a-z0-9]", "", f"{label} {value}".lower())
        if requested == "h264":
            return ("h264" in combined or "avc" in combined) and "h265" not in combined
        if requested == "h265":
            return "h265" in combined or "hevc" in combined
        return "av1" in combined and any(hardware in combined for hardware in
                                      ("nvidia", "nvenc", "amd", "amf", "intel", "qsv", "quicksync"))
    candidates = [(label, value) for label, value in available.items() if matches(label, value)]
    if requested == "av1":
        candidates.sort(key=lambda pair: ("8bit" not in re.sub(r"[^a-z0-9]", "", pair[0].lower()), pair[0]))
    else:
        candidates.sort(key=lambda pair: (pair[0].lower() != labels[requested].lower(), pair[0]))
    if not candidates:
        choices = ", ".join(available) or "none"
        raise RuntimeError(f"Resolve Studio does not offer {labels[requested]} for MP4 on this PC. "
                           f"Available MP4 codecs: {choices}. Choose another render codec in Auto PMV Maker settings.")
    if apply:
        for label, value in candidates:
            if project.SetCurrentRenderFormatAndCodec("mp4", value):
                return label, value
        raise RuntimeError(f"Resolve Studio lists {labels[requested]} for MP4, but rejected every available "
                           f"{labels[requested]} encoder on this PC. Choose another render codec in Auto PMV Maker settings.")
    return candidates[0]


def ffmpeg_av1_encoder():
    """Probe actual encoding, since listing an encoder does not mean it can run."""
    name, args = "av1_nvenc", ["-preset", "p5", "-cq", "20", "-b:v", "0"]
    try:
        trial = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=c=gray:s=640x360:r=30:d=0.2", "-frames:v", "4", "-c:v", name,
             *args, "-f", "null", "-"], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"NVIDIA AV1 hardware encoding is unavailable: {exc}") from exc
    if trial.returncode != 0:
        raise RuntimeError("NVIDIA AV1 hardware encoding failed: "
                           + trial.stderr.decode(errors="replace")[-1000:])
    return name, args


def select_render_profile(project, requested):
    """Prefer native Resolve AV1, then a high-quality Resolve intermediate."""
    if requested != "av1":
        label, codec = select_mp4_codec(project, requested, apply=True)
        return {"format": "mp4", "codec": codec, "label": label, "intermediate": False}
    try:
        label, codec = select_mp4_codec(project, "av1", apply=True)
        return {"format": "mp4", "codec": codec, "label": label, "intermediate": False}
    except RuntimeError as native_error:
        encoder, encoder_args = ffmpeg_av1_encoder()
        mov_codecs = project.GetRenderCodecs("mov") or {}
        for label, codec in mov_codecs.items():
            if codec == "DNxHRHQX_10" and project.SetCurrentRenderFormatAndCodec("mov", codec):
                return {"format": "mov", "codec": codec, "label": label, "intermediate": True,
                        "encoder": encoder, "encoderArgs": encoder_args}
        raise RuntimeError(f"{native_error} Resolve also rejected the DNxHR HQX intermediate needed "
                           "for FFmpeg AV1 encoding.")


def encode_av1(intermediate, audio_path, output_path, encoder, encoder_args, cancel, progress):
    """Encode the Resolve intermediate and publish only a verified AV1 MP4."""
    duration = float(probe(intermediate)["format"]["duration"])
    temporary = Path(intermediate).with_name("av1-output.mp4")
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(intermediate),
            "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", encoder,
            *encoder_args, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
            "-ar", "48000", "-shortest", "-movflags", "+faststart", "-progress", "pipe:1",
            "-nostats", str(temporary)]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    latest = {"seconds": 0.0}
    def read_progress():
        for line in process.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    latest["seconds"] = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    pass
    reader = threading.Thread(target=read_progress, daemon=True)
    reader.start()
    last_percent = -1
    try:
        while process.poll() is None:
            if cancel.is_set():
                process.kill()
                raise InterruptedError("AV1 encoding cancelled")
            percent = min(98, 80 + 18 * latest["seconds"] / max(0.1, duration))
            if int(percent) > last_percent:
                last_percent = int(percent)
                progress(percent, f"Encoding AV1 MP4 with {encoder}: {latest['seconds']:.1f}/{duration:.1f}s")
            time.sleep(0.25)
        reader.join(timeout=2)
        errors = process.stderr.read()
        if process.returncode:
            raise RuntimeError(f"FFmpeg AV1 encoding failed ({encoder}): {errors[-2000:]}")
        streams = probe(temporary)["streams"]
        video = next((stream for stream in streams if stream["codec_type"] == "video"), None)
        audio = next((stream for stream in streams if stream["codec_type"] == "audio"), None)
        if video is None or video.get("codec_name") != "av1" or audio is None or audio.get("codec_name") != "aac":
            raise RuntimeError("FFmpeg did not produce a playable AV1/AAC MP4")
        target = Path(output_path)
        partial = target.with_name(target.name + "." + uuid.uuid4().hex + ".partial")
        try:
            shutil.copyfile(temporary, partial)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        progress(98.5, "Verified final AV1/AAC MP4")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def animate_expansion(item, clip, role, width, height, fps):
    """Animate original-resolution media from its cell to full frame in Fusion."""
    frames = max(4, round(clip.expansion_duration * fps))
    comp = check(item.AddFusionComp(), "AddFusionComp for cell expansion")
    tools = list(comp.GetToolList().values())
    media_in = next((tool for tool in tools if tool.GetAttrs().get("TOOLS_RegID") == "MediaIn"), None)
    media_out = next((tool for tool in tools if tool.GetAttrs().get("TOOLS_RegID") == "MediaOut"), None)
    if media_in is None or media_out is None:
        raise RuntimeError("Resolve Fusion did not expose MediaIn/MediaOut for cell expansion")
    transform = check(comp.AddTool("Transform"), "Fusion Transform for cell expansion")
    transform.Input = media_in.Output
    transform.Center = comp.Path()
    # A corner tile shows the full landscape frame at half size. The portrait
    # version instead reveals a moving full-height mask.
    from_grid = clip.expansion_layout == "grid"
    if from_grid:
        col, row = clip.expansion_from % 2, clip.expansion_from // 2
        transform.UseSizeAndAspect = 0
        transform.XSize = comp.BezierSpline()
        transform.YSize = comp.BezierSpline()
        transform.XSize[0], transform.XSize[frames] = 0.5, 1.0
        transform.YSize[0], transform.YSize[frames] = 0.5, 1.0
        transform.Center[0] = {1: 0.25 + 0.5 * col, 2: 0.75 - 0.5 * row}
        transform.Center[frames] = {1: 0.5, 2: 0.5}
        media_out.Input = transform.Output
        if abs(float(transform.XSize[0]) - 0.5) > 0.01 or abs(float(transform.XSize[frames]) - 1) > 0.01:
            raise RuntimeError("Resolve did not retain grid expansion keyframes")
    else:
        pane_center = (clip.expansion_from + 0.5) / 3
        start_center = max(0.0, min(1.0, pane_center - (clip.crop_center - 0.5)))
        transform.Center[0] = {1: start_center, 2: 0.5}
        transform.Center[frames] = {1: 0.5, 2: 0.5}
        background = check(comp.AddTool("Background"), "Fusion transparent background")
        background.TopLeftAlpha = 0.0
        mask = check(comp.AddTool("RectangleMask"), "Fusion expansion mask")
        mask.Width = comp.BezierSpline()
        mask.Center = comp.Path()
        mask.Width[0], mask.Width[frames] = 1 / 3, 1.0
        mask.Center[0] = {1: pane_center, 2: 0.5}
        mask.Center[frames] = {1: 0.5, 2: 0.5}
        mask.Height = 1.0
        merge = check(comp.AddTool("Merge"), "Fusion expansion merge")
        merge.Background = background.Output
        merge.Foreground = transform.Output
        merge.EffectMask = mask.Output
        media_out.Input = merge.Output
        if abs(float(mask.Width[0]) - 1 / 3) > 0.01 or abs(float(mask.Width[frames]) - 1) > 0.01:
            raise RuntimeError("Resolve did not retain portrait expansion keyframes")


def render(clips, audio_path, output_path, width, height, fps, options, project_folder, cancel, progress,
           require_validation=True):
    resolve = connect(require_validation=require_validation)
    manager = resolve.GetProjectManager()
    project_name = "PMVMAKER_TMP_" + uuid.uuid4().hex
    project = manager.CreateProject(project_name)
    if not project:
        raise RuntimeError("Resolve could not create a temporary project. Open an editable project in a local project library, then retry. The scripting API reports database: " + str(manager.GetCurrentDatabase()))
    job_id = None
    work_dir = None
    try:
        check(project.SetSettings({"timelineResolutionWidth": str(width)}), "timeline width")
        check(project.SetSettings({"timelineResolutionHeight": str(height)}), "timeline height")
        check(project.SetSettings({"timelineFrameRate": str(fps)}), "timeline fps")
        check(project.SetSettings({"timelineInputResMismatchBehavior": "scaleToCrop"}), "project fill scaling")
        check(manager.SaveProject(), "SaveProject before media import")
        media_pool = project.GetMediaPool()
        folder = media_pool.GetCurrentFolder()
        media_storage = resolve.GetMediaStorage()
        paths = list(dict.fromkeys(os.path.realpath(path) for path in [c.path for c in clips] + [audio_path]))
        for path in paths:
            if not Path(path).is_file():
                raise RuntimeError("Resolve cannot read " + path)
        progress(52.2, f"Importing {len(paths) - 1} videos and final audio into Resolve")
        imported = media_storage.AddItemListToMediaPool([{"media": path} for path in paths])
        if not imported or len(imported) != len(paths):
            # Some versions import an existing item only once; resolve by path.
            imported = folder.GetClipList()
        items = {}
        for item in imported:
            item_path = item.GetClipProperty("File Path")
            if item_path:
                items[media_key(item_path)] = item
        for path in paths:
            if media_key(path) not in items:
                sample = imported[0].GetClipProperty() if imported else None
                raise RuntimeError("Resolve did not import " + path + "; item count: " + str(len(imported or []))
                                   + "; folder count: " + str(len(folder.GetClipList() or []))
                                   + "; first properties: " + repr(sample))
        source_rates = {}
        source_frames = {}
        for path in {clip.path for clip in clips}:
            item = items[media_key(path)]
            try:
                source_rates[path] = float(item.GetClipProperty("FPS"))
                source_frames[path] = int(item.GetClipProperty("Frames"))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Resolve cannot report source frame rate and length for {path}") from exc
            if source_rates[path] <= 0 or source_frames[path] <= 0:
                raise RuntimeError(f"Resolve reported invalid source frame rate or length for {path}")
        timeline = check(media_pool.CreateEmptyTimeline(project_name), "CreateEmptyTimeline")
        check(project.SetCurrentTimeline(timeline), "SetCurrentTimeline")
        check(timeline.SetStartTimecode("00:00:00:00"), "timeline start timecode")
        layout = options.get("layout", "full-screen")
        modes = layout_modes(options, layout)
        pane_count = 4 if "grid" in modes else 3 if "three-pane" in modes else 1
        hybrid = "full-screen" in modes and pane_count > 1
        main_tracks = pane_count + (1 if hybrid else 0)
        source_sizes = {}
        if pane_count > 1:
            for path in {clip.path for clip in clips}:
                video = next(stream for stream in probe(path)["streams"] if stream["codec_type"] == "video")
                source_width, source_height = int(video["width"]), int(video["height"])
                rotation = int(float(video.get("tags", {}).get("rotate", 0) or 0))
                for side_data in video.get("side_data_list", []):
                    rotation = int(float(side_data.get("rotation", rotation) or 0))
                if rotation % 180:
                    source_width, source_height = source_height, source_width
                source_sizes[path] = (source_width, source_height)
        # AppendToTimeline does not create a requested upper track on every
        # Resolve version. Reserve the tracks used by panes and accents first.
        for _ in range(main_tracks * 4 - timeline.GetTrackCount("video")):
            check(timeline.AddTrack("video"), "AddTrack video")
        for _ in range(1 - timeline.GetTrackCount("audio")):
            check(timeline.AddTrack("audio"), "AddTrack audio")
        treatment = options.get("colorTreatment", "natural")
        luma = {}
        if treatment == "matched":
            used_paths = list(dict.fromkeys(clip.path for clip in clips))
            for index, path in enumerate(used_paths):
                if cancel.is_set():
                    raise InterruptedError("Color analysis cancelled")
                progress(52.5 + index / max(1, len(used_paths)),
                         f"Sampling brightness: video {index + 1}/{len(used_paths)} — {Path(path).name}")
                luma[path] = source_luma(path)
        else:
            progress(53.5, "Color matching off" if treatment == "natural" else f"Applying {treatment} color tone")
        transition_on = "dissolve" in (options.get("transitionFamilies") or [])
        style = options.get("style", "rhythmic-polish")

        def intensity(key, clip, default):
            phase = (clip.record_start * 0.381966 + clip.pane * 0.217) % 1
            return option_range(options, key, phase, default)

        def center_at(clip, offset):
            if not clip.face_track:
                return clip.crop_center
            position = min(clip.face_track, key=lambda point: abs(point[0] - offset))
            return position[1]

        def clip_role(clip):
            return clip.layout_role or modes[0]

        def main_track(clip):
            return main_tracks if hybrid and clip_role(clip) == "full-screen" else clip.pane + 1

        def append_part(clip, offset, length, record_start, track_index, opacity=None, composite=None):
            if cancel.is_set():
                raise InterruptedError("Timeline build cancelled")
            source = items[media_key(clip.path)]
            start, end = source_frame_range(clip.source_start, offset, length,
                                            source_rates[clip.path], source_frames[clip.path])
            at = round(record_start * fps)
            entry = {"mediaPoolItem": source, "startFrame": start, "endFrame": end,
                     "recordFrame": at, "trackIndex": track_index, "mediaType": 1}
            result = media_pool.AppendToTimeline([entry])
            if not result:
                raise RuntimeError(f"Resolve could not append video {clip.video_id} at {at} on track {track_index}; source frames {start}-{end}; video tracks {timeline.GetTrackCount('video')}; timeline frames {timeline.GetStartFrame()}-{timeline.GetEndFrame()}; track items {len(timeline.GetItemListInTrack('video', track_index) or [])}")
            item = result[0]
            if item.GetProperties() is None:
                raise RuntimeError(
                    f"Resolve could not place video {clip.video_id} ({Path(clip.path).name}) on track {track_index} "
                    f"at {record_start:.2f}s: the requested source range {start}-{end} at "
                    f"{source_rates[clip.path]:.3f} fps produced no editable timeline item. "
                    "A clip already on this track may cover that position.")
            def set_property(key, value, label):
                set_item_property(item, key, value, label, clip, track_index, project_fill=True)
            base_zoom = 1.0
            role = clip_role(clip)
            if role in ("three-pane", "grid"):
                pane_width = width / (3 if role == "three-pane" else 2)
                pane_height = height if role == "three-pane" else height / 2
                source_width, source_height = source_sizes[clip.path]
                fill_scale = max(width / source_width, height / source_height)
                pane_scale = (pane_height / source_height if role == "three-pane" and options.get("selectionMode") == "face"
                              else max(pane_width / source_width, pane_height / source_height))
                base_zoom = pane_scale / fill_scale
                visible_width = source_width * pane_scale
                side_crop = max(0.0, (visible_width - pane_width) / 2)
                desired_center = center_at(clip, offset + length / 2)
                if clip.mirrored:
                    desired_center = 1.0 - desired_center
                shift = max(-side_crop, min(side_crop, (desired_center - 0.5) * visible_width))
                set_property("Scaling", resolve.SCALE_FILL, "pane scaling")
                set_property("ZoomX", base_zoom, "pane zoom X")
                set_property("ZoomY", base_zoom, "pane zoom Y")
                horizontal = (clip.pane - 1) * pane_width if role == "three-pane" else ((clip.pane % 2) - 0.5) * pane_width
                set_property("Pan", horizontal - shift, "pane position")
                if role == "grid":
                    set_property("Tilt", (0.5 - clip.pane // 2) * pane_height, "grid row position")
                    vertical_crop = max(0.0, (source_height * pane_scale - pane_height) / 2)
                    set_property("CropTop", vertical_crop, "grid top crop")
                    set_property("CropBottom", vertical_crop, "grid bottom crop")
                set_property("CropLeft", side_crop + shift, "left pane crop")
                set_property("CropRight", side_crop - shift, "right pane crop")
                if clip.mirrored:
                    set_property("FlipX", True, "mirror repeated source")
            else:
                set_property("Scaling", resolve.SCALE_FILL, "full-screen scaling")
            face_slice = role in ("three-pane", "grid") and options.get("selectionMode") == "face"
            if not face_slice and style == "high-energy" and clip.accent:
                motion_intensity = intensity("motionIntensity", clip, 0.25)
                zoom = base_zoom * (1 + 0.1 * motion_intensity)
                set_property("ZoomX", zoom, "accent zoom X")
                set_property("ZoomY", zoom, "accent zoom Y")
            elif not face_slice and style == "cinematic":
                motion_intensity = intensity("motionIntensity", clip, 0.25)
                zoom = base_zoom * (1 + 0.03 * motion_intensity)
                set_property("ZoomX", zoom, "cinematic zoom X")
                set_property("ZoomY", zoom, "cinematic zoom Y")
            if opacity is not None:
                set_property("Opacity", opacity, "effect opacity")
            if composite is not None:
                set_property("CompositeMode", composite, "effect composite mode")
            grade(item, treatment, luma.get(clip.path, 112.0))
            if clip.expansion_from is not None and offset == 0:
                animate_expansion(item, clip, role, width, height, fps)
            return item

        # Main video occupies separate tracks per pane. Dissolves use short incoming
        # slices on overlay tracks with increasing opacity over the outgoing clip.
        placed_clips = 0
        for track in range(1, main_tracks + 1):
            pane_clips = sorted((clip for clip in clips if main_track(clip) == track), key=lambda clip: clip.record_start)
            for position, clip in enumerate(pane_clips):
                placed_clips += 1
                progress(53.5 + 1.4 * placed_clips / max(1, len(clips)),
                         f"Assembling clip {placed_clips}/{len(clips)}: video {clip.video_id}, {clip_role(clip)} cell {clip.pane + 1}, timeline {clip.record_start:.1f}s")
                fade = 0.0
                transition_intensity = intensity("transitionIntensity", clip, 0.25)
                flash_intensity = intensity("flashIntensity", clip, 0)
                glitch_intensity = intensity("glitchIntensity", clip, 0)
                if (position and not clip.underlay and not pane_clips[position - 1].underlay
                        and abs(pane_clips[position - 1].record_start + pane_clips[position - 1].duration - clip.record_start) < 0.05
                        and transition_on and transition_intensity > 0):
                    previous = pane_clips[position - 1]
                    fade = min(0.5 * transition_intensity, clip.duration * 0.25, previous.duration * 0.25)
                    fade_frames = max(1, round(fade * fps))
                    fade = fade_frames / fps
                    if fade_frames >= 4:
                        first_frames = (fade_frames + 1) // 2
                        append_part(clip, 0, first_frames / fps, clip.record_start - fade,
                                    main_tracks + track, opacity=25)
                        append_part(clip, first_frames / fps, (fade_frames - first_frames) / fps,
                                    clip.record_start - fade + first_frames / fps,
                                    main_tracks + track, opacity=75)
                    else:
                        append_part(clip, 0, fade, clip.record_start - fade,
                                    main_tracks + track, opacity=50)
                if clip.face_track and len(clip.face_track) > 1 and clip.expansion_from is None:
                    boundaries = [0.0] + [(left[0] + right[0]) / 2 for left, right in zip(clip.face_track, clip.face_track[1:])] + [clip.duration]
                    for start, end in zip(boundaries, boundaries[1:]):
                        start = max(start, fade)
                        if end > start:
                            append_part(clip, start, end - start, clip.record_start + start - fade, track)
                else:
                    append_part(clip, fade, clip.duration - fade, clip.record_start, track)
                if not clip.underlay and clip.accent and flash_intensity > 0:
                    append_part(clip, 0, min(0.12, clip.duration), clip.record_start,
                                main_tracks * 2 + track, opacity=50 * flash_intensity,
                                composite=resolve.COMPOSITE_ADD)
                if not clip.underlay and clip.accent and glitch_intensity > 0:
                    effect = append_part(clip, min(0.08, clip.duration / 4), min(0.12, clip.duration / 4),
                                         clip.record_start, main_tracks * 3 + track,
                                         opacity=35 * glitch_intensity, composite=resolve.COMPOSITE_DIFF)
                    base_pan = 0
                    if clip_role(clip) == "three-pane":
                        source_width, source_height = source_sizes[clip.path]
                        visible_width = source_width * max((width / 3) / source_width, height / source_height)
                        side_crop = max(0.0, (visible_width - width / 3) / 2)
                        shift = max(-side_crop, min(side_crop, (center_at(clip, 0) - 0.5) * visible_width))
                        base_pan = (clip.pane - 1) * width / 3 - shift
                    elif clip_role(clip) == "grid":
                        base_pan = ((clip.pane % 2) - 0.5) * width / 2
                    set_item_property(effect, "Pan", base_pan + 20 * glitch_intensity, "glitch offset", clip,
                                      main_tracks * 3 + track)
        audio_item = items[media_key(audio_path)]
        result = media_pool.AppendToTimeline([{"mediaPoolItem": audio_item, "startFrame": 0,
                                               "endFrame": max(1, round(max(c.record_start + c.duration for c in clips) * fps)) - 1,
                                               "recordFrame": 0, "trackIndex": 1, "mediaType": 2}])
        if not result:
            raise RuntimeError("Resolve could not place the final audio mix")
        check(manager.SaveProject(), "SaveProject")
        requested_codec = options.get("outputCodec", "h264")
        profile = select_render_profile(project, requested_codec)
        if profile["intermediate"]:
            work_dir = tempfile.TemporaryDirectory(prefix="pmv-av1-render-")
            render_path = str(Path(work_dir.name) / "resolve-intermediate.mov")
            progress(55, f"Resolve rejected native AV1; rendering {profile['label']} before FFmpeg AV1 encoding")
        else:
            render_path = output_path
        check(project.SetCurrentRenderMode(1), "single clip render mode")
        settings = {"SelectAllFrames": True, "TargetDir": str(Path(render_path).parent),
                    "CustomName": Path(render_path).stem, "ExportVideo": True,
                    "ExportAudio": not profile["intermediate"],
                    "FormatWidth": width, "FormatHeight": height, "FrameRate": fps}
        if not profile["intermediate"]:
            settings.update(AudioCodec="aac", AudioSampleRate=48000)
        for key, value in settings.items():
            check(project.SetRenderSettings({key: value}), f"render setting {key}={value!r}")
        job_id = check(project.AddRenderJob(), "AddRenderJob")
        progress(55, f"Rendering {profile['label']} {'intermediate' if profile['intermediate'] else 'MP4'} in Resolve")
        check(project.StartRendering(job_id), "StartRendering")
        while project.IsRenderingInProgress():
            if cancel.is_set():
                project.StopRendering()
                raise InterruptedError("Render cancelled")
            status = project.GetRenderJobStatus(job_id) or {}
            percent = float(status.get("CompletionPercentage", 0) or 0)
            progress(55 + percent * (0.25 if profile["intermediate"] else 0.43), f"Resolve render {percent:.0f}%")
            time.sleep(1)
        status = project.GetRenderJobStatus(job_id) or {}
        if status.get("JobStatus") not in ("Complete", "Completed"):
            raise RuntimeError("Resolve render failed: " + str(status))
        if not Path(render_path).is_file() or Path(render_path).stat().st_size == 0:
            raise RuntimeError("Resolve reported completion but produced no video")
        if profile["intermediate"]:
            progress(80, f"Encoding final AV1 MP4 with {profile['encoder']}")
            encode_av1(render_path, audio_path, output_path, profile["encoder"],
                       profile["encoderArgs"], cancel, progress)
        video_stream = next((stream for stream in probe(output_path)["streams"]
                             if stream["codec_type"] == "video"), None)
        expected_codec = {"h264": "h264", "h265": "hevc", "av1": "av1"}[requested_codec]
        if video_stream is None or video_stream.get("codec_name") != expected_codec:
            raise RuntimeError(f"Resolve rendered {video_stream.get('codec_name') if video_stream else 'no video'} "
                               f"instead of requested {requested_codec.upper()}")
        if options.get("saveProject"):
            target = Path(project_folder or Path(output_path).parent)
            target.mkdir(parents=True, exist_ok=True)
            check(manager.ExportProject(project_name, str(target / (Path(output_path).stem + ".drp"))), "ExportProject")
        return status
    finally:
        try:
            if job_id:
                project.DeleteRenderJob(job_id)
            check(manager.CloseProject(project), "CloseProject")
            if project_name in (manager.GetProjectListInCurrentFolder() or []):
                check(manager.DeleteProject(project_name), "DeleteProject")
        finally:
            if work_dir is not None:
                work_dir.cleanup()
