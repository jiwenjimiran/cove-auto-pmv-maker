"""Sample source frames in place and locate a usable face crop for each edit."""
from __future__ import annotations

import math
import base64
from pathlib import Path

MODEL = Path(__file__).with_name("face_detection_yunet_2023mar.onnx")
RECOGNITION_MODEL = Path(__file__).with_name("face_recognition_sface_2021dec.onnx")


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def cove_face_track(rows, start, duration, pane_aspect, source_width, source_height,
                    allowed_performer_ids, keep_centered):
    """Use linked Cove/AI Faces keyframes when they cover a proposed portrait shot."""
    if not rows or source_width <= 0 or source_height <= 0:
        return None
    allowed = set(int(value) for value in allowed_performer_ids or ())
    crop_width = min(1.0, pane_aspect * source_height / source_width)
    end = start + duration
    by_performer = {}
    for row in rows:
        performer = int(row["performerId"])
        moment = float(row["time"])
        center = float(row["center"])
        face_width = float(row["width"])
        if performer not in allowed or moment < start - 2.5 or moment > end + 2.5:
            continue
        if not (0 <= center <= 1 and 0 < face_width <= crop_width):
            continue
        by_performer.setdefault(performer, []).append((moment, center, face_width, float(row["score"])))
    candidates = []
    for performer, samples in by_performer.items():
        samples.sort()
        if len(samples) < 2 or not any(start <= row[0] <= end for row in samples):
            continue
        if samples[0][0] > start + 2.5 or samples[-1][0] < end - 2.5:
            continue
        if any(right[0] - left[0] > 2.5 for left, right in zip(samples, samples[1:])):
            continue
        if not keep_centered:
            center = clamp(sum(row[1] for row in samples) / len(samples), crop_width / 2, 1 - crop_width / 2)
            if any(abs(row[1] - center) + row[2] / 2 > crop_width / 2 for row in samples):
                continue
            track = ((0.0, center),)
        else:
            track = tuple((clamp(moment - start, 0, duration),
                           clamp(center, crop_width / 2, 1 - crop_width / 2))
                          for moment, center, _width, _score in samples)
        candidates.append((len(samples), sum(row[3] for row in samples) / len(samples), performer, track))
    if not candidates:
        return None
    _count, _score, performer, track = max(candidates)
    return track, performer, None


class FaceAnalyzer:
    def __init__(self, references=None, threshold=0.55):
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("Face slice needs OpenCV. Install it for the companion Python with: py -3 -m pip install opencv-python-headless") from exc
        if not MODEL.is_file():
            raise RuntimeError("The bundled face detector model is missing. Reinstall the PMV companion ZIP.")
        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), 0.6, 0.3, 5000)
        self.references = {}
        self.reference_vectors = None
        self.reference_ids = []
        self._allowed_cache = {}
        self.recognizer = None
        self.threshold = max(0.55, float(threshold))
        if references is not None:
            if not RECOGNITION_MODEL.is_file():
                raise RuntimeError("Bundled SFace recognition model is missing. Reinstall the extension.")
            self.recognizer = cv2.FaceRecognizerSF.create(str(RECOGNITION_MODEL), "")
            for reference in references:
                raw = base64.b64decode(reference.get("dataBase64", ""))
                image = cv2.imdecode(__import__("numpy").frombuffer(raw, dtype="uint8"), cv2.IMREAD_COLOR)
                if image is None:
                    continue
                self.detector.setInputSize((image.shape[1], image.shape[0]))
                _, faces = self.detector.detect(image)
                if faces is None or len(faces) == 0:
                    continue
                face = max(faces, key=lambda row: row[2] * row[3] * row[-1])
                feature = self.recognizer.feature(self.recognizer.alignCrop(image, face))
                self.references.setdefault(int(reference["performerId"]), []).append(feature)
            if self.references:
                import numpy as np
                self.reference_ids = [performer_id for performer_id, features in self.references.items()
                                      for _ in features]
                vectors = np.vstack([feature.reshape(-1) for features in self.references.values() for feature in features])
                self.reference_vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)

    def analyze_match(self, path, start, duration, pane_aspect, keep_centered, cancel=None, rejection=None,
                      allowed_performer_ids=None, face_observations=None, source_dimensions=None):
        """Follow a selected identity through brief occlusion, without zooming."""
        def reject(reason):
            if rejection:
                rejection(reason)
            return None

        if self.recognizer is None:
            track = self.analyze(path, start, duration, pane_aspect, keep_centered, cancel)
            return (track, None, None) if track is not None else reject("no continuous detectable face")
        if source_dimensions and face_observations:
            linked = cove_face_track(face_observations, start, duration, pane_aspect,
                                     source_dimensions[0], source_dimensions[1],
                                     allowed_performer_ids, keep_centered)
            if linked is not None:
                return linked
        allowed = frozenset(int(value) for value in (allowed_performer_ids or ()))
        if allowed_performer_ids is not None and not allowed:
            return reject("video has no linked performer to match")
        if allowed_performer_ids is None:
            reference_vectors, reference_ids = self.reference_vectors, self.reference_ids
        else:
            if allowed not in self._allowed_cache:
                indices = [index for index, performer_id in enumerate(self.reference_ids)
                           if performer_id in allowed]
                self._allowed_cache[allowed] = (
                    self.reference_vectors[indices] if indices else None,
                    [self.reference_ids[index] for index in indices])
            reference_vectors, reference_ids = self._allowed_cache[allowed]
            if reference_vectors is None:
                return reject("linked performers have no selected reference face")
        if reference_vectors is None:
            return reject("no Cove face data or reference image for this video")
        cv2 = self.cv2
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError("OpenCV cannot read source video for Face slice: " + str(path))
        if hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
            capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
        count = max(3, min(24, math.ceil(duration / 0.5) + 1))
        observations = []
        votes = {}
        try:
            for index in range(count):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Face matching cancelled")
                offset = max(0.0, min(duration - 0.04, (index + 0.5) * duration / count))
                capture.set(cv2.CAP_PROP_POS_MSEC, (start + offset) * 1000)
                ok, frame = capture.read()
                if not ok:
                    return reject("source frame unavailable")
                height, width = frame.shape[:2]
                scale = min(1.0, 720 / max(width, height))
                if scale < 1:
                    frame = cv2.resize(frame, (max(2, round(width * scale)), max(2, round(height * scale))))
                    height, width = frame.shape[:2]
                crop_width = min(1.0, pane_aspect * height / width)
                self.detector.setInputSize((width, height))
                _, faces = self.detector.detect(frame)
                candidates = []
                for face in faces if faces is not None else ():
                    x, _y, face_width, _face_height = face[:4]
                    if face_width / width > crop_width:
                        continue
                    feature = self.recognizer.feature(self.recognizer.alignCrop(frame, face))
                    import numpy as np
                    vector = feature.reshape(-1)
                    vector /= max(float(np.linalg.norm(vector)), 1e-8)
                    similarities = reference_vectors @ vector
                    best = int(np.argmax(similarities))
                    similarity = float(similarities[best])
                    if similarity >= self.threshold:
                        candidates.append((similarity, reference_ids[best],
                                           clamp((x + face_width / 2) / width, 0, 1),
                                           face_width / width, crop_width))
                if candidates:
                    score, performer_id, center, face_fraction, crop_width = max(candidates)
                    observations.append((offset, center, face_fraction, crop_width, performer_id, score))
                    votes[performer_id] = votes.get(performer_id, 0) + 1
                if (not observations and offset > max(0.5, duration / count * 3)) or (
                        len(observations) + count - index - 1 < max(2, math.ceil(count * 0.5))):
                    return reject("selected performer missing from sampled frames")
        finally:
            capture.release()
        if len(observations) < max(2, math.ceil(count * 0.5)):
            return reject("too few matching face samples")
        performer_id = max(votes, key=votes.get)
        observations = [row for row in observations if row[4] == performer_id]
        if len(observations) < max(2, math.ceil(count * 0.5)):
            return reject("matching samples split across performers")
        allowed_gap = max(0.5, duration / count * 3)
        if (observations[0][0] > allowed_gap or duration - observations[-1][0] > allowed_gap
                or any(right[0] - left[0] > allowed_gap for left, right in zip(observations, observations[1:]))):
            return reject("matching face absent too long")
        # This is the mean SFace cosine similarity of accepted observations,
        # not a calibrated probability that the identity is correct.
        similarity = sum(row[5] for row in observations) / len(observations)
        if not keep_centered:
            crop_width = observations[0][3]
            center = clamp(sum(row[1] for row in observations) / len(observations), crop_width / 2, 1 - crop_width / 2)
            if any(abs(row[1] - center) + row[2] / 2 > crop_width / 2 for row in observations):
                return reject("face moved outside fixed crop")
            return ((0.0, center),), performer_id, similarity
        centers = []
        current = observations[0][1]
        for offset, face_x, _face_width, crop_width, _id, _score in observations:
            current = clamp(0.35 * current + 0.65 * face_x, crop_width / 2, 1 - crop_width / 2)
            if not centers or abs(current - centers[-1][1]) >= 0.025:
                centers.append((offset, float(current)))
        return tuple(centers), performer_id, similarity

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
