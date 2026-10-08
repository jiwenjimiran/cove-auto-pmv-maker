"""Media analysis and edit decisions. Master video files are only read in place."""
from __future__ import annotations

import json
import math
import os
import random
import re
import statistics
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path


def run(args, *, cancel=None, **kwargs):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    try:
        while process.poll() is None:
            if cancel and cancel.is_set():
                process.kill()
                raise InterruptedError("Job cancelled")
            try:
                out, err = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                continue
        else:
            out, err = process.communicate()
    finally:
        if process.poll() is None:
            process.kill()
    if process.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed: {err.decode(errors='replace')[-2000:]}")
    return out, err


def probe(path):
    out, _ = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    return json.loads(out)


def audio_duration(path):
    return float(probe(path)["format"]["duration"])


def choose_format(sources, layout, options):
    if not sources:
        raise ValueError("No eligible video sources")
    short_sides = {min(int(s["width"]), int(s["height"])) for s in sources}
    base = next(iter(short_sides)) if len(short_sides) == 1 and next(iter(short_sides)) in (720, 2160) else 1080
    ratios = [int(s["width"]) / int(s["height"]) for s in sources]
    common = max(ratios) - min(ratios) <= sum(ratios) / len(ratios) * 0.02
    ratio = sum(ratios) / len(ratios) if common else 16 / 9
    if layout == "three-pane" and ratio < 1:
        ratio = 16 / 9
    if ratio >= 1:
        width, height = 2 * round(base * ratio / 2), base
    else:
        width, height = base, 2 * round(base / ratio / 2)
    fps = int(options.get("outputFps") or (60 if all(59.5 <= float(s["fps"]) <= 60.5 for s in sources) else 30))
    if width < 320 or height < 320 or width > 7680 or height > 7680 or fps not in (24, 25, 30, 50, 60):
        raise ValueError("Unsupported render size or frame rate")
    return width, height, fps


def beat_grid(song, start, end, cancel=None):
    # Envelope from a mono 8 kHz analysis stream, about 16 KB per second.
    out, _ = run(["ffmpeg", "-v", "error", "-ss", str(start), "-to", str(end), "-i", str(song),
                  "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], cancel=cancel)
    import array
    samples = array.array("h")
    samples.frombytes(out)
    step = 1600  # 0.2 seconds
    rms = [math.sqrt(sum(v * v for v in samples[i:i + step]) / max(1, len(samples[i:i + step])))
           for i in range(0, len(samples), step)]
    if not rms:
        return [0.0, end - start]
    onset = [0.0] + [max(0.0, rms[i] - rms[i - 1]) for i in range(1, len(rms))]
    baseline = statistics.median(onset)
    peaks = []
    for i in range(2, len(onset) - 2):
        if onset[i] >= max(onset[i - 2:i + 3]) and onset[i] > max(100, baseline * 1.5):
            time = i * 0.2
            if not peaks or time - peaks[-1] >= 0.3:
                peaks.append(time)
    if len(peaks) < 8:
        interval = max(0.5, min(2.0, (end - start) / 32))
        peaks = [i * interval for i in range(1, int((end - start) / interval))]
    return [0.0] + [p for p in peaks if 0 < p < end - start] + [end - start]


def shot_boundaries(path, duration, seek=0, cancel=None):
    # Analyze a sparse, scaled stream. This decodes source in place and writes no video copy.
    try:
        _, err = run(["ffmpeg", "-hide_banner", "-ss", str(seek), "-t", str(duration), "-i", path, "-vf",
                      "fps=1,scale=320:-2,blackdetect=d=1:pix_th=0.1,select='gt(scene,0.3)',showinfo",
                      "-an", "-f", "null", "-"], cancel=cancel)
        points = [float(x) for x in re.findall(rb"pts_time:([0-9.]+)", err)]
        dark = [(float(a), float(b)) for a, b in re.findall(rb"black_start:([0-9.]+) black_end:([0-9.]+)", err)]
        return sorted(set([seek] + [seek + p for p in points if 1 < p < duration - 1] + [seek + duration])), [(seek + a, seek + b) for a, b in dark]
    except RuntimeError:
        return [seek, seek + duration], []


def candidate_ranges(source, tag_only=False, cancel=None):
    segments = source.get("segments") or []
    ranges = [(float(s["start"]), float(s["end"]), int(s["id"]), 2.0) for s in segments if float(s["end"]) - float(s["start"]) >= 0.75]
    if tag_only:
        return ranges
    ranges.extend((float(s["start"]), float(s["end"]), None, 1.8) for s in source.get("savedRanges") or []
                  if float(s["end"]) - float(s["start"]) >= 0.75)
    if ranges:
        return ranges
    duration = float(source["duration"])
    window = min(20.0, duration)
    seeks = [0.0] if duration <= window else sorted({0.0, max(0.0, duration / 2 - window / 2), duration - window})
    for seek in seeks:
        boundaries, dark = shot_boundaries(source["path"], window, seek, cancel)
        for a, b in zip(boundaries, boundaries[1:]):
            dark_overlap = sum(max(0, min(b, end) - max(a, start)) for start, end in dark)
            if b - a >= 1 and dark_overlap < (b - a) * 0.5:
                ranges.append((a, b, None, 1.0))
    if not ranges:
        ranges.append((0.0, float(source["duration"]), None, 0.5))
    return ranges


@dataclass
class Clip:
    video_id: int
    path: str
    source_start: float
    duration: float
    record_start: float
    pane: int
    segment_id: int | None
    accent: bool
    crop_center: float = 0.5
    face_track: tuple[tuple[float, float], ...] = ()


def option_range(options, key, phase, default):
    lower = max(0.0, min(1.0, float(options.get(key + "Min", options.get(key, default)))))
    upper = max(lower, min(1.0, float(options.get(key + "Max", options.get(key, default)))))
    return lower + (upper - lower) * max(0.0, min(1.0, phase))


def edit_plan(sources, beats, options, layout, cancel=None):
    if not sources:
        raise ValueError("No eligible video sources")
    if layout == "three-pane" and options.get("useVerticalVideosOnly"):
        sources = [source for source in sources if int(source["height"]) > int(source["width"])]
        if not sources:
            raise ValueError("No vertical source videos are eligible for three-pane mode")
    style = options.get("style", "rhythmic-polish")
    speed = {"cinematic": 1.6, "rhythmic-polish": 1.0, "high-energy": 0.65}.get(style, 1.0)
    duration = beats[-1]
    phrases = beats[::8]
    cuts = [0.0]
    pos = 0.0
    adherence = max(0.0, min(1.0, float(options.get("beatAdherence", 0.95))))
    while True:
        nearby = [b - a for a, b in zip(beats, beats[1:]) if pos - 2 <= a <= pos + 2 and b > a]
        beat_interval = statistics.median(nearby) if nearby else 1.0
        pace = option_range(options, "pacing", max(0.0, min(1.0, (1.5 - beat_interval) / 1.0)), 0.5)
        target = max(float(options.get("minClipSeconds", 1)), min(float(options.get("maxClipSeconds", 5)),
                     speed * (3.2 - 2 * pace)))
        if pos + target >= duration:
            break
        desired = pos + target
        nearest = min(beats, key=lambda b: abs(b - desired))
        near_phrase = min(phrases, key=lambda b: abs(b - desired))
        if abs(near_phrase - desired) < target * 0.15:
            nearest = near_phrase
        nxt = desired * (1 - adherence) + nearest * adherence
        if nxt - pos < float(options.get("minClipSeconds", 1)):
            nxt = desired
        cuts.append(nxt)
        pos = nxt
    cuts.append(duration)
    pane_count = 3 if layout == "three-pane" else 1
    selection = options.get("selectionMode", "center") if pane_count == 3 and not options.get("useVerticalVideosOnly") else "center"
    if selection not in ("center", "random", "face"):
        raise ValueError("Unknown portrait slice selection mode")
    analyzer = None
    if selection == "face":
        from face_analysis import FaceAnalyzer
        analyzer = FaceAnalyzer()
    pane_aspect = None
    if pane_count == 3:
        output_width, output_height, _ = choose_format(sources, layout, options)
        pane_aspect = output_width / (3 * output_height)
    rng = random.Random(options.get("randomSeed"))
    # A large studio may contain far more videos than the track can show. Decode only
    # those that can actually occupy a cut while keeping format preflight on every source.
    active = sources[:min(len(sources), (len(cuts) - 1) * pane_count)]
    pools = {int(s["id"]): candidate_ranges(s, bool(s.get("tagOnly")), cancel) for s in active}
    usable = [s for s in active if pools[int(s["id"])] ]
    if not usable:
        raise ValueError("No usable ranges in selected sources")
    result = []
    counters = {int(s["id"]): 0 for s in usable}
    for slot, (a, b) in enumerate(zip(cuts, cuts[1:])):
        for pane in range(pane_count):
            # Round robin guarantees each selected source appears when enough slots exist.
            position = slot * pane_count + pane
            diversity = max(0.0, min(1.0, float(options.get("sourceDiversity", 0.8))))
            if position < len(usable):
                source = usable[position]
            else:
                repeat = 1 + round((1 - diversity) * 3)
                source = usable[(len(usable) + (position - len(usable)) // repeat) % len(usable)]
            length = b - a
            candidates = [source] if selection != "face" else [source] + [s for s in usable if s is not source]
            picked = None
            for candidate in candidates:
                sid = int(candidate["id"])
                pool = [range_ for range_ in pools[sid] if not candidate.get("tagOnly") or range_[1] - range_[0] >= length]
                if not pool:
                    continue
                for range_index in range(len(pool)):
                    start, end, segment_id, _quality = pool[(counters[sid] + range_index) % len(pool)]
                    if end - start < length:
                        if candidate.get("tagOnly"):
                            continue
                        starts = [max(0.0, end - length)]
                    else:
                        free = end - start - length
                        starts = [start + fraction * free for fraction in
                                  ((0.5, 0.2, 0.8) if selection == "face" else ((counters[sid] + 1) * 0.618 % 1,))]
                    for candidate_start in starts:
                        face_track = ()
                        center = 0.5
                        if selection == "face":
                            face_track = analyzer.analyze(candidate["path"], candidate_start, length, pane_aspect,
                                                          bool(options.get("keepFaceCentered", True)), cancel)
                            if face_track is None:
                                continue
                            center = face_track[0][1]
                        elif selection == "random":
                            crop_fraction = min(1.0, pane_aspect * int(candidate["height"]) / int(candidate["width"]))
                            center = rng.uniform(crop_fraction / 2, 1 - crop_fraction / 2)
                        picked = (candidate, candidate_start, segment_id, center, face_track)
                        counters[sid] += 1
                        break
                    if picked:
                        break
                if picked:
                    break
            if picked is None:
                if selection == "face":
                    raise ValueError(f"No detectable face throughout a usable {length:.2f}s source range at {a:.2f}s; Face slice rejects that edit point")
                raise ValueError(f"Video {int(source['id'])} has no timed segment long enough for a {length:.2f}s edit")
            source, start, segment_id, center, face_track = picked
            sid = int(source["id"])
            phrase_accent = any(abs(a - phrase) < 0.12 for phrase in phrases)
            result.append(Clip(sid, source["path"], start, length, a, pane, segment_id,
                               phrase_accent or (style == "high-energy" and slot % 4 == 0), center, face_track))
    return result


def sanitize(value):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned[:120] or "Multi"


def output_stem(sources, clips, launch_name=None):
    if launch_name:
        return "PMVMAKER_" + sanitize(launch_name)
    used = [s for s in sources if int(s["id"]) in {c.video_id for c in clips}]
    common = set(used[0].get("performerIds") or [])
    for source in used[1:]:
        common &= set(source.get("performerIds") or [])
    if common:
        names = {pid: name for s in used for pid, name in zip(s.get("performerIds") or [], s.get("performerNames") or [])}
        return "PMVMAKER_" + sanitize("_".join(sorted(names[i] for i in common)))
    studios = {s.get("studioId") for s in used}
    if len(studios) == 1 and None not in studios:
        return "PMVMAKER_" + sanitize(used[0].get("studioName") or "Multi")
    tag_sets = []
    for source in used:
        ids = {c.segment_id for c in clips if c.video_id == int(source["id"])}
        tag_sets.append({s.get("tagName") for s in source.get("segments") or [] if s.get("id") in ids and s.get("tagName")})
    common_tags = set.intersection(*tag_sets) if tag_sets else set()
    return "PMVMAKER_" + sanitize("_".join(sorted(common_tags)) if common_tags else "Multi")


def reserve_output(folder, stem, project_folder="", save_project=False):
    os.makedirs(folder, exist_ok=True)
    for index in range(100000):
        path = Path(folder) / (stem + (f"({index})" if index else "") + ".mp4")
        marker = Path(str(path) + ".reserve")
        try:
            with marker.open("x"):
                pass
        except FileExistsError:
            continue
        project_path = Path(project_folder or folder) / (path.stem + ".drp")
        if path.exists() or save_project and project_path.exists():
            marker.unlink(missing_ok=True)
            continue
        return str(path), marker
    raise RuntimeError("No available output filename")


def prepare_audio(selection, temp, cancel=None):
    if selection["kind"] == "youtube":
        url = selection["url"]
        if not re.match(r"^https://(www\.)?(youtube\.com|youtu\.be)/", url, re.I):
            raise ValueError("Only HTTPS YouTube URLs are accepted")
        target = str(Path(temp) / "download.%(ext)s")
        run(["yt-dlp", "--no-playlist", "-x", "--audio-format", "wav", "-o", target, url], cancel=cancel)
        matches = list(Path(temp).glob("download.*"))
        if len(matches) != 1:
            raise RuntimeError("yt-dlp produced no audio file")
        return str(matches[0])
    source = selection["path"]
    if selection["kind"] == "video":
        output = str(Path(temp) / "extracted.wav")
        run(["ffmpeg", "-y", "-v", "error", "-i", source, "-vn", "-ac", "2", "-ar", "48000", output], cancel=cancel)
        return output
    return source


def mix_audio(song, clips, options, temp, duration, trim_start=0, cancel=None):
    output = str(Path(temp) / "mix.wav")
    mode = options.get("sourceAudio", "mixed")
    filters = ["[0:a]aresample=48000,volume=0.78,atrim=duration=%f,asetpts=PTS-STARTPTS[song]" % duration]
    inputs = ["-ss", str(trim_start), "-t", str(duration), "-i", song]
    selected = [] if mode == "muted" else [c for c in clips if mode == "all" or c.pane == 0 and c.accent]
    source_gain = 0.18 if mode == "mixed" else 0.3 / (max((c.pane for c in clips), default=0) + 1)
    audio_paths = {c.path for c in selected}
    has_audio = {path: any(stream.get("codec_type") == "audio" for stream in probe(path).get("streams", []))
                 for path in audio_paths}
    selected = [c for c in selected if has_audio[c.path]]
    if len(selected) > 80:
        # Render bounded accent stems so a long song never hits Windows command length
        # or ffmpeg filter graph limits. The song enters only the final mix.
        stems = []
        for batch_index in range(0, len(selected), 80):
            batch = selected[batch_index:batch_index + 80]
            begin = batch[0].record_start
            span = max(c.record_start + c.duration for c in batch) - begin
            stem = str(Path(temp) / f"accent-{batch_index//80}.wav")
            stem_inputs, stem_filters = [], []
            for index, clip in enumerate(batch):
                stem_inputs += ["-ss", str(clip.source_start), "-t", str(clip.duration if mode == "all" else min(0.45, clip.duration)), "-i", clip.path]
                delay = round((clip.record_start - begin) * 1000)
                stem_filters.append(f"[{index}:a]aresample=48000,asetpts=PTS-STARTPTS,volume={source_gain},adelay={delay}|{delay}[a{index}]")
            labels = "".join(f"[a{i}]" for i in range(len(batch)))
            stem_filters.append(f"{labels}amix=inputs={len(batch)}:normalize=0,atrim=duration={span}[out]")
            stem_graph = Path(temp) / f"stem-filter-{batch_index//80}.txt"
            stem_graph.write_text(";".join(stem_filters), encoding="utf-8")
            run(["ffmpeg", "-y", "-v", "error", *stem_inputs, "-filter_complex_script", str(stem_graph),
                 "-map", "[out]", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", stem], cancel=cancel)
            stems.append((stem, begin))
        for index, (stem, begin) in enumerate(stems, 1):
            inputs += ["-i", stem]
            delay = round(begin * 1000)
            filters.append(f"[{index}:a]adelay={delay}|{delay}[accent{index}]")
        count = len(stems)
    else:
        for index, clip in enumerate(selected, 1):
            inputs += ["-ss", str(clip.source_start), "-t", str(clip.duration if mode == "all" else min(0.45, clip.duration)), "-i", clip.path]
            delay = int(clip.record_start * 1000)
            filters.append(f"[{index}:a]aresample=48000,asetpts=PTS-STARTPTS,volume={source_gain},adelay={delay}|{delay}[accent{index}]")
        count = len(selected)
    labels = "[song]" + "".join(f"[accent{i}]" for i in range(1, count + 1))
    filters.append(f"{labels}amix=inputs={count+1}:normalize=0,alimiter=limit=0.95:attack=5:release=50,atrim=duration={duration}[out]")
    graph = Path(temp) / "audio-filter.txt"
    graph.write_text(";".join(filters), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex_script", str(graph), "-map", "[out]",
         "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", output], cancel=cancel)
    return output
