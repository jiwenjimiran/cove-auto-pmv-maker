"""Resolve Studio 20.3.1 scripting bridge. All API calls happen on one worker thread."""
from __future__ import annotations

import os
import sys
import time
import re
import json
import uuid
import math
from pathlib import Path

from engine import option_range, probe, run

MODULES = Path(os.environ.get("RESOLVE_SCRIPT_API", r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting")) / "Modules"
VALIDATION = Path(__file__).with_name("validated-version.json")
VALIDATION_SCHEMA = 3
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


def render(clips, audio_path, output_path, width, height, fps, options, project_folder, cancel, progress,
           require_validation=True):
    resolve = connect(require_validation=require_validation)
    manager = resolve.GetProjectManager()
    project_name = "PMVMAKER_TMP_" + uuid.uuid4().hex
    project = manager.CreateProject(project_name)
    if not project:
        raise RuntimeError("Resolve could not create a temporary project. Open an editable project in a local project library, then retry. The scripting API reports database: " + str(manager.GetCurrentDatabase()))
    job_id = None
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
        layout = options.get("layout", "three-pane")
        pane_count = 3 if layout == "three-pane" else 1
        source_sizes = {}
        if pane_count == 3:
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
        for _ in range(pane_count * 4 - timeline.GetTrackCount("video")):
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
            if pane_count == 3:
                pane_width = width / 3
                source_width, source_height = source_sizes[clip.path]
                fill_scale = max(width / source_width, height / source_height)
                pane_scale = (height / source_height if options.get("selectionMode") == "face"
                              else max(pane_width / source_width, height / source_height))
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
                set_property("Pan", (clip.pane - 1) * pane_width - shift, "pane position")
                set_property("CropLeft", side_crop + shift, "left pane crop")
                set_property("CropRight", side_crop - shift, "right pane crop")
                if clip.mirrored:
                    set_property("FlipX", True, "mirror repeated source")
            else:
                set_property("Scaling", resolve.SCALE_FILL, "full-screen scaling")
            face_slice = pane_count == 3 and options.get("selectionMode") == "face"
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
            return item

        # Main video occupies separate tracks per pane. Dissolves use short incoming
        # slices on overlay tracks with increasing opacity over the outgoing clip.
        placed_clips = 0
        for pane in range(pane_count):
            pane_clips = sorted((clip for clip in clips if clip.pane == pane), key=lambda clip: clip.record_start)
            for position, clip in enumerate(pane_clips):
                placed_clips += 1
                progress(53.5 + 1.4 * placed_clips / max(1, len(clips)),
                         f"Assembling clip {placed_clips}/{len(clips)}: video {clip.video_id}, pane {pane + 1}/{pane_count}, timeline {clip.record_start:.1f}s")
                fade = 0.0
                transition_intensity = intensity("transitionIntensity", clip, 0.25)
                flash_intensity = intensity("flashIntensity", clip, 0)
                glitch_intensity = intensity("glitchIntensity", clip, 0)
                if position and transition_on and transition_intensity > 0:
                    previous = pane_clips[position - 1]
                    fade = min(0.5 * transition_intensity, clip.duration * 0.25, previous.duration * 0.25)
                    fade_frames = max(1, round(fade * fps))
                    fade = fade_frames / fps
                    if fade_frames >= 4:
                        first_frames = (fade_frames + 1) // 2
                        append_part(clip, 0, first_frames / fps, clip.record_start - fade,
                                    pane_count + pane + 1, opacity=25)
                        append_part(clip, first_frames / fps, (fade_frames - first_frames) / fps,
                                    clip.record_start - fade + first_frames / fps,
                                    pane_count + pane + 1, opacity=75)
                    else:
                        append_part(clip, 0, fade, clip.record_start - fade,
                                    pane_count + pane + 1, opacity=50)
                if clip.face_track and len(clip.face_track) > 1:
                    boundaries = [0.0] + [(left[0] + right[0]) / 2 for left, right in zip(clip.face_track, clip.face_track[1:])] + [clip.duration]
                    for start, end in zip(boundaries, boundaries[1:]):
                        start = max(start, fade)
                        if end > start:
                            append_part(clip, start, end - start, clip.record_start + start - fade, pane + 1)
                else:
                    append_part(clip, fade, clip.duration - fade, clip.record_start, pane + 1)
                if clip.accent and flash_intensity > 0:
                    append_part(clip, 0, min(0.12, clip.duration), clip.record_start,
                                pane_count * 2 + pane + 1, opacity=50 * flash_intensity,
                                composite=resolve.COMPOSITE_ADD)
                if clip.accent and glitch_intensity > 0:
                    effect = append_part(clip, min(0.08, clip.duration / 4), min(0.12, clip.duration / 4),
                                         clip.record_start, pane_count * 3 + pane + 1,
                                         opacity=35 * glitch_intensity, composite=resolve.COMPOSITE_DIFF)
                    base_pan = 0
                    if pane_count == 3:
                        source_width, source_height = source_sizes[clip.path]
                        visible_width = source_width * max((width / 3) / source_width, height / source_height)
                        side_crop = max(0.0, (visible_width - width / 3) / 2)
                        shift = max(-side_crop, min(side_crop, (center_at(clip, 0) - 0.5) * visible_width))
                        base_pan = (pane - 1) * width / 3 - shift
                    set_item_property(effect, "Pan", base_pan + 20 * glitch_intensity, "glitch offset", clip,
                                      pane_count * 3 + pane + 1)
        audio_item = items[media_key(audio_path)]
        result = media_pool.AppendToTimeline([{"mediaPoolItem": audio_item, "startFrame": 0,
                                               "endFrame": max(1, round(max(c.record_start + c.duration for c in clips) * fps)) - 1,
                                               "recordFrame": 0, "trackIndex": 1, "mediaType": 2}])
        if not result:
            raise RuntimeError("Resolve could not place the final audio mix")
        check(manager.SaveProject(), "SaveProject")
        codecs = project.GetRenderCodecs("mp4") or {}
        codec = next((value for label, value in codecs.items() if "264" in label or "264" in value), None)
        if codec is None:
            raise RuntimeError("Resolve has no H.264 MP4 render codec")
        check(project.SetCurrentRenderFormatAndCodec("mp4", codec), "H.264 MP4 render format")
        check(project.SetCurrentRenderMode(1), "single clip render mode")
        settings = {"SelectAllFrames": True, "TargetDir": str(Path(output_path).parent),
                    "CustomName": Path(output_path).stem, "ExportVideo": True, "ExportAudio": True,
                    "FormatWidth": width, "FormatHeight": height, "FrameRate": fps, "AudioCodec": "aac",
                    "AudioSampleRate": 48000}
        for key, value in settings.items():
            check(project.SetRenderSettings({key: value}), f"render setting {key}={value!r}")
        job_id = check(project.AddRenderJob(), "AddRenderJob")
        progress(55, "Rendering H.264 MP4 in Resolve")
        check(project.StartRendering(job_id), "StartRendering")
        while project.IsRenderingInProgress():
            if cancel.is_set():
                project.StopRendering()
                raise InterruptedError("Render cancelled")
            status = project.GetRenderJobStatus(job_id) or {}
            percent = float(status.get("CompletionPercentage", 0) or 0)
            progress(55 + percent * 0.43, f"Resolve render {percent:.0f}%")
            time.sleep(1)
        status = project.GetRenderJobStatus(job_id) or {}
        if status.get("JobStatus") not in ("Complete", "Completed"):
            raise RuntimeError("Resolve render failed: " + str(status))
        if not Path(output_path).is_file() or Path(output_path).stat().st_size == 0:
            raise RuntimeError("Resolve reported completion but produced no MP4")
        if options.get("saveProject"):
            target = Path(project_folder or Path(output_path).parent)
            target.mkdir(parents=True, exist_ok=True)
            check(manager.ExportProject(project_name, str(target / (Path(output_path).stem + ".drp"))), "ExportProject")
        return status
    finally:
        if job_id:
            project.DeleteRenderJob(job_id)
        check(manager.CloseProject(project), "CloseProject")
        if project_name in (manager.GetProjectListInCurrentFolder() or []):
            check(manager.DeleteProject(project_name), "DeleteProject")
