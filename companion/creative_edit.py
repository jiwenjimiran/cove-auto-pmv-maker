"""Deterministic musical direction and bounded, per-shot image processing.

Only selected ranges are decoded. Masters stay untouched; generated media can
be retained with a Resolve project. The same plan powers renders and receipts.
"""
from __future__ import annotations

import json
import math
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

from engine import run, probe

FEATURES = ("automaticPacing", "beatPunch", "cameraDrift", "impactRecoil", "speedRamps",
            "motionEcho", "highlightBloom", "rgbSplit", "freezeAccents", "smartFraming",
            "actionSync", "motionMatching", "colorPolish")


def enabled(options, key):
    return options.get(key, True) is not False


def analyze_shot(clip, cancel=None):
    """Motion/quality cues from a small sample, never outside the chosen range."""
    import cv2
    import numpy as np
    raw, _ = run(["ffmpeg", "-v", "error", "-ss", str(clip.source_start), "-t", str(clip.duration),
                  "-i", clip.path, "-vf", "fps=6,scale=160:90", "-an", "-pix_fmt", "bgr24",
                  "-f", "rawvideo", "-"], cancel=cancel, timeout=40)
    frames = np.frombuffer(raw[:len(raw) // 43200 * 43200], np.uint8).reshape(-1, 90, 160, 3)
    motion, directions, luma, sharpness = [], [], [], []
    previous = None
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        luma.append(float(gray.mean()))
        sharpness.append(float(cv2.Laplacian(gray, cv2.CV_32F).var()))
        if previous is not None:
            flow = cv2.calcOpticalFlowFarneback(previous, gray, None, .5, 2, 12, 2, 5, 1.1, 0)
            motion.append(float(np.linalg.norm(flow, axis=2).mean()))
            directions.append(float(np.median(flow[:, :, 0])))
        previous = gray
    return {"peak": (int(np.argmax(motion)) + 1) / 6 if motion else clip.duration / 2,
            "motion": float(np.mean(motion)) if motion else 0,
            "direction": float(np.mean(directions)) if directions else 0,
            "luma": float(np.median(luma)) if luma else 112,
            "sharpness": float(np.median(sharpness)) if sharpness else 0}


def time_knots(duration, hits, cue, options, dominant):
    """Monotone source-time map with exact endpoints and bounded source use."""
    import numpy as np
    output = np.linspace(0, duration, 17)
    source = output.copy()
    target = hits[0][0] if hits else duration / 2
    peak = max(.15 * duration, min(.85 * duration, cue.get("peak", duration / 2)))
    target = max(.2 * duration, min(.8 * duration, target))
    if enabled(options, "actionSync") and hits and cue.get("motion", 0) > .25:
        # Limit retiming to keep sparse/uncertain action estimates natural.
        peak = max(target - duration * .18, min(target + duration * .18, peak))
        source = np.interp(output, [0, target, duration], [0, peak, duration])
    if dominant == "speedRamps":
        weights = 1 + .38 * np.cos(np.linspace(0, 2 * math.pi, 16))
        source = np.interp(np.concatenate(([0], np.cumsum(weights))) / weights.sum() * duration,
                           output, source)
    elif dominant == "freezeAccents":
        index = min(13, max(2, round(target / duration * 16)))
        source[index + 1] = source[index]
    source[0], source[-1] = 0, duration
    return list(zip(output.tolist(), source.tolist()))


def direct(clips, beats, options, cancel=None, progress=None):
    """Choose an effect vocabulary, leader and cooldown for each musical phrase."""
    cues = {}
    result = list(clips)
    for i, clip in enumerate(clips):
        key = (clip.path, clip.source_start, clip.duration)
        if key not in cues:
            if cancel and cancel.is_set():
                raise InterruptedError("Creative analysis cancelled")
            if progress:
                progress(39, f"Analyzing motion and color: shot {i + 1}/{len(clips)}")
            cues[key] = analyze_shot(clip, cancel)
    # Match direction among equal-duration full-screen slots. Keep source diversity,
    # allowed ranges and exact edit timing; do not move linked expansion shots.
    if enabled(options, "motionMatching"):
        for i in range(1, len(result)):
            current, previous = result[i], result[i - 1]
            if current.layout_role not in ("", "full-screen") or current.expansion_from is not None or current.underlay:
                continue
            direction = cues[(previous.path, previous.source_start, previous.duration)]["direction"]
            candidates = [j for j in range(i, min(i + 6, len(result)))
                          if abs(result[j].duration - current.duration) < .001
                          and result[j].layout_role == current.layout_role and result[j].pane == current.pane
                          and result[j].expansion_from is None and not result[j].underlay]
            if candidates:
                def match_score(j):
                    row = cues[(result[j].path, result[j].source_start, result[j].duration)]
                    return abs(row["direction"] - direction) + max(0, 35 - row["sharpness"]) / 100 + abs(row["luma"] - 115) / 500
                best = min(candidates, key=match_score)
                other = result[best]
                result[i] = replace(other, record_start=current.record_start, accent=current.accent)
                result[best] = replace(current, record_start=other.record_start, accent=other.accent)
    plans = []
    last_accent = -10.0
    vocabulary = [key for key in ("beatPunch", "impactRecoil", "speedRamps", "motionEcho", "rgbSplit", "freezeAccents")
                  if enabled(options, key)]
    ordered = sorted(enumerate(result), key=lambda pair: (pair[1].record_start, pair[1].pane))
    decisions = {}
    for serial, (index, clip) in enumerate(ordered):
        cue = cues[(clip.path, clip.source_start, clip.duration)]
        energy = beats.energy_at(clip.record_start) if hasattr(beats, "energy_at") else .5
        phase = int(clip.record_start / max(2, 240 / max(60, getattr(beats, "tempo", 120))))
        count = 4 if clip.layout_role == "grid" else 3 if clip.layout_role == "three-pane" else 1
        leader = clip.pane == phase % count
        hits = [(float(t - clip.record_start), beats.strength_at(t) if hasattr(beats, "strength_at") else .6)
                for t in beats[1:-1] if clip.record_start <= t < clip.record_start + clip.duration]
        hits = [hit for hit in hits if hit[1] >= .35][::2]
        dominant = None
        if vocabulary and leader and not clip.underlay and energy >= .42 and hits and clip.record_start - last_accent >= 1.8:
            band_rows = getattr(beats, "bands", ())
            band = min(band_rows, key=lambda row: abs(row[0] - clip.record_start - hits[0][0])) if band_rows else None
            family = ("beatPunch", "speedRamps", "freezeAccents") if band and band[1] > band[3] else ("impactRecoil", "motionEcho", "rgbSplit")
            choices = [key for key in vocabulary if key in family] or vocabulary
            dominant = choices[phase % len(choices)]
            if dominant in ("speedRamps", "freezeAccents") and (clip.expansion_from is not None or cue["motion"] < .25):
                dominant = "beatPunch" if enabled(options, "beatPunch") else None
            if dominant:
                last_accent = clip.record_start
        style = options.get("style", "rhythmic-polish")
        strength = {"cinematic": .55, "rhythmic-polish": .75, "high-energy": 1.0}.get(style, .75)
        decisions[index] = {"dominant": dominant, "hits": hits, "energy": energy,
                            "strength": strength, "leader": leader, "cue": cue,
                            "drift": enabled(options, "cameraDrift"), "pullback": phase % 2 == 1,
                            "bloom": enabled(options, "highlightBloom") and leader and energy > .65,
                            "framing": enabled(options, "smartFraming"),
                            "color": enabled(options, "colorPolish"), "palette": style,
                            "scale": (0, .035, .065)[phase % 3] if enabled(options, "smartFraming") else 0,
                            "direction": 1 if cue["direction"] >= 0 else -1,
                            "knots": ([(0, 0), (clip.duration, clip.duration)] if clip.underlay or clip.expansion_from is not None
                                      else time_knots(clip.duration, hits, cue, options, dominant))}
    return result, [decisions[i] for i in range(len(result))]


def pulse(at, hits):
    return max((strength * math.exp(-(at - t) / .13) for t, strength in hits if 0 <= at - t < .65), default=0)


def image_effect(frame, at, duration, plan, center=.5, previous=None):
    import cv2
    import numpy as np
    h, w = frame.shape[:2]
    power = pulse(at, plan["hits"]) * plan["strength"]
    dominant = plan["dominant"]
    fraction = at / max(duration, .01)
    drift = (.025 * (1 - fraction if plan.get("pullback") else fraction)) if plan["drift"] else 0
    zoom = 1 + (.008 if plan["drift"] else 0) + plan["scale"] + drift + (.065 * power if dominant == "beatPunch" else 0)
    angle = .5 * power * math.sin(at * 63) if dominant == "impactRecoil" else 0
    if dominant == "impactRecoil":
        zoom += .025
    matrix = cv2.getRotationMatrix2D((w * center, h * .5), angle, zoom)
    if plan["drift"]:
        matrix[0, 2] += w * .006 * math.sin(at / max(duration, .01) * math.pi) * plan["direction"]
    if dominant == "impactRecoil":
        matrix[0, 2] += w * .004 * power * math.sin(at * 91)
        matrix[1, 2] += h * .003 * power * math.cos(at * 71)
    out = cv2.warpAffine(frame, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    if dominant == "motionEcho" and previous is not None:
        out = cv2.addWeighted(out, 1 - .24 * power, previous, .24 * power, 0)
    if dominant == "rgbSplit" and power > .05:
        offset = max(1, round(w * .002 * power))
        out[:, offset:, 2] = out[:, :-offset, 2].copy()
        out[:, :-offset, 0] = out[:, offset:, 0].copy()
    if plan["color"]:
        gain = max(.87, min(1.14, 115 / max(40, plan["cue"]["luma"])))
        values = out.astype(np.float32) / 255
        # Gentle contrast around mid-gray, with smooth shoulder protection.
        values = np.clip((values * gain - .5) * 1.035 + .5, 0, 1)
        palette = {"cinematic": (.99, 1, 1.012), "high-energy": (1.012, 1, .995)}.get(plan.get("palette"), (1, 1, 1))
        values = np.clip(values * np.asarray(palette), 0, 1)
        out = (values * 255).astype(np.uint8)
    if plan["bloom"] and power > .01:
        highlights = np.maximum(out.astype(np.float32) - 165, 0)
        glow = cv2.GaussianBlur(highlights, (0, 0), max(1, w / 180))
        out = np.clip(out.astype(np.float32) + glow * .32 * power, 0, 255).astype(np.uint8)
    return out


def _audio_filter(knots):
    """Apply the identical piecewise time map to source sound, including holds."""
    filters, labels = [], []
    for i, ((t0, s0), (t1, s1)) in enumerate(zip(knots, knots[1:])):
        duration = t1 - t0
        label = f"a{i}"
        labels.append(f"[{label}]")
        if s1 - s0 < 1e-5:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration}[{label}]")
        else:
            rate = (s1 - s0) / duration
            tempos = []
            while rate < .5:
                tempos.append("atempo=0.5")
                rate *= 2
            while rate > 2:
                tempos.append("atempo=2")
                rate /= 2
            tempos.append(f"atempo={rate:.8f}")
            filters.append(f"[1:a]atrim=start={s0}:end={s1},asetpts=PTS-STARTPTS,"
                           + ",".join(tempos) + f",aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={duration}[{label}]")
    return ";".join(filters + ["".join(labels) + f"concat=n={len(labels)}:v=0:a=1[audio]"])


def prepare_creative_clips(clips, plans, options, folder, fps, cancel, progress):
    import cv2
    import numpy as np
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = []
    cache = {}
    for index, (clip, plan) in enumerate(zip(clips, plans)):
        if cancel.is_set():
            raise InterruptedError("Effects cancelled")
        key = json.dumps([clip.path, clip.source_start, clip.duration, plan], sort_keys=True)
        if key in cache and not clip.face_track:
            result.append(replace(clip, path=cache[key], source_start=0))
            continue
        progress(40 + 10 * index / max(1, len(clips)), f"Animating shot {index + 1}/{len(clips)}: {plan['dominant'] or 'polish'}")
        info = probe(clip.path)
        capture = cv2.VideoCapture(clip.path)
        source_fps = capture.get(cv2.CAP_PROP_FPS)
        if not capture.isOpened() or source_fps <= 0:
            capture.release()
            raise RuntimeError(f"Could not decode effects source: {clip.path}")
        capture.set(cv2.CAP_PROP_POS_MSEC, clip.source_start * 1000)
        ok, first = capture.read()
        if not ok:
            capture.release()
            raise RuntimeError(f"No frame at selected source time: {clip.path}")
        h, w = first.shape[:2]
        w, h = w // 2 * 2, h // 2 * 2
        silent = folder / f"shot-{index:05d}-silent.mp4"
        target = folder / f"shot-{index:05d}.mp4"
        error_path = folder / f"shot-{index:05d}.log"
        count = max(1, round((clip.record_start + clip.duration) * fps) - round(clip.record_start * fps))
        command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                   "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(silent)]
        done = threading.Event()
        with error_path.open("wb") as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
            def watchdog():
                while not done.wait(.2):
                    if cancel.is_set():
                        process.kill()
                        return
            monitor = threading.Thread(target=watchdog, daemon=True)
            monitor.start()
            try:
                decoded_frames, current_index, previous = {0: first}, 0, None
                max_source = max(0, int(clip.duration * source_fps) - 1)
                xs, ys = zip(*plan["knots"])
                for number in range(count):
                    if cancel.is_set():
                        raise InterruptedError("Effects cancelled")
                    at = number / fps
                    source_time = min(clip.duration - 1 / source_fps, float(np.interp(at, xs, ys)))
                    desired = min(max_source, max(0, int(source_time * source_fps)))
                    while current_index < min(max_source, desired + 1):
                        ok, decoded = capture.read()
                        if not ok:
                            raise RuntimeError(f"Source ended inside selected shot: {clip.path}")
                        current_index += 1
                        if current_index >= desired:
                            decoded_frames[current_index] = decoded
                    frame = decoded_frames[desired][:h, :w]
                    fraction = max(0, min(1, source_time * source_fps - desired))
                    if fraction > .01 and desired + 1 in decoded_frames:
                        frame = cv2.addWeighted(frame, 1 - fraction, decoded_frames[desired + 1][:h, :w], fraction, 0)
                    decoded_frames = {key: value for key, value in decoded_frames.items() if key >= desired}
                    center = clip.crop_center
                    if clip.face_track:
                        center = float(np.interp(source_time, [p[0] for p in clip.face_track], [p[1] for p in clip.face_track]))
                    output = image_effect(frame, at, clip.duration, plan, center, previous)
                    previous = output
                    process.stdin.write(output.tobytes())
                    if number % max(1, fps * 2) == 0:
                        progress(40 + 10 * (index + number / count) / len(clips),
                                 f"Animating shot {index + 1}/{len(clips)} ({number + 1}/{count} frames)")
                process.stdin.close()
                if process.wait(timeout=120):
                    raise RuntimeError("Effect encoding failed: " + error_path.read_text(errors="replace")[-1500:])
            finally:
                done.set()
                if process.poll() is None:
                    process.kill()
                process.wait()
                capture.release()
        if any(stream["codec_type"] == "audio" for stream in info["streams"]) and options.get("sourceAudio", "mixed") != "muted":
            run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-ss", str(clip.source_start),
                 "-t", str(clip.duration), "-i", clip.path, "-filter_complex", _audio_filter(plan["knots"]),
                 "-map", "0:v", "-map", "[audio]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-t", str(count / fps), str(target)], cancel=cancel, timeout=180)
            silent.unlink()
        else:
            silent.replace(target)
        error_path.unlink(missing_ok=True)
        xs, ys = zip(*plan["knots"])
        # Track coordinates follow the retimed subject, not the old source clock.
        track = tuple((n / fps, float(np.interp(np.interp(n / fps, xs, ys),
                      [p[0] for p in clip.face_track], [p[1] for p in clip.face_track])))
                      for n in range(0, count, max(1, fps // 3))) if clip.face_track else ()
        result.append(replace(clip, path=str(target), source_start=0, face_track=track))
        cache[key] = str(target)
    return result
