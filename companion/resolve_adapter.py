"""Resolve Studio 20.3.1 scripting bridge. All API calls happen on one worker thread."""
from __future__ import annotations

import os
import sys
import time
import re
import json
from pathlib import Path

from engine import run

MODULES = Path(os.environ.get("RESOLVE_SCRIPT_API", r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting")) / "Modules"
VALIDATION = Path(__file__).with_name("validated-version.json")
sys.path.insert(0, str(MODULES))


def connect(require_validation=True):
    try:
        import DaVinciResolveScript as api
        resolve = api.scriptapp("Resolve")
    except Exception as exc:
        raise RuntimeError(f"Resolve scripting API unavailable: {exc}") from exc
    if resolve is None:
        raise RuntimeError("Resolve is running but its external scripting API is unavailable. Enable local scripting in Resolve Preferences > System > General.")
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
        if validated.get("version") != version or validated.get("product") != product:
            raise RuntimeError(f"Resolve {version} needs the PMV render compatibility check. Run it from Auto PMV Maker settings in Cove.")
    return resolve


def check(ok, label):
    if not ok:
        raise RuntimeError(f"Resolve rejected {label}")
    return ok


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
    project_name = "PMVMAKER_TMP_" + Path(output_path).stem + "_" + str(int(time.time()))
    project = check(manager.CreateProject(project_name), "CreateProject")
    job_id = None
    try:
        check(project.SetSetting("timelineResolutionWidth", str(width)), "timeline width")
        check(project.SetSetting("timelineResolutionHeight", str(height)), "timeline height")
        check(project.SetSetting("timelineFrameRate", str(fps)), "timeline fps")
        media_pool = project.GetMediaPool()
        folder = media_pool.GetCurrentFolder()
        media_storage = resolve.GetMediaStorage()
        paths = list(dict.fromkeys([c.path for c in clips] + [audio_path]))
        for path in paths:
            if not Path(path).is_file():
                raise RuntimeError("Resolve cannot read " + path)
        imported = media_storage.AddItemListToMediaPool(paths)
        if not imported or len(imported) != len(paths):
            # Some versions import an existing item only once; resolve by path.
            imported = folder.GetClipList()
        items = {}
        for item in imported:
            item_path = item.GetClipProperty("File Path")
            if item_path:
                items[os.path.normcase(os.path.normpath(item_path))] = item
        for path in paths:
            if os.path.normcase(os.path.normpath(path)) not in items:
                raise RuntimeError("Resolve did not import " + path)
        timeline = check(media_pool.CreateEmptyTimeline(project_name), "CreateEmptyTimeline")
        check(project.SetCurrentTimeline(timeline), "SetCurrentTimeline")
        check(timeline.SetStartTimecode("00:00:00:00"), "timeline start timecode")
        layout = options.get("layout", "three-pane")
        pane_count = 3 if layout == "three-pane" else 1
        treatment = options.get("colorTreatment", "matched")
        luma = {path: source_luma(path) for path in {clip.path for clip in clips}} if treatment == "matched" else {}
        transition_on = "dissolve" in (options.get("transitionFamilies") or [])
        transition_intensity = max(0.0, min(1.0, float(options.get("transitionIntensity", 0))))
        flash_intensity = max(0.0, min(1.0, float(options.get("flashIntensity", 0))))
        glitch_intensity = max(0.0, min(1.0, float(options.get("glitchIntensity", 0))))
        motion_intensity = max(0.0, min(1.0, float(options.get("motionIntensity", 0.25))))
        style = options.get("style", "rhythmic-polish")

        def append_part(clip, offset, length, record_start, track_index, opacity=None, composite=None):
            if cancel.is_set():
                raise InterruptedError("Timeline build cancelled")
            source = items[os.path.normcase(os.path.normpath(clip.path))]
            start = round((clip.source_start + offset) * fps)
            count = max(1, round(length * fps))
            at = round(record_start * fps)
            entry = {"mediaPoolItem": source, "startFrame": start, "endFrame": start + count - 1,
                     "recordFrame": at, "trackIndex": track_index, "mediaType": 1}
            result = media_pool.AppendToTimeline([entry])
            if not result:
                raise RuntimeError(f"Resolve could not append video {clip.video_id} at {at}")
            item = result[0]
            if pane_count == 3:
                pane_width = width / 3
                check(item.SetProperty("Scaling", resolve.SCALE_FILL), "pane scaling")
                check(item.SetProperty("Pan", (clip.pane - 1) * pane_width), "pane position")
                check(item.SetProperty("CropLeft", clip.pane * pane_width), "left pane crop")
                check(item.SetProperty("CropRight", (2 - clip.pane) * pane_width), "right pane crop")
            else:
                check(item.SetProperty("Scaling", resolve.SCALE_FILL), "full-screen scaling")
            if style == "high-energy" and clip.accent:
                zoom = 1 + 0.1 * motion_intensity
                check(item.SetProperty("ZoomX", zoom), "accent zoom X")
                check(item.SetProperty("ZoomY", zoom), "accent zoom Y")
            elif style == "cinematic":
                zoom = 1 + 0.03 * motion_intensity
                check(item.SetProperty("ZoomX", zoom), "cinematic zoom X")
                check(item.SetProperty("ZoomY", zoom), "cinematic zoom Y")
            if opacity is not None:
                check(item.SetProperty("Opacity", opacity), "effect opacity")
            if composite is not None:
                check(item.SetProperty("CompositeMode", composite), "effect composite mode")
            grade(item, treatment, luma.get(clip.path, 112.0))
            return item

        # Main video occupies separate tracks per pane. Dissolves use short incoming
        # slices on overlay tracks with increasing opacity over the outgoing clip.
        for pane in range(pane_count):
            pane_clips = sorted((clip for clip in clips if clip.pane == pane), key=lambda clip: clip.record_start)
            for position, clip in enumerate(pane_clips):
                fade = 0.0
                if position and transition_on and transition_intensity > 0:
                    previous = pane_clips[position - 1]
                    fade = min(0.5 * transition_intensity, clip.duration * 0.25, previous.duration * 0.25)
                    fade_frames = max(1, round(fade * fps))
                    fade = fade_frames / fps
                    for frame in range(fade_frames):
                        append_part(clip, frame / fps, 1 / fps, clip.record_start - fade + frame / fps,
                                    pane_count + pane + 1, opacity=100 * (frame + 1) / fade_frames)
                append_part(clip, fade, clip.duration - fade, clip.record_start, pane + 1)
                if clip.accent and flash_intensity > 0:
                    append_part(clip, 0, min(0.12, clip.duration), clip.record_start,
                                pane_count * 2 + pane + 1, opacity=50 * flash_intensity,
                                composite=resolve.COMPOSITE_ADD)
                if clip.accent and glitch_intensity > 0:
                    effect = append_part(clip, min(0.08, clip.duration / 4), min(0.12, clip.duration / 4),
                                         clip.record_start, pane_count * 3 + pane + 1,
                                         opacity=35 * glitch_intensity, composite=resolve.COMPOSITE_DIFF)
                    check(effect.SetProperty("Pan", ((pane - 1) * width / 3 if pane_count == 3 else 0) + 20 * glitch_intensity), "glitch offset")
        audio_item = items[os.path.normcase(os.path.normpath(audio_path))]
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
                    "AudioSampleRate": 48000, "VideoQuality": "Best", "ReplaceExistingFilesInPlace": False}
        check(project.SetRenderSettings(settings), "render settings")
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
        check(manager.DeleteProject(project_name), "DeleteProject")
