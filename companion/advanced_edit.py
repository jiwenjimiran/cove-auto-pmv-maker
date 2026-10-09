"""Bar-aware edits with independently changing portrait panes."""
from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import replace

from engine import Clip, choose_format
from source_picker import SourceCursor


def clock_time(seconds):
    minutes, seconds = divmod(int(round(seconds)), 60)
    return f"{minutes}:{seconds:02d}"


def edit_plan(sources, beats, options, layout, cancel=None, progress=None, references=None, log=None):
    if layout == "three-pane" and options.get("useVerticalVideosOnly"):
        sources = [s for s in sources if int(s["height"]) > int(s["width"])]
    if not sources:
        raise ValueError("No eligible source videos")
    duration = float(beats[-1])
    if duration < 1:
        raise ValueError("Backing song is too short")
    panes = 3 if layout == "three-pane" else 1
    maximum = max(0.5, float(options.get("maxClipSeconds", 5)))
    minimum = min(maximum, max(0.25, float(options.get("minClipSeconds", 1))))
    bar_times = sorted({float(t) for t in getattr(beats, "bars", ()) if minimum <= t < duration - minimum})
    phrase_times = sorted({float(t) for t in getattr(beats, "phrases", ()) if minimum <= t < duration - minimum})
    if not bar_times:
        meter = int(options.get("beatsPerBar")) if str(options.get("beatsPerBar")) in ("3", "4", "6") else 4
        bar_times = [float(t) for t in beats[meter:-1:meter]]
    events = [(0.0, tuple(range(panes)))]
    last_cut = [0.0] * panes
    turn = 0
    for t in sorted(set(bar_times + phrase_times)):
        if t >= duration - minimum:
            continue
        phrase = any(abs(t - p) < 0.08 for p in phrase_times)
        due = [p for p in range(panes) if t - last_cut[p] >= maximum - 0.001]
        if phrase:
            changed = list(range(panes))
        else:
            changed = due or ([turn % panes] if t - last_cut[turn % panes] >= minimum else [])
            turn += 1
        if changed:
            events.append((t, tuple(changed)))
            for p in changed:
                last_cut[p] = t
    # A slow song may have bars longer than the allowed clip. Insert beat cuts.
    beat_candidates = sorted(float(t) for t in beats[1:-1])
    for pane in range(panes):
        times = sorted({t for t, changed in events if pane in changed} | {duration})
        for left, right in zip(times, times[1:]):
            cursor = left
            while right - cursor > maximum + 0.001:
                target = cursor + maximum
                candidates = [b for b in beat_candidates if cursor + minimum <= b <= target]
                nxt = candidates[-1] if candidates else target
                if right - nxt < minimum:
                    nxt = right - minimum
                events.append((nxt, (pane,)))
                cursor = nxt
    changes = {}
    for t, panes_changed in events:
        changes.setdefault(t, set()).update(panes_changed)
    times = sorted(set(changes) | {duration})
    rng = random.Random(options.get("randomSeed"))
    cursors = {int(s["id"]): SourceCursor(s, options, rng, cancel) for s in sources}
    eligible = [s for s in sources if cursors[int(s["id"])].ranges]
    if not eligible:
        raise ValueError("Timestamp bounds leave no usable source ranges")
    selection = (options.get("fullSelectionMode", "face") if panes == 1 else
                 options.get("selectionMode", "face") if not options.get("useVerticalVideosOnly") else "center")
    matcher = None
    if selection == "face":
        from face_analysis import FaceAnalyzer
        matcher = FaceAnalyzer(references=references if options.get("matchSelectedPerformers", True) else None,
                               threshold=float(options.get("faceSimilarityThreshold", 0.55)))
        if options.get("matchSelectedPerformers", True) and not matcher.references:
            raise ValueError("No usable reference face for selected performers. Choose performers with portrait or Cove face images, or disable performer matching.")
    reference_names = {int(row["performerId"]): row.get("performerName") or f"performer #{row['performerId']}"
                       for row in references or []}
    pane_aspect = None
    if panes == 3:
        width, height, _ = choose_format(sources, layout, options)
        pane_aspect = width / (3 * height)
    elif selection == "face":
        width, height, _ = choose_format(sources, layout, options)
        pane_aspect = width / height
    states = [None] * panes
    result = []
    serial = 0
    seen = set()
    failed_length = {}
    diversity = max(0.0, min(1.0, float(options.get("sourceDiversity", 0.8))))
    repeat_factor = 1 + round((1 - diversity) * 3)
    pair_mode = panes == 3 and len(eligible) <= 2 and options.get("mirrorRepeatedSource", True)
    for index, (left, right) in enumerate(zip(times, times[1:])):
        if cancel and cancel.is_set():
            raise InterruptedError("Edit cancelled")
        length = right - left
        if length < 0.02:
            continue
        changed = set(changes.get(left, ()))
        if pair_mode and changed.intersection({0, 2}):
            changed.update({0, 2})
        previous_states = list(states)
        for pane in changed:
            states[pane] = None
        for pane in sorted(changed):
            if pane == 2 and pair_mode:
                states[2] = dict(states[0])
                continue
            chosen = None
            future = [t for t in times[index + 1:] if pane in changes.get(t, ())]
            if pane in (0, 2) and pair_mode:
                future = [t for t in times[index + 1:] if changes.get(t, set()).intersection({0, 2})]
            required = min(maximum, max(minimum, (future[0] if future else duration) - left))
            # The first passes cover every explicitly selected video when the
            # song offers enough edit points; later passes rotate the library.
            start_index = serial if len(seen) < len(eligible) else serial // repeat_factor
            candidates = [eligible[(start_index + offset) % len(eligible)] for offset in range(len(eligible))]
            if len(seen) < len(eligible):
                candidates.sort(key=lambda source: int(source["id"]) in seen)
            if len(changed) == panes and left > 0 and len(eligible) > 1 and previous_states[pane]:
                previous_id = int(previous_states[pane]["source"]["id"])
                candidates.sort(key=lambda source: int(source["id"]) == previous_id)
            for offset, source in enumerate(candidates):
                sid = int(source["id"])
                if sid in failed_length and required >= failed_length[sid] - 0.01:
                    continue
                if len(eligible) > 1 and (len(eligible) >= panes or pair_mode) and any(
                        state and state["source"]["id"] == sid for state in states):
                    continue
                rejection_counts = Counter()

                def accept(start, span):
                    if matcher is None:
                        return ((), None, None)
                    return matcher.analyze_match(source["path"], start, span, pane_aspect,
                                                 bool(options.get("keepFaceCentered", True)), cancel,
                                                 (lambda reason: rejection_counts.update((reason,))) if log else None)
                started = time.monotonic()
                window_count = 0
                last_window_log = 0.0

                def on_window(attempt, window_start, window_length, source_range):
                    nonlocal window_count, last_window_log
                    window_count += 1
                    now = time.monotonic()
                    if log and (window_count == 1 or now - last_window_log >= 10):
                        origin = f"timed segment {source_range.segment_id}" if source_range.segment_id else f"band {source_range.band + 1}"
                        log(f"Scanning video {sid}, pane {pane + 1}, song {clock_time(left)}: "
                            f"source {clock_time(window_start)}–{clock_time(window_start + window_length)} "
                            f"({origin}, window {attempt}); checking scenes and faces")
                        last_window_log = now
                if progress and matcher:
                    progress(25 + 14 * index / max(1, len(times) - 1),
                             f"Matching faces: video {sid} ({offset + 1}/{len(eligible)} candidates), pane {pane + 1}, song {left:.1f}s")
                found = cursors[sid].next(required, accept, on_window)
                if not found:
                    failed_length[sid] = min(required, failed_length.get(sid, required))
                    if log:
                        reasons = ", ".join(f"{reason} ({count})" for reason, count in rejection_counts.most_common(3))
                        log(f"Rejected video {sid}, pane {pane + 1}, song {clock_time(left)}: "
                            f"no usable {('matching face' if matcher else 'scene')} for {required:.1f}s "
                            f"after {window_count} windows in {time.monotonic() - started:.1f}s"
                            + (f"; face checks: {reasons}" if reasons else ""))
                    if progress:
                        progress(25 + 14 * index / max(1, len(times) - 1),
                                 f"Skipping video {sid}: no usable {'matching face' if matcher else 'scene'} for a {required:.1f}s clip")
                if found:
                    start, segment_id, evidence = found
                    previous = previous_states[pane]
                    if (previous and previous["source"]["id"] == sid
                            and abs(start - (previous["start"] + left - previous["began"])) < 0.05):
                        jumped = cursors[sid].next(required, accept, on_window)
                        if jumped:
                            start, segment_id, evidence = jumped
                    track, performer_id, similarity = evidence
                    crop = track[0][1] if track else 0.5
                    if selection == "random":
                        fraction = min(1.0, pane_aspect * int(source["height"]) / int(source["width"]))
                        crop = rng.uniform(fraction / 2, 1 - fraction / 2)
                    chosen = dict(source=source, start=start, segment=segment_id, crop=crop,
                                  track=track, performer=performer_id, began=left)
                    if log:
                        detail = (f" with {reference_names.get(performer_id, f'performer #{performer_id}')} "
                                  f"at {similarity:.0%} match confidence (SFace cosine similarity, not a probability)"
                                  if performer_id is not None and similarity is not None else
                                  " with a detected face" if matcher else "")
                        log(f"Selected slice from video {sid}: source {clock_time(start)}–{clock_time(start + required)}"
                            f" → song {clock_time(left)}–{clock_time(left + required)}, pane {pane + 1}{detail}; "
                            f"{window_count} windows, {time.monotonic() - started:.1f}s")
                    seen.add(sid)
                    serial += offset + 1
                    break
            if chosen is None:
                raise ValueError(f"No usable {'matching face' if matcher else 'scene'} for pane {pane + 1} at {left:.2f}s. Check timestamp bounds, reference portraits, and clip lengths.")
            states[pane] = chosen
            if progress:
                progress(25 + 14 * index / max(1, len(times) - 1),
                         f"Selecting {'matching face and ' if matcher else ''}scene: video {chosen['source']['id']}, pane {pane + 1}, song {left:.1f}s")
        # A repeated video occupying both outside panes uses the exact same
        # source moment. The right pane is flipped; the center has its own crop.
        if pair_mode and states[0] and states[2]:
            states[2] = dict(states[0])
        for pane, state in enumerate(states):
            if state is None:
                continue
            offset = left - state["began"]
            track = tuple((max(0.0, t - offset), x) for t, x in state["track"] if offset <= t <= offset + length)
            if not track and state["track"]:
                nearest = min(state["track"], key=lambda point: abs(point[0] - offset - length / 2))
                track = ((0.0, nearest[1]),)
            phrase = any(abs(left - p) < 0.08 for p in phrase_times)
            mirrored = panes == 3 and pane == 2 and states[0] and state["source"]["id"] == states[0]["source"]["id"] and options.get("mirrorRepeatedSource", True)
            result.append(Clip(int(state["source"]["id"]), state["source"]["path"], state["start"] + offset,
                               length, left, pane, state["segment"], phrase, state["crop"], track,
                               state["performer"], bool(mirrored)))
    if not result:
        raise ValueError("No video clips could be selected")
    merged = []
    for clip in sorted(result, key=lambda row: (row.pane, row.record_start)):
        previous = merged[-1] if merged and merged[-1].pane == clip.pane else None
        if (previous and not clip.accent and previous.video_id == clip.video_id
                and previous.segment_id == clip.segment_id and previous.mirrored == clip.mirrored
                and previous.matched_performer_id == clip.matched_performer_id
                and abs(previous.crop_center - clip.crop_center) < 0.001
                and abs(previous.record_start + previous.duration - clip.record_start) < 0.02
                and abs(previous.source_start + previous.duration - clip.source_start) < 0.05
                and previous.duration + clip.duration <= maximum + 0.01):
            track = previous.face_track + tuple((previous.duration + t, x) for t, x in clip.face_track)
            merged[-1] = replace(previous, duration=previous.duration + clip.duration, face_track=track)
        else:
            merged.append(clip)
    return merged
