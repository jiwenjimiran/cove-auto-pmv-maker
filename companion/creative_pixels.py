"""Visible, resolution-independent image effects and optical-flow interpolation.

These are baked into selected media, so the saved Resolve project and the final
render use the same pixels. No private Resolve/OFX identifiers are assumed.
"""
from functools import lru_cache
from pathlib import Path
import math

import cv2
import numpy as np


def ease(value):
    value = min(1.0, max(0.0, float(value)))
    return value * value * (3 - 2 * value)


def screen(base, light, amount):
    a = base.astype(np.float32) / 255
    b = np.clip(light.astype(np.float32) / 255 * amount, 0, .95)
    return np.uint8(np.clip(1 - (1 - a) * (1 - b), 0, 1) * 255)


def highlights(frame, threshold=.50):
    values = frame.astype(np.float32) / 255
    luma = cv2.cvtColor(values, cv2.COLOR_BGR2GRAY)
    knee = np.clip((luma - threshold + .12) / .24, 0, 1)
    return values * (knee * knee * (3 - 2 * knee))[..., None] * 255


def glow(frame, amount=1.0):
    h, w = frame.shape[:2]
    small = cv2.resize(highlights(frame), (max(16, w // 4), max(16, h // 4)))
    near = cv2.GaussianBlur(small, (0, 0), max(1, w / 220))
    wide = cv2.GaussianBlur(small, (0, 0), max(2, w / 65))
    bloom = cv2.resize(near * .65 + wide * .65, (w, h))
    return screen(frame, bloom, .9 * amount)


def anamorphic(frame, amount=1.0):
    h, w = frame.shape[:2]
    small = cv2.resize(highlights(frame, .65), (max(16, w // 4), max(16, h // 4)))
    streak = cv2.GaussianBlur(small, (0, 0), max(3, w * .055), sigmaY=.65)
    streak *= np.array([1.2, .85, .65], np.float32)
    return screen(frame, cv2.resize(streak, (w, h)), 2.2 * amount)


def light_rays(frame, amount=1.0):
    h, w = frame.shape[:2]
    small = cv2.resize(highlights(frame, .70), (max(24, w // 4), max(24, h // 4)))
    sh, sw = small.shape[:2]
    luminance = small.mean(axis=2)
    # Anchor rays to a real bright region, never a random point in the picture.
    _, peak, _, location = cv2.minMaxLoc(cv2.GaussianBlur(luminance, (0, 0), 2))
    if peak < 10:
        return frame
    rays = np.zeros_like(small)
    for factor in np.linspace(1.0, 1.65, 12):
        matrix = cv2.getRotationMatrix2D(location, 0, float(factor))
        rays += cv2.warpAffine(small, matrix, (sw, sh), borderMode=cv2.BORDER_CONSTANT) / 12
    return screen(frame, cv2.resize(rays, (w, h)), 1.5 * amount)


@lru_cache(maxsize=1)
def person_net():
    path = Path(__file__).with_name("human_segmentation_pphumanseg_2023mar.onnx")
    if not path.is_file():
        raise RuntimeError("The bundled person-segmentation model is missing. Reinstall the current companion ZIP.")
    return cv2.dnn.readNetFromONNX(str(path))


def person_mask(frame):
    """PP-HumanSeg's foreground probability; no performer identity database."""
    net = person_net()
    blob = cv2.dnn.blobFromImage(frame, 1 / 127.5, (192, 192), (127.5, 127.5, 127.5), swapRB=True)
    net.setInput(blob)
    probability = net.forward()[0, 1]
    mask = cv2.resize(probability, (frame.shape[1], frame.shape[0]))
    # Protect the whole person, including a soft safety margin at their outline.
    radius = max(1, round(min(frame.shape[:2]) * .008))
    mask = cv2.dilate(mask, np.ones((2 * radius + 1, 2 * radius + 1), np.uint8))
    return cv2.GaussianBlur(np.clip((mask - .20) / .5, 0, 1), (0, 0), max(1, radius / 2))


def swirly_bokeh(frame, mask, amount=1.0):
    if mask is None or float((mask > .6).mean()) < .015:
        return frame  # Do not invent a subject mask or blur unrecognized people.
    h, w = frame.shape[:2]
    sh, sw = max(24, h // 3), max(24, w // 3)
    small = cv2.resize(frame, (sw, sh))
    ys, xs = np.indices((sh, sw), dtype=np.float32)
    mass = cv2.resize(mask, (sw, sh))
    total = max(.001, float(mass.sum()))
    cx, cy = float((xs * mass).sum() / total), float((ys * mass).sum() / total)
    dx, dy = xs - cx, ys - cy
    radius = np.sqrt((dx / sw) ** 2 + (dy / sh) ** 2)
    blurred = np.zeros_like(small, np.float32)
    for offset in np.linspace(-1, 1, 9):
        angle = offset * .28 * amount * np.minimum(1, radius * 2)
        xx = cx + dx * np.cos(angle) - dy * np.sin(angle)
        yy = cy + dx * np.sin(angle) + dy * np.cos(angle)
        blurred += cv2.remap(small, xx.astype(np.float32), yy.astype(np.float32), cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REFLECT_101) / 9
    blurred = cv2.GaussianBlur(blurred, (0, 0), max(.7, sw * .004 * amount))
    blurred = cv2.resize(blurred, (w, h))
    protected = mask[..., None]
    return np.uint8(np.clip(frame * protected + blurred * (1 - protected), 0, 255))


def outline_echo(frame, amount):
    h, w = frame.shape[:2]
    edges = cv2.Canny(frame, 70, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    edges = cv2.warpAffine(edges, cv2.getRotationMatrix2D((w / 2, h / 2), 0, 1.08),
                           (w, h), borderMode=cv2.BORDER_REFLECT_101)
    return cv2.add(frame, np.uint8(np.clip(edges * (.72 * amount), 0, 255))[..., None].repeat(3, axis=2))


def video_call(frame, amount):
    """An optional brief call-window accent, not a fake app notification."""
    h, w = frame.shape[:2]
    result = cv2.GaussianBlur(frame, (0, 0), max(1, w * .008))
    result = np.uint8(result * .32)
    margin = max(2, round(min(h, w) * .07))
    inner = cv2.resize(frame, (w - 2 * margin, h - 2 * margin))
    result[margin:h - margin, margin:w - margin] = inner
    cv2.rectangle(result, (margin, margin), (w - margin - 1, h - margin - 1), (220, 220, 220), max(1, w // 400))
    radius = max(3, round(min(h, w) * .025))
    for offset, color in ((-1, (65, 65, 65)), (0, (45, 45, 220)), (1, (65, 65, 65))):
        cx, cy = w // 2 + offset * radius * 4, h - margin - radius * 2
        cv2.circle(result, (cx, cy), radius, color, -1, cv2.LINE_AA)
        cv2.line(result, (cx - radius // 2, cy), (cx + radius // 2, cy), (245, 245, 245), max(1, radius // 4))
    return cv2.addWeighted(frame, 1 - min(1, amount), result, min(1, amount), 0)


def sky_mask(frame):
    """Conservative blue-sky key: only a large region connected to the top edge."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    candidate = np.uint8((hsv[..., 0] >= 87) & (hsv[..., 0] <= 119)
                         & (hsv[..., 1] > 55) & (hsv[..., 2] > 110))
    candidate[round(h * .72):] = 0
    _, labels = cv2.connectedComponents(candidate)
    ids = np.unique(labels[:max(1, h // 50)])
    mask = np.isin(labels, ids[ids > 0]).astype(np.float32)
    if mask[:max(1, h // 50)].mean() < .8 or mask.mean() < .12:
        return np.zeros((h, w), np.float32)
    return cv2.GaussianBlur(mask, (0, 0), max(1, min(h, w) * .003))


def replace_sky(frame, mask):
    h, w = frame.shape[:2]
    y, x = np.indices((h, w), dtype=np.float32)
    t = np.clip(y / max(1, h * .65), 0, 1)[..., None]
    sky = np.array([155, 70, 35]) * (1 - t) + np.array([170, 160, 245]) * t
    # Deterministic cloud bands: no external image, rights, or missing project asset.
    clouds = np.clip(np.sin(x / w * 9 + y / h * 17) + np.sin(x / w * 23 - y / h * 11) - .5, 0, 1)
    clouds = cv2.GaussianBlur(clouds, (0, 0), max(1, w * .01))[..., None] * .35
    sky = sky * (1 - clouds) + np.array([225, 220, 245]) * clouds
    return np.uint8(np.clip(frame * (1 - mask[..., None]) + sky * mask[..., None], 0, 255))


def optical_flow_pair(first, second):
    h, w = first.shape[:2]
    scale = min(1.0, 384 / w)
    size = (max(16, round(w * scale)), max(16, round(h * scale)))
    a = cv2.resize(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), size)
    b = cv2.resize(cv2.cvtColor(second, cv2.COLOR_BGR2GRAY), size)
    forward = cv2.calcOpticalFlowFarneback(a, b, None, .5, 3, 21, 4, 7, 1.5, 0)
    backward = cv2.calcOpticalFlowFarneback(b, a, None, .5, 3, 21, 4, 7, 1.5, 0)
    factor = np.array([w / size[0], h / size[1]], np.float32)
    return cv2.resize(forward, (w, h)) * factor, cv2.resize(backward, (w, h)) * factor


def interpolate(first, second, fraction, flows=None):
    if fraction <= 0:
        return first.copy()
    if fraction >= 1:
        return second.copy()
    forward, backward = flows or optical_flow_pair(first, second)
    y, x = np.indices(first.shape[:2], dtype=np.float32)
    a = cv2.remap(first, x - forward[..., 0] * fraction, y - forward[..., 1] * fraction,
                  cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    b = cv2.remap(second, x - backward[..., 0] * (1 - fraction), y - backward[..., 1] * (1 - fraction),
                  cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    return cv2.addWeighted(a, 1 - fraction, b, fraction, 0)


def affine_motion(frame, transform, at, shutter=1 / 60, samples=5):
    """Integrate the animated camera over a shutter interval, with safe borders."""
    h, w = frame.shape[:2]
    total = np.zeros_like(frame, np.float32)
    for offset in np.linspace(-shutter / 2, shutter / 2, samples):
        zoom, angle, dx, dy, center = transform(max(0, at + float(offset)))
        matrix = cv2.getRotationMatrix2D((w * center, h * .5), angle, zoom)
        matrix[:, 2] += (dx * w, dy * h)
        total += cv2.warpAffine(frame, matrix, (w, h), borderMode=cv2.BORDER_REFLECT_101) / samples
    return np.uint8(np.clip(total, 0, 255))
