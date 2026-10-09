"""Bounded, scene-aware sampling of original source files."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    start: float
    end: float
    segment_id: int | None = None
    band: int = 0


def permitted_ranges(source, options, tag_only=False):
    duration = float(source["duration"])
    lower = max(0.0, float(options.get("minimumTimestampSeconds") or 0))
    upper = min(duration, duration - max(0.0, float(options.get("endBufferSeconds") or 0)))
    if upper <= lower:
        return []
    marked = [Range(max(lower, float(row["start"])), min(upper, float(row["end"])), int(row["id"]))
              for row in source.get("segments") or []]
    marked = [row for row in marked if row.end - row.start >= 0.75]
    if tag_only:
        return marked
    saved = [Range(max(lower, float(row["start"])), min(upper, float(row["end"])))
             for row in source.get("savedRanges") or []]
    saved = [row for row in saved if row.end - row.start >= 0.75]
    if options.get("sampledClipsProgress", False):
        # Short files merge neighboring 5% bands so an edit can fit inside
        # each selected range; long files visit all twenty bands in order.
        desired = max(0.75, float(options.get("maxClipSeconds") or 5))
        band_count = max(1, min(20, int((upper - lower) / desired)))
        bands = [Range(lower + (upper - lower) * index / band_count,
                      lower + (upper - lower) * (index + 1) / band_count, None, index)
                for index in range(band_count)]
    else:
        window = min(20.0, upper - lower)
        positions = sorted({lower, max(lower, (lower + upper - window) / 2), upper - window})
        bands = [Range(position, position + window, None, index) for index, position in enumerate(positions)]
    return marked + saved + bands


def scene_ranges(path, start, duration, cancel=None):
    """Detect cuts in a small, downscaled sample of the requested window."""
    import numpy as np
    from scenedetect.detectors import AdaptiveDetector
    from engine import run

    fps, width, height = 6, 160, 90
    raw, _ = run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(duration), "-i", path,
                  "-vf", f"fps={fps},scale={width}:{height}", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"], cancel=cancel)
    frame_size = width * height * 3
    frames = np.frombuffer(raw[:len(raw) // frame_size * frame_size], dtype=np.uint8).reshape(-1, height, width, 3)
    if not len(frames):
        return []
    detector = AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=6, min_content_val=15.0)
    cuts = []
    for index, frame in enumerate(frames):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Scene analysis cancelled")
        cuts.extend(detector.process_frame(index, frame))
    cuts = [start + index / fps for index in cuts if 0 < index < len(frames)]
    boundaries = [start, *cuts, min(start + duration, start + len(frames) / fps)]
    ranges = []
    for left, right in zip(boundaries, boundaries[1:]):
        a = max(0, round((left - start) * fps))
        b = min(len(frames), round((right - start) * fps))
        if right - left >= 0.75 and b > a and float(frames[a:b].mean()) >= 18:
            ranges.append((left, right))
    return ranges


class SourceCursor:
    def __init__(self, source, options, rng=None, cancel=None):
        self.source = source
        self.options = options
        self.ranges = permitted_ranges(source, options, bool(source.get("tagOnly")))
        self.rng = rng or random.Random()
        self.cancel = cancel
        self.index = 0
        self.shots = []
        self.position = None
        self.current_segment_id = None

    def next(self, length, accept=None):
        if not self.ranges:
            return None
        attempts = 0
        while attempts < len(self.ranges) * 3:
            if self.position is None or not self.shots:
                source_range = self.ranges[self.index % len(self.ranges)]
                self.index += 1
                attempts += 1
                window_length = min(max(1.0, float(self.options.get("rotatedClipLengthSeconds") or 30)),
                                    source_range.end - source_range.start)
                if window_length < length:
                    continue
                free = source_range.end - source_range.start - window_length
                window_start = source_range.start + (self.rng.random() * free if free > 0 else 0)
                self.shots = [(a, b, source_range.segment_id) for a, b in
                              scene_ranges(self.source["path"], window_start, window_length, self.cancel)]
                self.position = self.shots[0][0] if self.shots else None
                if self.position is None:
                    continue
            left, right, segment_id = self.shots[0]
            start = max(left, self.position)
            if start + length > right + 0.001:
                self.shots.pop(0)
                self.position = self.shots[0][0] if self.shots else None
                continue
            # A rejected face sample can be retried once later in the same shot.
            for candidate_start in (start, min(right - length, start + max(0.5, length / 2))):
                result = accept(candidate_start, length) if accept else True
                if result:
                    self.position = candidate_start + length
                    if not self.options.get("cycleLongerClipIntoSegments", False):
                        self.shots = []
                        self.position = None
                    return candidate_start, segment_id, result
            self.shots.pop(0)
            self.position = self.shots[0][0] if self.shots else None
        return None
