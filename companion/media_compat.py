"""Make short, Resolve-readable intermediates for selected Windows Media ranges."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from engine import probe, run


INCOMPATIBLE_CONTAINERS = {".wmv", ".asf"}


def needs_reencode(path):
    return Path(path).suffix.lower() in INCOMPATIBLE_CONTAINERS


def prepare_resolve_clips(clips, media_dir, cancel, progress):
    """Convert only selected ranges; leave original clips intact for audio and metadata."""
    targets = defaultdict(list)
    for clip in clips:
        if needs_reencode(clip.path):
            targets[clip.path].append(clip)
    if not targets:
        return clips

    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
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
        converted[path].append((start, end, str(output)))

    resolve_clips = []
    for clip in clips:
        if not needs_reencode(clip.path):
            resolve_clips.append(clip)
            continue
        end = clip.source_start + clip.duration
        match = next(((start, output) for start, stop, output in converted[clip.path]
                      if start - 0.0001 <= clip.source_start and end <= stop + 0.0001), None)
        if match is None:
            raise RuntimeError(f"No converted range covers video {clip.video_id} at {clip.source_start:.2f}s")
        start, output = match
        resolve_clips.append(replace(clip, path=output, source_start=clip.source_start - start))
    progress(50, f"Re-encoded {len(jobs)} Windows Media ranges for Resolve")
    return resolve_clips
