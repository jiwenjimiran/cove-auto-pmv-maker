"""Sample source frames in place and locate a usable face crop for each edit."""
from __future__ import annotations

import math
from pathlib import Path

MODEL = Path(__file__).with_name("face_detection_yunet_2023mar.onnx")


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


class FaceAnalyzer:
    def __init__(self):
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("Face slice needs OpenCV. Install it for the companion Python with: py -3 -m pip install opencv-python-headless") from exc
        if not MODEL.is_file():
            raise RuntimeError("The bundled face detector model is missing. Reinstall the PMV companion ZIP.")
        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), 0.6, 0.3, 5000)

    def analyze(self, path, start, duration, pane_aspect, keep_centered, cancel=None):
        """Return (offset, horizontal center) samples, or None when a face is absent.

        Every sampled part of the proposed edit must contain a detectable face
        that fits the chosen vertical crop. No source video is copied.
        """
        cv2 = self.cv2
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError("OpenCV cannot read source video for Face slice: " + str(path))
        if hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
            capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
        count = max(2, min(24, math.ceil(duration / 0.4) + 1))
        offsets = [max(0.0, min(duration - 0.04, (index + 0.5) * duration / count)) for index in range(count)]
        observations = []
        previous_x = None
        try:
            for offset in offsets:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Face analysis cancelled")
                capture.set(cv2.CAP_PROP_POS_MSEC, (start + offset) * 1000)
                ok, frame = capture.read()
                if not ok:
                    return None
                height, width = frame.shape[:2]
                scale = min(1.0, 640 / max(width, height))
                if scale < 1:
                    frame = cv2.resize(frame, (max(2, round(width * scale)), max(2, round(height * scale))))
                    height, width = frame.shape[:2]
                crop_width = min(1.0, pane_aspect * height / width)
                self.detector.setInputSize((width, height))
                _, faces = self.detector.detect(frame)
                if faces is None or len(faces) == 0:
                    return None
                candidates = []
                for face in faces:
                    x, _y, face_width, face_height = face[:4]
                    center = float(clamp((x + face_width / 2) / width, 0.0, 1.0))
                    if face_width / width > crop_width:
                        continue
                    score = float(face[-1]) * face_width * face_height
                    if previous_x is not None:
                        score /= 1 + 3 * abs(center - previous_x)
                    candidates.append((score, center, face_width / width))
                if not candidates:
                    return None
                _score, center, face_fraction = max(candidates)
                previous_x = center
                observations.append((offset, center, face_fraction, crop_width))
        finally:
            capture.release()
        if not keep_centered:
            center = sum(item[1] for item in observations) / len(observations)
            crop_width = observations[0][3]
            center = clamp(center, crop_width / 2, 1 - crop_width / 2)
            if any(abs(face_x - center) + face_width / 2 > crop_width / 2 for _, face_x, face_width, _ in observations):
                return None
            return ((0.0, center),)
        # Smooth small detector jitter while still following meaningful movement.
        centers = []
        current = observations[0][1]
        for offset, face_x, _face_width, crop_width in observations:
            current = clamp(0.35 * current + 0.65 * face_x, crop_width / 2, 1 - crop_width / 2)
            if not centers or abs(current - centers[-1][1]) >= 0.025:
                centers.append((offset, float(current)))
        return tuple(centers)
