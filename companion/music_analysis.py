"""Beat, bar, and phrase estimates for the PMV edit scheduler."""
from __future__ import annotations

import math
import statistics


class BeatGrid(list):
    def __init__(self, beats, bars=(), phrases=(), tempo=0.0, meter=4, confidence=0.0):
        super().__init__(beats)
        self.bars = tuple(bars)
        self.phrases = tuple(phrases)
        self.tempo = tempo
        self.meter = meter
        self.confidence = confidence


def analyze_music(song, start, end, run, cancel=None, meter="auto"):
    """Decode bounded mono windows and track onsets without copying the song."""
    import numpy as np

    duration = end - start
    if duration <= 0:
        raise ValueError("Song duration must be positive")
    sample_rate, hop, frame_length = 11025, 256, 1024
    beat_times, accents = [], []
    cursor = 0.0
    while cursor < duration:
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Beat analysis cancelled")
        span = min(300.0, duration - cursor)
        raw, _ = run(["ffmpeg", "-v", "error", "-ss", str(start + cursor), "-t", str(span),
                      "-i", str(song), "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"], cancel=cancel)
        samples = np.frombuffer(raw, dtype="<f4")
        if samples.size >= frame_length * 2:
            # Positive log-spectral flux across bass, midrange, and treble.
            # Chunked FFTs keep a five-minute window below ~50 MB of working data.
            envelope = []
            previous = None
            window = np.hanning(frame_length).astype(np.float32)
            total = 1 + (len(samples) - frame_length) // hop
            for first in range(0, total, 512):
                indices = (np.arange(first, min(first + 512, total))[:, None] * hop
                           + np.arange(frame_length)[None, :])
                spectrum = np.log1p(np.abs(np.fft.rfft(samples[indices] * window, axis=1)))
                if previous is not None:
                    spectrum = np.vstack((previous, spectrum))
                flux = np.maximum(0, np.diff(spectrum, axis=0))
                envelope.extend((flux[:, 1:24].mean(axis=1) * 1.4 + flux[:, 24:180].mean(axis=1)
                                 + flux[:, 180:].mean(axis=1) * 0.5).tolist())
                previous = spectrum[-1:]
            onset = np.asarray(envelope, dtype=np.float32)
            onset = np.maximum(0, onset - np.median(onset))
            if onset.max(initial=0) > 0:
                onset = onset / onset.max()
                minimum_lag = max(1, round(0.3 * sample_rate / hop))
                maximum_lag = min(len(onset) // 3, round(1.2 * sample_rate / hop))
                lag_scores = [(float(np.dot(onset[:-lag], onset[lag:])), lag)
                              for lag in range(minimum_lag, maximum_lag + 1)]
                if lag_scores:
                    strongest = max(score for score, _ in lag_scores)
                    # Prefer the shorter pulse when a half-time interpretation
                    # scores almost as well as a longer autocorrelation peak.
                    period = min(lag for score, lag in lag_scores if score >= strongest * 0.82)
                    phases = [sum(float(onset[index]) for index in range(phase, len(onset), period))
                              for phase in range(period)]
                    phase = max(range(period), key=lambda index: phases[index])
                    for frame in range(phase, len(onset), period):
                        radius = max(1, round(period * 0.18))
                        lo, hi = max(0, frame - radius), min(len(onset), frame + radius + 1)
                        actual = lo + int(np.argmax(onset[lo:hi]))
                        local = actual * hop / sample_rate
                        if 0 < local < span:
                            beat_times.append(cursor + local)
                            accents.append(float(onset[actual]))
        cursor += span
    paired = sorted((time, strength) for time, strength in zip(beat_times, accents) if 0 < time < duration)
    paired = [(t, s) for index, (t, s) in enumerate(paired)
              if index == 0 or t - paired[index - 1][0] > 0.12]
    beat_times = [t for t, _ in paired]
    accents = [s for _, s in paired]
    intervals = [b - a for a, b in zip(beat_times, beat_times[1:]) if 0.25 <= b - a <= 2.0]
    if len(intervals) < 4 or sum(accents) < 0.8:
        step = max(0.4, min(1.0, duration / 32))
        beat_times = [i * step for i in range(1, math.ceil(duration / step)) if i * step < duration]
        accents = [0.0] * len(beat_times)
        confidence = 0.0
    else:
        median = statistics.median(intervals)
        spread = statistics.median(abs(value - median) for value in intervals)
        confidence = max(0.0, min(1.0, 1 - spread / max(median, 0.001) * 2))
    median_interval = statistics.median(intervals) if intervals else (beat_times[1] - beat_times[0] if len(beat_times) > 1 else 0.5)
    tempo = 60 / max(median_interval, 0.001)
    if str(meter) in ("3", "4", "6"):
        chosen_meter = int(meter)
    else:
        # Prefer the common four-beat meter unless accents strongly support another.
        scores = {}
        for candidate in (3, 4, 6):
            phases = [sum(accents[i] for i in range(phase, len(accents), candidate)) for phase in range(candidate)]
            scores[candidate] = (max(phases) / max(1, sum(accents))) if accents else 0
        chosen_meter = max((3, 4, 6), key=lambda value: scores[value] - (0 if value == 4 else 0.08))
    phases = [sum(accents[i] for i in range(phase, len(accents), chosen_meter)) for phase in range(chosen_meter)]
    phase = max(range(chosen_meter), key=lambda value: phases[value]) if phases else 0
    bars = [beat_times[i] for i in range(phase, len(beat_times), chosen_meter)]
    phrases = [bars[i] for i in range(4, len(bars), 4)]
    return BeatGrid([0.0, *beat_times, duration], bars, phrases, tempo, chosen_meter, confidence)
