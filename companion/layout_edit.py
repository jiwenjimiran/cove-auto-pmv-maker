"""Phrase-aligned multi-cell and hybrid PMV edit planning."""
from __future__ import annotations

import random
import time
from dataclasses import replace

from advanced_edit import clock_time
from engine import Clip, choose_format
from source_picker import SourceCursor, permitted_ranges


def _musical_times(beats, options):
    duration = float(beats[-1])
    bars = sorted({float(t) for t in getattr(beats, "bars", ()) if 0 < t < duration})
    if not bars:
        meter = int(options.get("beatsPerBar")) if str(options.get("beatsPerBar")) in ("3", "4", "6") else 4
        bars = [float(t) for t in beats[meter:-1:meter]]
    phrases = sorted({float(t) for t in getattr(beats, "phrases", ()) if 0 < t < duration})
    if not phrases:
        phrases = bars[4::4]
    return duration, bars, phrases


def _phase_events(start, end, role, beats, bars, phrases, options, opening):
    count = {"three-pane": 3, "grid": 4, "full-screen": 1}[role]
    maximum = max(0.5, float(options.get("maxClipSeconds", 5)))
    minimum = min(maximum, max(0.25, float(options.get("minClipSeconds", 1))))
    order = [1, 0, 2] if role == "three-pane" else [0, 3, 1, 2] if role == "grid" else [0]
    events = {start: {order[0]} if opening else set(range(count))}
    last = {pane: start for pane in events[start]}
    intro_end = start
    if opening and count > 1:
        cadence = beats[1:-1] if options.get("style") == "high-energy" else bars
        additions = [float(t) for t in cadence if start < t < end - minimum][:count - 1]
        if len(additions) < count - 1:
            raise ValueError(f"Song is too short to fill the {role} opening before its next layout change")
        for pane, at in zip(order[1:], additions):
            events.setdefault(at, set()).add(pane)
            last[pane] = at
        intro_end = additions[-1]
    cadence = beats[1:-1] if count == 1 and options.get("style") == "high-energy" else bars
    turn = 0
    for at in sorted(set(float(t) for t in cadence) | (set(phrases) if count > 1 else set())):
        if at <= intro_end + 0.001 or at >= end - minimum or at <= start:
            continue
        if count > 1 and any(abs(at - phrase) < 0.08 for phrase in phrases):
            changed = set(range(count))
        else:
            due = {pane for pane in range(count) if pane in last and at - last[pane] >= maximum - 0.001}
            target = turn % count
            changed = due or ({target} if target in last and at - last[target] >= minimum else set())
            turn += 1
        if changed:
            events.setdefault(at, set()).update(changed)
            last.update({pane: at for pane in changed})
    # Every active cell must get a new source before it exceeds the clip limit.
    beat_times = sorted(float(t) for t in beats[1:-1])
    for pane in range(count):
        starts = sorted(t for t, changed in events.items() if pane in changed)
        for left, right in zip(starts, [*starts[1:], end]):
            cursor = left
            while right - cursor > maximum + 0.001:
                target = cursor + maximum
                earlier = [t for t in beat_times if cursor + minimum <= t <= target]
                nxt = earlier[-1] if earlier else target
                if right - nxt < minimum:
                    nxt = right - minimum
                if nxt <= cursor + 0.001:
                    break
                events.setdefault(nxt, set()).add(pane)
                cursor = nxt
    return events


def edit_plan(sources, beats, options, layout, cancel=None, progress=None, references=None, log=None):
    hybrid = layout in ("three-pane-full", "grid-full")
    multi_role = "grid" if layout in ("grid", "grid-full") else "three-pane"
    if multi_role == "grid":
        sources = [source for source in sources if int(source["height"]) <= int(source["width"])]
    if not sources:
        raise ValueError("No eligible video sources for this layout")
    duration, bars, phrases = _musical_times(beats, options)
    if duration < 1:
        raise ValueError("Backing song is too short")
    rng = random.Random(options.get("randomSeed"))
    cursors = {int(source["id"]): SourceCursor(source, options, rng, cancel) for source in sources}
    eligible = [source for source in sources if cursors[int(source["id"])].ranges]
    if multi_role == "grid" and len(eligible) < 4:
        raise ValueError("Grid needs four eligible landscape source videos")
    if not eligible:
        raise ValueError("Timestamp or segment restrictions leave no usable sources")
    multi_pool = ([source for source in eligible if int(source["height"]) > int(source["width"])]
                  if multi_role == "three-pane" and options.get("useVerticalVideosOnly") else eligible)
    if not multi_pool:
        raise ValueError("No portrait sources are eligible for the three-pane phase")
    output_width, output_height, _ = choose_format(eligible, layout, options)
    slice_face = options.get("selectionMode", "face") == "face" and not (
        multi_role == "three-pane" and options.get("useVerticalVideosOnly"))
    full_face = hybrid and options.get("fullSelectionMode", "scene") == "face"
    matcher = None
    if slice_face or full_face:
        from face_analysis import FaceAnalyzer
        matcher = FaceAnalyzer(references=references if options.get("matchSelectedPerformers", True) else None,
                               threshold=float(options.get("faceSimilarityThreshold", 0.45)))
        if options.get("matchSelectedPerformers", True) and not matcher.references:
            raise ValueError("No usable reference face for selected performers")
    reference_names = {int(row["performerId"]): row.get("performerName") or f"performer #{row['performerId']}"
                       for row in references or []}
    opening_cadence = beats[1:-1] if options.get("style") == "high-energy" else bars
    needed = 3 if multi_role == "grid" else 2
    opening_times = [float(t) for t in opening_cadence if 0 < t < duration][:needed]
    if len(opening_times) < needed:
        raise ValueError("Song is too short to complete the opening cell sequence")
    boundaries = ([t for t in phrases if t > opening_times[-1] + 0.01 and t < duration - 0.25]
                  if hybrid else [])
    if hybrid and not boundaries:
        raise ValueError("Song needs a phrase boundary after the opening to alternate layouts")
    edges = [0.0, *boundaries, duration]
    maximum = max(0.5, float(options.get("maxClipSeconds", 5)))
    minimum = min(maximum, max(0.25, float(options.get("minClipSeconds", 1))))
    seen = set()
    serial = 0
    clips = []
    outgoing = None
    previous_role = None
    expansion_turn = 0

    def source_allowed(state, at, length):
        source = state["source"]
        return any(row.start - 0.001 <= at and at + length <= row.end + 0.001
                   for row in permitted_ranges(source, options, bool(source.get("tagOnly"))))

    for phase_index, (phase_start, phase_end) in enumerate(zip(edges, edges[1:])):
        role = multi_role if phase_index % 2 == 0 else "full-screen"
        count = {"three-pane": 3, "grid": 4, "full-screen": 1}[role]
        events = _phase_events(phase_start, phase_end, role, beats, bars, phrases, options, phase_index == 0)
        times = sorted(set(events) | {phase_end})
        states = [None] * count
        expansion = None
        for event_index, (left, right) in enumerate(zip(times, times[1:])):
            if cancel and cancel.is_set():
                raise InterruptedError("Edit cancelled")
            changed = sorted(events.get(left, ()))
            pair_mode = role == "three-pane" and len(multi_pool) <= 2 and options.get("mirrorRepeatedSource", True)
            if pair_mode and 2 in changed and 0 not in changed and states[0] is None:
                changed.append(0)
            for pane in changed:
                if pair_mode and pane == 2 and states[0] is not None:
                    states[2] = dict(states[0])
                    continue
                future = next((at for at in times[event_index + 1:] if pane in events.get(at, ())), phase_end)
                required = min(maximum, max(minimum, future - left))
                selection = (options.get("fullSelectionMode", "scene") if role == "full-screen"
                             else "center" if role == "three-pane" and options.get("useVerticalVideosOnly")
                             else options.get("selectionMode", "face"))
                aspect = output_width / output_height if role != "three-pane" else output_width / (3 * output_height)
                chosen = None
                # An expanded clip starts at the exact next source frame of its visible cell.
                if pane == 0 and role == "full-screen" and previous_role in ("grid", "three-pane") and left == phase_start:
                    allow_expansion = previous_role == "grid" or expansion_turn % 2 == 0
                    expansion_turn += 1
                    if allow_expansion:
                        for old_pane, previous in enumerate(outgoing or []):
                            if previous is None:
                                continue
                            start = previous["start"] + left - previous["began"]
                            transition = min(0.5, required / 3)
                            if not source_allowed(previous, start, required):
                                continue
                            if not all(state is None or source_allowed(state, state["start"] + left - state["began"], transition)
                                       for state in outgoing):
                                continue
                            evidence = ((), None, None)
                            if selection == "face":
                                evidence = matcher.analyze_match(previous["source"]["path"], start, required, aspect,
                                                                 bool(options.get("keepFaceCentered", True)), cancel)
                                if not evidence:
                                    continue
                            track, performer, similarity = evidence
                            chosen = dict(source=previous["source"], start=start, segment=previous["segment"],
                                          crop=track[0][1] if track else 0.5, track=track, performer=performer,
                                          began=left, expansion_from=old_pane, expansion_duration=transition,
                                          expansion_layout=previous_role)
                            expansion = chosen
                            if log:
                                log(f"Expanding {previous_role} cell {old_pane + 1} to full screen at song {clock_time(left)} "
                                    f"from video {previous['source']['id']}, source {clock_time(start)}")
                            break
                    if chosen is None and log:
                        log(f"Using a phrase-aligned cut to full screen at {clock_time(left)}; no continuous cell qualifies")
                if chosen is None:
                    pool = eligible if role == "full-screen" else multi_pool
                    candidates = pool[serial % len(pool):] + pool[:serial % len(pool)]
                    candidates.sort(key=lambda source: int(source["id"]) in seen)
                    for offset, source in enumerate(candidates):
                        sid = int(source["id"])
                        if role != "full-screen" and len(pool) >= count and any(
                                state and other_pane != pane and int(state["source"]["id"]) == sid
                                for other_pane, state in enumerate(states)):
                            continue
                        started = time.monotonic()
                        def accept(start, span):
                            if selection != "face":
                                return ((), None, None)
                            return matcher.analyze_match(source["path"], start, span, aspect,
                                                         bool(options.get("keepFaceCentered", True)), cancel)
                        if progress:
                            progress(25 + 14 * left / duration,
                                     f"Choosing {role} cell {pane + 1}/{count}: video {sid}, song {left:.1f}s")
                        found = cursors[sid].next(required, accept)
                        if not found:
                            if log:
                                log(f"Rejected video {sid} for {role} cell {pane + 1} at {clock_time(left)} "
                                    f"after {time.monotonic() - started:.1f}s")
                            continue
                        start, segment, evidence = found
                        track, performer, similarity = evidence
                        crop = track[0][1] if track else 0.5
                        if selection == "random":
                            fraction = min(1.0, aspect * int(source["height"]) / int(source["width"]))
                            crop = rng.uniform(fraction / 2, 1 - fraction / 2)
                        chosen = dict(source=source, start=start, segment=segment, crop=crop,
                                      track=track, performer=performer, began=left)
                        seen.add(sid)
                        serial += offset + 1
                        if log:
                            name = reference_names.get(performer, f"performer #{performer}") if performer else ""
                            match = f", {name} at {similarity:.0%} SFace similarity" if similarity is not None else ""
                            log(f"Selected {role} cell {pane + 1}: video {sid}, source "
                                f"{clock_time(start)}–{clock_time(start + required)}, song {clock_time(left)}{match}")
                        break
                if chosen is None:
                    raise ValueError(f"No eligible {role} clip for cell {pane + 1} at song {left:.2f}s")
                states[pane] = chosen
            if pair_mode and states[0] is not None and states[2] is not None:
                states[2] = dict(states[0])
            if expansion and left == phase_start:
                for old_pane, state in enumerate(outgoing or []):
                    if state is None:
                        continue
                    offset = left - state["began"]
                    clips.append(Clip(int(state["source"]["id"]), state["source"]["path"], state["start"] + offset,
                                      expansion["expansion_duration"], left, old_pane, state["segment"], False,
                                      state["crop"], (), state["performer"], False, previous_role,
                                      None, 0.0, True))
            for pane, state in enumerate(states):
                if state is None or right - left < 0.02:
                    continue
                offset = left - state["began"]
                track = tuple((max(0.0, t - offset), x) for t, x in state["track"] if offset <= t <= offset + right - left)
                if not track and state["track"]:
                    closest = min(state["track"], key=lambda point: abs(point[0] - offset - (right - left) / 2))
                    track = ((0.0, closest[1]),)
                mirrored = pair_mode and pane == 2
                clips.append(Clip(int(state["source"]["id"]), state["source"]["path"], state["start"] + offset,
                                  right - left, left, pane, state["segment"],
                                  any(abs(left - phrase) < 0.08 for phrase in phrases), state["crop"], track,
                                  state["performer"], mirrored, role,
                                  state.get("expansion_from") if left == state["began"] else None,
                                  state.get("expansion_duration", 0.0) if left == state["began"] else 0.0,
                                  False, state.get("expansion_layout", "") if left == state["began"] else ""))
        outgoing = states
        previous_role = role
    if not clips:
        raise ValueError("No video clips could be selected")
    merged = []
    for clip in sorted(clips, key=lambda row: (row.layout_role, row.pane, row.record_start, row.underlay)):
        previous = merged[-1] if merged and merged[-1].pane == clip.pane and merged[-1].layout_role == clip.layout_role else None
        if (previous and not previous.underlay and not clip.underlay and not clip.accent
                and previous.video_id == clip.video_id and previous.segment_id == clip.segment_id
                and previous.mirrored == clip.mirrored and previous.matched_performer_id == clip.matched_performer_id
                and abs(previous.crop_center - clip.crop_center) < 0.001
                and abs(previous.record_start + previous.duration - clip.record_start) < 0.02
                and abs(previous.source_start + previous.duration - clip.source_start) < 0.05
                and previous.duration + clip.duration <= maximum + 0.01):
            track = previous.face_track + tuple((previous.duration + t, x) for t, x in clip.face_track)
            merged[-1] = replace(previous, duration=previous.duration + clip.duration, face_track=track)
        else:
            merged.append(clip)
    return sorted(merged, key=lambda clip: (clip.record_start, clip.pane, clip.underlay))
