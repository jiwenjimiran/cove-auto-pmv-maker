"""Two-shot, full-composition transitions baked as short Resolve overlay clips.

Samples are clamped to already selected footage. Windows straddle the cut, do
not change the timeline length, and work across grids and portrait layouts.
"""
from collections import OrderedDict
from pathlib import Path
import math
import subprocess
import threading

import cv2
import numpy as np

from creative_pixels import affine_motion, ease, interpolate, optical_flow_pair
from engine import Clip, layout_modes

TRANSITIONS = ("slideTransitions", "zoomTransitions", "shakeTransitions", "blurTransitions", "smoothMorph")


def plan_transitions(clips, beats, options, fps):
    families = [name for name in TRANSITIONS if options.get(name, True) is not False]
    if not families:
        return []
    cuts = sorted({round(clip.record_start * fps) / fps for clip in clips if not clip.underlay and clip.record_start > 0})
    strength = {"subtle": .5, "bold": 1.0, "max": 1.3}.get(options.get("effectIntensity", "bold"), 1.0)
    style = options.get("style", "rhythmic-polish")
    plans, last_end = [], -1
    for serial, cut in enumerate(cuts):
        if style == "cinematic" and serial % 2:
            continue
        before = [c for c in clips if c.record_start < cut - 1e-5 and c.record_start + c.duration >= cut - 1 / fps]
        after = [c for c in clips if abs(c.record_start - cut) < 1 / fps]
        if not before or not after:
            continue
        family = families[len(plans) % len(families)]
        span = {"slideTransitions": .46, "zoomTransitions": 8 / 30, "shakeTransitions": .4,
                "blurTransitions": .72, "smoothMorph": .36}[family]
        span = min(span, min(c.duration for c in before + after) * .7)
        count = max(4, round(span * fps))
        start = round(cut * fps) - count // 2
        end = start + count
        if start / fps < last_end + 1 / fps or start < 0:
            continue
        # A cell expansion already has its own animation and underlay; stacking a
        # transition across it would obscure its movement or sample an incomplete layout.
        if any(c.expansion_from is not None and c.record_start < end / fps
               and c.record_start + c.expansion_duration > start / fps for c in clips):
            continue
        plans.append({"family": family, "cut": cut, "startFrame": start, "frames": count,
                      "strength": strength, "direction": 1 if serial % 2 == 0 else -1})
        last_end = end / fps
    return plans


class FrameReader:
    """Small LRU of decoders; sequential reads within each transition window."""
    def __init__(self):
        self.cache = OrderedDict()

    def read(self, clip, at):
        if clip.path not in self.cache:
            capture = cv2.VideoCapture(clip.path)
            if not capture.isOpened():
                capture.release()
                raise RuntimeError("Cannot read transition source: " + clip.path)
            if len(self.cache) >= 12:
                self.cache.popitem(last=False)[1][0].release()
            self.cache[clip.path] = [capture, -2, None]
        self.cache.move_to_end(clip.path)
        row = self.cache[clip.path]
        capture = row[0]
        fps = capture.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            raise RuntimeError("Invalid transition source frame rate: " + clip.path)
        offset = max(0, min(clip.duration - 1 / fps, at - clip.record_start))
        index = max(0, min(round((clip.source_start + offset) * fps), int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) - 1))
        if index != row[1]:
            if index != row[1] + 1:
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Cannot decode transition frame {index}: {clip.path}")
            row[1], row[2] = index, frame
        return row[2], offset

    def close(self):
        for capture, _, _ in self.cache.values():
            capture.release()
        self.cache.clear()


def fit_frame(frame, width, height, center=.5, mirrored=False, full_height=False):
    h, w = frame.shape[:2]
    if mirrored:
        frame = cv2.flip(frame, 1)
        center = 1 - center
    scale = height / h if full_height else max(width / w, height / h)
    resized = cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_LINEAR)
    rh, rw = resized.shape[:2]
    x = max(0, min(rw - width, round(center * rw - width / 2)))
    y = max(0, (rh - height) // 2)
    cropped = resized[y:y + height, x:x + width]
    if cropped.shape[:2] == (height, width):
        return cropped
    output = np.zeros((height, width, 3), np.uint8)
    oy, ox = (height - cropped.shape[0]) // 2, (width - cropped.shape[1]) // 2
    output[oy:oy + cropped.shape[0], ox:ox + cropped.shape[1]] = cropped
    return output


def compose_scene(clips, stamp, at, width, height, options, reader):
    canvas = np.zeros((height, width, 3), np.uint8)
    modes = layout_modes(options)
    active = [c for c in clips if c.record_start <= stamp < c.record_start + c.duration]
    active.sort(key=lambda c: (not c.underlay, (c.layout_role or modes[0]) == "full-screen", c.pane))
    for clip in active:
        frame, offset = reader.read(clip, at)
        role = clip.layout_role or modes[0]
        center = float(np.interp(offset, [p[0] for p in clip.face_track], [p[1] for p in clip.face_track])) if clip.face_track else clip.crop_center
        if role == "grid":
            x0, x1 = round((clip.pane % 2) * width / 2), round((clip.pane % 2 + 1) * width / 2)
            y0, y1 = round((clip.pane // 2) * height / 2), round((clip.pane // 2 + 1) * height / 2)
        elif role == "three-pane":
            x0, x1, y0, y1 = round(clip.pane * width / 3), round((clip.pane + 1) * width / 3), 0, height
        else:
            x0, x1, y0, y1, center = 0, width, 0, height, .5
        canvas[y0:y1, x0:x1] = fit_frame(frame, x1 - x0, y1 - y0, center,
            clip.mirrored and role != "full-screen", role == "three-pane" and options.get("selectionMode") == "face")
    return canvas


def morph_compatible(a, b):
    """Smooth cuts belong between similar compositions, not unrelated faces."""
    a = cv2.resize(a, (96, 54)).astype(np.float32)
    b = cv2.resize(b, (96, 54)).astype(np.float32)
    difference = float(np.mean(np.abs(cv2.GaussianBlur(a, (0, 0), 2) - cv2.GaussianBlur(b, (0, 0), 2))))
    if difference >= 34:
        return False
    # Similar palette alone is insufficient: require matching spatial structure
    # before warping between shots. Small camera/subject movements still pass.
    def structure(frame):
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (0, 0), 1)
        return (gray - gray.mean()).ravel()
    x, y = structure(a), structure(b)
    variance = float(np.linalg.norm(x) * np.linalg.norm(y))
    if variance < 1e-3:
        return float(x.std()) < 2 and float(y.std()) < 2 and difference < 12
    return float(np.dot(x, y) / variance) >= .90


def transition_frame(outgoing, incoming, fraction, plan, flows=None):
    if fraction <= 0:
        return outgoing.copy()
    if fraction >= 1:
        return incoming.copy()
    h, w = outgoing.shape[:2]
    p = ease(fraction)
    power = math.sin(math.pi * fraction) ** 2
    family, strength = plan["family"], plan["strength"]
    if family == "slideTransitions":
        # Two complete shots share a moving boundary; integrate its movement
        # over the shutter for the tutorial's eased, motion-blurred slide.
        total = np.zeros_like(outgoing, np.float32)
        for dt in np.linspace(-.025, .025, 5):
            pos = round(ease(fraction + dt) * h)
            pair = np.vstack((outgoing, incoming)) if plan["direction"] > 0 else np.vstack((incoming, outgoing))
            top = pos if plan["direction"] > 0 else h - pos
            total += pair[top:top + h] / 5
        return np.uint8(np.clip(total, 0, 255))
    if family == "smoothMorph":
        return interpolate(outgoing, incoming, p, flows)
    mixed = cv2.addWeighted(outgoing, 1 - p, incoming, p, 0)
    if family == "blurTransitions":
        # Peak at the edit, zero at both ends, horizontal directional blur.
        base = outgoing if fraction < .5 else incoming
        sigma = max(.01, w * .065 * strength * power)
        return cv2.GaussianBlur(base, (0, 0), sigma, sigmaY=max(.01, sigma * .025))
    if family == "zoomTransitions":
        blend = ease((fraction - .38) / .24)
        mixed = cv2.addWeighted(outgoing, 1 - blend, incoming, blend, 0)
        def camera(t):
            zoom = 1 + strength * math.sin(math.pi * min(1, t)) ** 2
            return zoom, 0, 0, 0, .5
        return affine_motion(mixed, camera, fraction, shutter=.16, samples=7)
    if family == "shakeTransitions":
        def camera(t):
            envelope = math.sin(math.pi * min(1, t)) ** 2 * strength
            return 1 + .12 * envelope, 2.5 * envelope * math.sin(t * 48), .045 * envelope * math.sin(t * 57), .025 * envelope * math.cos(t * 41), .5
        shaken = affine_motion(mixed, camera, fraction, shutter=.035, samples=5)
        return np.uint8(np.clip(shaken.astype(np.float32) * (1 + .37 * power * min(1, strength)), 0, 255))
    raise ValueError("Unknown transition family: " + family)


def encode_frames(path, frames, width, height, fps, cancel):
    path = Path(path)
    log = path.with_suffix('.log')
    done = threading.Event()
    with log.open('wb') as errors:
        process = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
            '-s', f'{width}x{height}', '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264',
            '-preset', 'fast', '-crf', '16', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
        def watch():
            while not done.wait(.2):
                if cancel.is_set():
                    process.kill()
                    return
        monitor = threading.Thread(target=watch, daemon=True)
        monitor.start()
        try:
            for frame in frames:
                if cancel.is_set():
                    raise InterruptedError('Transition rendering cancelled')
                process.stdin.write(frame.tobytes())
            process.stdin.close()
            if process.wait(timeout=120):
                raise RuntimeError('Transition encoding failed: ' + log.read_text(errors='replace')[-1200:])
        finally:
            done.set()
            if process.poll() is None:
                process.kill()
            process.wait()
    log.unlink(missing_ok=True)


def prepare_transitions(clips, beats, options, folder, width, height, fps, cancel, progress):
    plans = plan_transitions(clips, beats, options, fps)
    if not plans:
        return [], []
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    reader, overlays, receipts = FrameReader(), [], []
    try:
        for index, plan in enumerate(plans):
            if cancel.is_set():
                raise InterruptedError('Transitions cancelled')
            cut = plan['cut']
            # Snapshots choose the shots on either side; frame reads still move
            # through each selected shot and clamp only the short extra handle.
            before, after = cut - .5 / fps, cut + .5 / fps
            outgoing = compose_scene(clips, before, before, width, height, options, reader)
            incoming = compose_scene(clips, after, after, width, height, options, reader)
            flows = None
            if plan['family'] == 'smoothMorph':
                if not morph_compatible(outgoing, incoming):
                    # Respect switches: if only morphs were requested, leave a
                    # clean cut rather than secretly enabling another effect.
                    if options.get('blurTransitions', True) is False:
                        receipts.append(dict(plan, skipped='Shots are too different for a smooth morph'))
                        continue
                    plan = dict(plan, family='blurTransitions', fallback='Shots are too different for a smooth morph')
                else:
                    flows = optical_flow_pair(outgoing, incoming)
            path = folder / f'transition-{index:05d}.mp4'
            progress(50.5 + 1.3 * index / len(plans), f"Compositing {plan['family']}: cut {index + 1}/{len(plans)}")
            def frames():
                for n in range(plan['frames']):
                    at = (plan['startFrame'] + n) / fps
                    a = compose_scene(clips, before, at, width, height, options, reader)
                    b = compose_scene(clips, after, at, width, height, options, reader)
                    yield transition_frame(a, b, n / (plan['frames'] - 1), plan, flows)
            encode_frames(path, frames(), width, height, fps, cancel)
            overlays.append(Clip(0, str(path), 0, plan['frames'] / fps, plan['startFrame'] / fps,
                                 0, None, False, layout_role='full-screen', transition_overlay=True))
            receipts.append(plan)
    finally:
        reader.close()
    return overlays, receipts
