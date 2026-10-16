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
from creative_pixels import (affine_motion, anamorphic, glow, interpolate, light_rays,
                             optical_flow_pair, outline_echo, person_mask, replace_sky,
                             sky_mask, swirly_bokeh, video_call, ease)

FEATURES = ("automaticPacing", "beatPunch", "cameraDrift", "impactRecoil", "speedRamps",
            "motionEcho", "highlightBloom", "rgbSplit", "freezeAccents", "smartFraming",
            "actionSync", "motionMatching", "colorPolish", "slideTransitions", "zoomTransitions",
            "shakeTransitions", "blurTransitions", "smoothMorph", "swirlyBokeh", "anamorphicFlares",
            "lightRays", "outlineEcho", "superSlowMotion", "videoCall", "skyReplacement")
OPTIONAL_FEATURES = ("videoCall", "skyReplacement")


def enabled(options, key):
    return options.get(key, key not in OPTIONAL_FEATURES) is not False


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
    """Smooth speed curves with exact selected-range endpoints (no extra footage)."""
    import numpy as np
    output = np.linspace(0, duration, 65)
    mid = (output[:-1] + output[1:]) / 2
    target = next((hit[0] for hit in hits if duration * .18 < hit[0] < duration * .82), duration / 2)
    source = output.copy()
    if dominant in ("speedRamps", "superSlowMotion"):
        # Fast edges settle into slow motion around the musical impact. Integrate
        # velocity, rather than jumping playback speed at segment boundaries.
        floor = .085 if dominant == "superSlowMotion" else .22
        width = duration * (.21 if dominant == "superSlowMotion" else .18)
        valley = np.exp(-((mid - target) / max(.02, width)) ** 4)
        rates = 1.8 * (1 - valley) + floor * valley
        source = np.concatenate(([0], np.cumsum(rates))) / rates.sum() * duration
    elif enabled(options, "actionSync") and hits and cue.get("motion", 0) > .25:
        peak = max(target - duration * .18, min(target + duration * .18, cue.get("peak", target)))
        source = np.interp(output, [0, target, duration], [0, peak, duration])
    if dominant == "freezeAccents":
        index = min(56, max(2, round(target / duration * 64)))
        source[index + 1:index + 4] = source[index]
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
    last_accent = -10.0
    vocabulary = [key for key in ("beatPunch", "impactRecoil", "speedRamps", "motionEcho", "rgbSplit", "freezeAccents", "superSlowMotion")
                  if enabled(options, key)]
    looks = [key for key in ("swirlyBokeh", "anamorphicFlares", "lightRays", "outlineEcho", "videoCall", "skyReplacement")
             if enabled(options, key)]
    ordered = sorted(enumerate(result), key=lambda pair: (pair[1].record_start, pair[1].pane))
    decisions, accent_number = {}, int(options.get("randomSeed") or 0) % max(1, len(vocabulary))
    style = options.get("style", "rhythmic-polish")
    strength = {"subtle": .5, "bold": 1.0, "max": 1.3}.get(options.get("effectIntensity", "bold"), 1.0)
    cooldown = {"cinematic": 1.4, "rhythmic-polish": .8, "high-energy": .5}.get(style, .8)
    for serial, (index, clip) in enumerate(ordered):
        cue = cues[(clip.path, clip.source_start, clip.duration)]
        energy = beats.energy_at(clip.record_start) if hasattr(beats, "energy_at") else .5
        phase = int(clip.record_start / max(2, 240 / max(60, getattr(beats, "tempo", 120))))
        count = 4 if clip.layout_role == "grid" else 3 if clip.layout_role == "three-pane" else 1
        leader = clip.pane == phase % count
        hits = [(float(t - clip.record_start), beats.strength_at(t) if hasattr(beats, "strength_at") else .65)
                for t in beats[1:-1] if clip.record_start <= t < clip.record_start + clip.duration]
        hits = [hit for hit in hits if hit[1] >= .25]
        if clip.accent and (not hits or hits[0][0] > .12):
            hits.insert(0, (0.0, max(.65, energy)))
        dominant = None
        if vocabulary and leader and not clip.underlay and hits and clip.record_start - last_accent >= cooldown:
            dominant = vocabulary[accent_number % len(vocabulary)]
            accent_number += 1
            if dominant in ("speedRamps", "superSlowMotion", "freezeAccents") and (clip.expansion_from is not None or cue["motion"] < .2):
                dominant = "beatPunch" if enabled(options, "beatPunch") else None
            if dominant:
                last_accent = clip.record_start
        look = looks[serial % len(looks)] if looks and leader and not clip.underlay else None
        if look == "skyReplacement" and cue["motion"] > 1.2:
            look = None
        decisions[index] = {"dominant": dominant, "look": look, "hits": hits, "energy": energy,
                            "strength": strength, "leader": leader, "cue": cue,
                            "drift": enabled(options, "cameraDrift"), "pullback": phase % 2 == 1,
                            "bloom": enabled(options, "highlightBloom") and not clip.underlay,
                            "framing": enabled(options, "smartFraming"),
                            "color": enabled(options, "colorPolish"), "palette": style,
                            "scale": (0, .04, .08)[phase % 3] if enabled(options, "smartFraming") else 0,
                            "direction": 1 if cue["direction"] >= 0 else -1,
                            "knots": ([(0, 0), (clip.duration, clip.duration)] if clip.underlay or clip.expansion_from is not None
                                      else time_knots(clip.duration, hits, cue, options, dominant))}
    return result, [decisions[i] for i in range(len(result))]


def pulse(at, hits):
    return max((strength * math.exp(-(at - t) / .13) for t, strength in hits if 0 <= at - t < .65), default=0)


def image_effect(frame, at, duration, plan, center=.5, previous=None):
    import cv2
    import numpy as np
    strength = plan["strength"]
    power = pulse(at, plan["hits"]) * strength
    dominant, look = plan["dominant"], plan.get("look")
    out = frame
    if look == "swirlyBokeh":
        out = swirly_bokeh(out, person_mask(out), .8 + strength * .4)
    elif look == "skyReplacement":
        mask = sky_mask(out)
        if mask.any():
            mask *= 1 - person_mask(out)
            out = replace_sky(out, mask)

    def camera(time):
        fraction = ease(time / max(duration, .01))
        kick = pulse(time, plan["hits"]) * strength
        drift = .04 * (1 - fraction if plan.get("pullback") else fraction) if plan["drift"] else 0
        zoom = 1 + plan["scale"] + drift + (.22 * kick if dominant == "beatPunch" else 0)
        angle, dx, dy = 0, 0, 0
        if plan["drift"]:
            zoom += .025
            dx = .012 * math.sin(fraction * math.pi) * plan["direction"]
        if dominant == "impactRecoil":
            zoom += .10 * min(1, kick)
            angle = 2.4 * kick * math.sin(time * 48)
            dx += .028 * kick * math.sin(time * 73)
            dy = .019 * kick * math.cos(time * 57)
        return zoom, angle, dx, dy, center

    out = affine_motion(out, camera, at, samples=5 if dominant in ("beatPunch", "impactRecoil") else 1)
    if dominant == "motionEcho" and previous is not None:
        h, w = out.shape[:2]
        ghost = cv2.warpAffine(previous, cv2.getRotationMatrix2D((w * center, h / 2), 0, 1.05), (w, h), borderMode=cv2.BORDER_REFLECT_101)
        amount = min(.48, .42 * power)
        out = cv2.addWeighted(out, 1 - amount, ghost, amount, 0)
    if dominant == "rgbSplit" and power > .05:
        offset = max(1, round(out.shape[1] * .008 * power))
        out[:, offset:, 2] = out[:, :-offset, 2].copy()
        out[:, :-offset, 0] = out[:, offset:, 0].copy()
    if plan["color"]:
        gain = max(.87, min(1.14, 115 / max(40, plan["cue"]["luma"])))
        values = np.clip((out.astype(np.float32) / 255 * gain - .5) * 1.045 + .5, 0, 1)
        palette = {"cinematic": (.99, 1, 1.012), "high-energy": (1.012, 1, .995)}.get(plan.get("palette"), (1, 1, 1))
        out = (np.clip(values * np.asarray(palette), 0, 1) * 255).astype(np.uint8)
    # A persistent soft glow, with the beat adding emphasis rather than being
    # the only time glow is visible.
    if plan["bloom"]:
        out = glow(out, strength * (.65 + .25 * min(1, power)))
    if look == "anamorphicFlares":
        out = anamorphic(out, strength)
    elif look == "lightRays":
        out = light_rays(out, strength)
    elif look == "outlineEcho":
        out = outline_echo(out, min(1, .25 + power))
    elif look == "videoCall":
        out = video_call(out, ease(min(at, duration - at) / .18))
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
            # WSOLA needs context around very short ramp intervals. Read it
            # within the selected clip, stretch, then trim the exact interval.
            # Padding before atempo also prevents short inputs from failing at EOF.
            context_start = max(0, s0 - .18)
            context_end = min(knots[-1][1], s1 + .18)
            skip = (s0 - context_start) / ((s1 - s0) / duration)
            filters.append(f"[1:a]atrim=start={context_start}:end={context_end},asetpts=PTS-STARTPTS,apad=pad_dur=0.25,"
                           + ",".join(tempos) + f",aresample=48000,aformat=channel_layouts=stereo,atrim=start={skip},asetpts=PTS-STARTPTS,apad,atrim=duration={duration}[{label}]")
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
        progress(40 + 10 * index / max(1, len(clips)), f"Animating shot {index + 1}/{len(clips)}: {plan['dominant'] or 'polish'} + {plan.get('look') or 'glow'}")
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
                flow_key, flows = None, None
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
                        next_frame = decoded_frames[desired + 1][:h, :w]
                        if plan["dominant"] in ("speedRamps", "superSlowMotion"):
                            if flow_key != desired:
                                flows = optical_flow_pair(frame, next_frame)
                                flow_key = desired
                            frame = interpolate(frame, next_frame, fraction, flows)
                        else:
                            frame = cv2.addWeighted(frame, 1 - fraction, next_frame, fraction, 0)
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
            audio_graph = folder / f"shot-{index:05d}-audio.txt"
            audio_graph.write_text(_audio_filter(plan["knots"]), encoding="utf-8")
            run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-ss", str(clip.source_start),
                 "-t", str(clip.duration), "-i", clip.path, "-filter_complex_script", str(audio_graph),
                 "-map", "0:v", "-map", "[audio]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-t", str(count / fps), str(target)], cancel=cancel, timeout=180)
            silent.unlink()
            audio_graph.unlink(missing_ok=True)
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
