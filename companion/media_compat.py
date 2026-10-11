"""Make short, Resolve-readable intermediates for rejected source ranges."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import os
from pathlib import Path

from engine import probe, run


INCOMPATIBLE_CONTAINERS = {".wmv", ".asf"}


def needs_reencode(path):
    return Path(path).suffix.lower() in INCOMPATIBLE_CONTAINERS


def _selected_ranges(clips, paths):
    targets = defaultdict(list)
    for clip in clips:
        if clip.path in paths:
            targets[clip.path].append(clip)
    jobs = []
    for path, selected in targets.items():
        intervals = sorted((clip.source_start, clip.source_start + clip.duration) for clip in selected)
        merged = []
        for start, end in intervals:
            if merged and start <= merged[-1][1] + 0.5:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        jobs.extend((path, start, end) for start, end in merged)
    return jobs


def _replace_clips(clips, converted):
    resolve_clips = []
    for clip in clips:
        if clip.path not in converted:
            resolve_clips.append(clip)
            continue
        end = clip.source_start + clip.duration
        match = next(((output, offset) for start, stop, output, offset in converted[clip.path]
                      if start - 0.0001 <= clip.source_start and end <= stop + 0.0001), None)
        if match is None:
            raise RuntimeError(f"No converted range covers video {clip.video_id} at {clip.source_start:.2f}s")
        output, offset = match
        resolve_clips.append(replace(clip, path=output, source_start=clip.source_start + offset))
    return resolve_clips


def prepare_resolve_clips(clips, media_dir, cancel, progress):
    """Re-encode selected WMV ranges; leave originals intact for audio and metadata."""
    jobs = _selected_ranges(clips, {clip.path for clip in clips if needs_reencode(clip.path)})
    if not jobs:
        return clips

    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)

    converted = defaultdict(list)
    for index, (path, start, end) in enumerate(jobs, 1):
        if cancel.is_set():
            raise InterruptedError("Media conversion cancelled")
        output = media_dir / f"source-{index:04d}.mp4"
        progress(42 + 8 * (index - 1) / len(jobs),
                 f"Re-encoding Windows Media range {index}/{len(jobs)}: {Path(path).name} at {start:.1f}-{end:.1f}s")
        # Decode the source in place. The tail pad gives Resolve enough frames
        # for its inclusive endFrame when source and timeline rates differ.
        run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", str(start),
             "-i", path, "-vf", "setpts=PTS-STARTPTS,pad=ceil(iw/2)*2:ceil(ih/2)*2,"
                                "tpad=stop_mode=clone:stop_duration=0.5",
             "-t", str(end - start + 0.5), "-an", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)],
            cancel=cancel)
        streams = probe(output)
        if not any(stream.get("codec_type") == "video" for stream in streams.get("streams", [])):
            raise RuntimeError(f"FFmpeg produced no video from {path} at {start:.2f}-{end:.2f}s")
        if float(streams["format"].get("duration", 0)) + 0.1 < end - start:
            raise RuntimeError(f"FFmpeg produced a short video from {path} at {start:.2f}-{end:.2f}s")
        converted[path].append((start, end, str(output), -start))

    progress(50, f"Re-encoded {len(jobs)} Windows Media ranges for Resolve")
    return _replace_clips(clips, converted)


def _path_key(path):
    return os.path.normcase(os.path.realpath(path))


def remux_rejected_containers(clips, missing_paths, media_dir, cancel, progress):
    """Stream-copy selected ranges when Resolve rejected a misnamed Matroska file."""
    clips_by_key = defaultdict(list)
    for clip in clips:
        clips_by_key[_path_key(clip.path)].append(clip)
    targets = set()
    codecs = {}
    for missing in missing_paths:
        selected = clips_by_key.get(_path_key(missing))
        if not selected:
            continue
        path = selected[0].path
        progress(52.4, f"Probing rejected Resolve import: {Path(path).name}")
        info = probe(path)
        container = info.get("format", {}).get("format_name", "")
        video = next((stream for stream in info.get("streams", [])
                      if stream.get("codec_type") == "video"), None)
        codec = video.get("codec_name") if video else None
        if Path(path).suffix.lower() not in {".mp4", ".mov"} or "matroska" not in container:
            continue
        if codec not in {"h264", "hevc", "av1", "mpeg4"}:
            continue
        progress(52.4, f"Container mismatch: {Path(path).name} is {container} with {codec}; remuxing selected ranges")
        targets.add(path)
        codecs[path] = codec
    jobs = _selected_ranges(clips, targets)
    if not jobs:
        return clips, set()

    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    converted = defaultdict(list)
    for index, (path, start, end) in enumerate(jobs, 1):
        if cancel.is_set():
            raise InterruptedError("Media remux cancelled")
        raw = media_dir / f"remux-{index:04d}-raw.mp4"
        output = media_dir / f"remux-{index:04d}.mp4"
        progress(52.5, f"Remuxing rejected range {index}/{len(jobs)}: {Path(path).name} at {start:.1f}-{end:.1f}s")
        # The first copy retains the preceding keyframe and absolute PTS.
        # The second rebases timestamps so Resolve sees a short media item;
        # both passes copy compressed HEVC/H.264 packets without encoding.
        codec = codecs[path]
        tag = ["-tag:v", "hvc1"] if codec == "hevc" else []
        try:
            run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-copyts", "-ss", str(start),
                 "-i", path, "-to", str(end + 0.5), "-map", "0:v:0", "-an", "-c:v", "copy", *tag,
                 "-avoid_negative_ts", "disabled", "-movflags", "+faststart", str(raw)], cancel=cancel)
            original_start = float(probe(raw).get("format", {}).get("start_time", 0))
            run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", str(raw),
                 "-map", "0:v:0", "-an", "-c:v", "copy", *tag, "-avoid_negative_ts", "make_zero",
                 "-movflags", "+faststart", str(output)], cancel=cancel)
        finally:
            raw.unlink(missing_ok=True)
        result = probe(output)
        stream = next((row for row in result.get("streams", []) if row.get("codec_type") == "video"), None)
        first = float(result.get("format", {}).get("start_time", 0))
        duration = float(result.get("format", {}).get("duration", 0))
        offset = first - original_start
        if stream is None or stream.get("codec_name") != codec or first > start + offset + 0.05 \
                or first + duration < end + offset - 0.05:
            raise RuntimeError(f"FFmpeg could not remux the selected {codec} range from {path}")
        converted[path].append((start, end, str(output), offset))
    progress(52.6, f"Remuxed {len(jobs)} rejected ranges without re-encoding video")
    return _replace_clips(clips, converted), {_path_key(path) for path in targets}
