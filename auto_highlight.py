#!/usr/bin/env python3
"""Local-first automatic highlight editor MVP."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib import error, request


KEYWORDS = [
    "哈哈",
    "笑死",
    "真的假的",
    "你看",
    "哇",
    "靠",
    "太扯",
    "超猛",
    "等一下",
    "重點是",
    "這個很重要",
    "這邊",
    "這裡",
    "第一次看到",
    "有名",
    "排隊",
    "景點",
    "夜市",
    "車站",
    "老街",
    "入口",
    "好吃",
    "推薦",
    "地標",
    "wow",
    "look",
    "amazing",
    "important",
    "first time",
    "recommend",
]

EMOTION_WORDS = ["哈哈", "笑", "哇", "驚", "扯", "猛", "哭", "喜歡", "好吃", "amazing", "wow", "funny"]
PLACE_WORDS = ["這邊", "這裡", "景點", "夜市", "車站", "老街", "入口", "地標", "店", "路", "街", "market", "station"]
OCR_PLACE_WORDS = ["入口", "出口", "駅", "站", "公園", "水族館", "動物園", "市場", "店", "restaurant", "park", "station"]
VISION_PLACE_WORDS = ["aquarium", "zoo", "park", "station", "market", "restaurant", "temple", "museum", "水族館", "動物園", "公園", "車站", "市場", "餐廳"]
VISION_INTEREST_WORDS = ["animal", "crowd", "performance", "reaction", "close-up", "landmark", "動物", "人群", "表演", "反應", "特寫", "地標"]
FOCUS_ALIAS_GROUPS = {
    "marine_mammal": ["marine mammal", "seal", "sea lion", "walrus", "dolphin", "whale", "海豹", "海獅", "海象", "海豚", "鯨", "海洋動物"],
    "aquatic_animal": ["aquatic animal", "marine animal", "sea animal", "turtle", "fish", "水生動物", "海洋生物", "海龜", "魚"],
    "aquarium": ["aquarium", "marine exhibit", "marine park", "aquatic enclosure", "水族館", "海洋館", "海生館"],
    "animal": ["animal", "animals", "動物"],
    "landmark": ["landmark", "temple", "museum", "地標", "寺", "廟", "博物館"],
    "market": ["market", "night market", "市場", "夜市"],
    "restaurant": ["restaurant", "food stall", "cafe", "餐廳", "店", "攤"],
    "performance": ["performance", "stage show", "live show", "表演", "演出"],
}
FOCUS_DISPLAY_NAMES = {
    "marine_mammal": "海洋動物",
    "aquatic_animal": "水生動物",
    "aquarium": "水族館場景",
    "animal": "動物",
    "landmark": "地標",
    "market": "市場",
    "restaurant": "餐飲店家",
    "performance": "表演",
}
FOCUS_GENERIC_TERMS = {
    "person",
    "people",
    "man",
    "woman",
    "child",
    "children",
    "water",
    "glass",
    "indoor",
    "outdoor",
    "scene",
    "video",
    "image",
    "close-up",
    "close up",
    "rock",
    "rocks",
    "railing",
    "metal railing",
    "fence",
    "net",
    "netting",
    "barrier",
    "platform",
    "roof",
    "structure",
    "tank",
}
THUMB_WIDTH = 768
QUALITY_FRAME_SIZE = 64
DEFAULT_OUTPUT_SIZE = "1080x1920"
DEFAULT_RENDER_CRF = 28
DEFAULT_RENDER_PRESET = "medium"
DEFAULT_AUDIO_BITRATE = "128k"
DEFAULT_CLIP_PADDING = 2.5


@dataclass(frozen=True)
class Candidate:
    id: str
    start: float
    end: float
    transcript: str
    signals: dict[str, Any]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class RenderSettings:
    output_size: str
    crf: int
    preset: str
    audio_bitrate: str
    video_bitrate: str = ""


def log(message: str) -> None:
    print(message, flush=True)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required tool: {name}")


def run_command(args: list[str]) -> None:
    log("+ " + " ".join(args))
    try:
        subprocess.run(args, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {' '.join(args)}") from exc


def run_capture(args: list[str]) -> str:
    try:
        completed = subprocess.run(args, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {' '.join(args)}\n{stderr}") from exc
    return completed.stdout


def run_binary_capture(args: list[str]) -> bytes:
    try:
        completed = subprocess.run(args, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {' '.join(args)}\n{stderr}") from exc
    return completed.stdout


def format_time(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def video_duration(video_path: Path) -> float:
    require_tool("ffprobe")
    output = run_capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )
    try:
        return float(output.strip())
    except ValueError as exc:
        raise SystemExit(f"Could not read video duration from ffprobe output: {output!r}") from exc


def parse_output_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("output size must use WIDTHxHEIGHT, for example 1080x1920")
    width = int(match.group(1))
    height = int(match.group(2))
    if width < 2 or height < 2:
        raise argparse.ArgumentTypeError("output size must be at least 2x2")
    return width, height


def output_size_arg(value: str) -> str:
    width, height = parse_output_size(value)
    return f"{width}x{height}"


def crf_arg(value: str) -> int:
    try:
        crf = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("CRF must be an integer from 0 to 51") from exc
    if not 0 <= crf <= 51:
        raise argparse.ArgumentTypeError("CRF must be an integer from 0 to 51")
    return crf


def render_scale_filter(output_size: str) -> str:
    width, height = parse_output_size(output_size)
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1"


def render_encoding_args(settings: RenderSettings) -> list[str]:
    args = [
        "-vf",
        render_scale_filter(settings.output_size),
        "-c:v",
        "libx264",
        "-preset",
        settings.preset,
    ]
    if settings.video_bitrate:
        args.extend(["-b:v", settings.video_bitrate])
    else:
        args.extend(["-crf", str(settings.crf)])
    args.extend(["-c:a", "aac", "-b:a", settings.audio_bitrate, "-movflags", "+faststart"])
    return args


def init_work_dir(out_dir: Path, source_video: Path) -> None:
    if out_dir.exists() and any(out_dir.iterdir()):
        log(f"Using existing work directory: {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("clips", "thumbnails", "output"):
        (out_dir / name).mkdir(parents=True, exist_ok=True)
    source = {
        "source_video": str(source_video.resolve()),
        "duration_sec": video_duration(source_video),
    }
    write_json(out_dir / "source.json", source)


def extract_audio(source_video: Path, out_dir: Path) -> Path:
    require_tool("ffmpeg")
    audio_path = out_dir / "audio.wav"
    if audio_path.exists():
        log(f"Audio already exists: {audio_path}")
        return audio_path
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio_path),
        ]
    )
    return audio_path


def transcribe_audio(audio_path: Path, out_dir: Path, model: str) -> Path:
    transcript_path = out_dir / "transcript.json"
    if transcript_path.exists():
        log(f"Transcript already exists: {transcript_path}")
        return transcript_path

    code = (
        "import json, sys\n"
        "from faster_whisper import WhisperModel\n"
        "audio, model_name, out = sys.argv[1:4]\n"
        "model = WhisperModel(model_name, device='auto', compute_type='auto')\n"
        "segments, info = model.transcribe(audio, vad_filter=True)\n"
        "data = {'language': info.language, 'duration_sec': info.duration, 'segments': []}\n"
        "for i, seg in enumerate(segments):\n"
        "    data['segments'].append({'id': f't_{i:05d}', 'start': seg.start, 'end': seg.end, 'text': seg.text.strip()})\n"
        "with open(out, 'w', encoding='utf-8') as f:\n"
        "    json.dump(data, f, ensure_ascii=False, indent=2)\n"
        "    f.write('\\n')\n"
    )
    run_command([sys.executable, "-c", code, str(audio_path), model, str(transcript_path)])
    return transcript_path


def normalize_segment(raw: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": raw.get("id", f"t_{index:05d}"),
        "start": float(raw["start"]),
        "end": float(raw["end"]),
        "text": str(raw.get("text", "")).strip(),
    }


def transcript_segments(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    return [normalize_segment(seg, i) for i, seg in enumerate(transcript.get("segments", []))]


def text_hits(text: str, words: list[str]) -> list[str]:
    lowered = text.lower()
    return [word for word in words if word.lower() in lowered]


def transcript_text_between(segments: list[dict[str, Any]], start: float, end: float) -> str:
    parts = [seg["text"] for seg in segments if seg["end"] > start and seg["start"] < end and seg["text"]]
    return " ".join(parts).strip()


def clamp_segment(start: float, end: float, duration: float) -> tuple[float, float]:
    return max(0.0, start), min(duration, max(start, end))


def candidate_from_window(
    candidate_id: str,
    start: float,
    end: float,
    segments: list[dict[str, Any]],
    duration: float,
) -> Optional[Candidate]:
    start, end = clamp_segment(start, end, duration)
    if end - start < 8:
        return None
    text = transcript_text_between(segments, start, end)
    if not text:
        return None
    keywords = text_hits(text, KEYWORDS)
    emotion_words = text_hits(text, EMOTION_WORDS)
    place_words = text_hits(text, PLACE_WORDS)
    utterances = [seg for seg in segments if seg["end"] > start and seg["start"] < end]
    speech_seconds = sum(max(0.0, min(end, seg["end"]) - max(start, seg["start"])) for seg in utterances)
    density = min(1.0, speech_seconds / max(1.0, end - start))
    signals = {
        "keywords": keywords,
        "emotion_words": emotion_words,
        "place_words": place_words,
        "speech_density": round(density, 3),
        "utterance_count": len(utterances),
        "question_exclamation_count": sum(text.count(ch) for ch in ("?", "？", "!", "！")),
    }
    return Candidate(candidate_id, round(start, 3), round(end, 3), text, signals)


def merge_candidates(candidates: list[Candidate], max_gap: float = 10.0, max_duration: float = 75.0) -> list[Candidate]:
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda item: (item.start, item.end))
    merged: list[Candidate] = []
    current = ordered[0]
    for candidate in ordered[1:]:
        can_merge = candidate.start - current.end < max_gap and candidate.end - current.start <= max_duration
        if can_merge:
            current = merge_two_candidates(current, candidate)
        else:
            merged.append(current)
            current = candidate
    merged.append(current)
    return [renumber_candidate(candidate, i) for i, candidate in enumerate(merged)]


def merge_two_candidates(left: Candidate, right: Candidate) -> Candidate:
    signals = {
        "keywords": sorted(set(left.signals.get("keywords", []) + right.signals.get("keywords", []))),
        "emotion_words": sorted(set(left.signals.get("emotion_words", []) + right.signals.get("emotion_words", []))),
        "place_words": sorted(set(left.signals.get("place_words", []) + right.signals.get("place_words", []))),
        "speech_density": round(max(left.signals.get("speech_density", 0), right.signals.get("speech_density", 0)), 3),
        "utterance_count": left.signals.get("utterance_count", 0) + right.signals.get("utterance_count", 0),
        "question_exclamation_count": left.signals.get("question_exclamation_count", 0)
        + right.signals.get("question_exclamation_count", 0),
    }
    transcript = merge_transcript_strings(left.transcript, right.transcript)
    return Candidate(left.id, left.start, max(left.end, right.end), transcript, signals)


def merge_transcript_strings(left: str, right: str) -> str:
    if not left:
        return right
    if not right or right in left:
        return left
    if left in right:
        return right

    left_tokens = left.split()
    right_tokens = right.split()
    max_overlap = min(len(left_tokens), len(right_tokens))
    for overlap in range(max_overlap, 0, -1):
        if left_tokens[-overlap:] == right_tokens[:overlap]:
            return " ".join(left_tokens + right_tokens[overlap:])
    return f"{left} {right}"


def renumber_candidate(candidate: Candidate, index: int) -> Candidate:
    return Candidate(f"seg_{index:03d}", candidate.start, candidate.end, candidate.transcript, candidate.signals)


def trim_candidate(candidate: Candidate, min_duration: float = 12.0, max_duration: float = 75.0) -> Candidate:
    duration = candidate.duration
    start = candidate.start
    end = candidate.end
    if duration < min_duration:
        extra = (min_duration - duration) / 2
        start = max(0.0, start - extra)
        end = end + extra
    elif duration > max_duration:
        end = start + max_duration
    return Candidate(candidate.id, round(start, 3), round(end, 3), candidate.transcript, candidate.signals)


def split_long_candidate(
    candidate: Candidate,
    segments: list[dict[str, Any]],
    duration: float,
    target_duration: float = 24.0,
    step: float = 16.0,
) -> list[Candidate]:
    if candidate.duration < 32:
        return []
    windows: list[tuple[float, float, float, str]] = []
    utterances = [seg for seg in segments if seg["end"] > candidate.start and seg["start"] < candidate.end and seg.get("text")]
    for utterance in utterances:
        text = utterance["text"]
        score = (
            len(text_hits(text, KEYWORDS)) * 2.5
            + len(text_hits(text, EMOTION_WORDS)) * 1.5
            + len(text_hits(text, PLACE_WORDS)) * 0.8
            + sum(text.count(ch) for ch in ("?", "？", "!", "！")) * 0.8
            + 0.4
        )
        center = (utterance["start"] + utterance["end"]) / 2
        start = max(candidate.start, center - target_duration / 2)
        end = min(candidate.end, start + target_duration)
        start = max(candidate.start, end - target_duration)
        windows.append((score, start, end, "transcript_event"))

    cursor = candidate.start
    while cursor + 12 <= candidate.end:
        end = min(candidate.end, cursor + target_duration)
        if candidate.end - end < 8:
            end = candidate.end
        windows.append((0.2, cursor, end, "even_window"))
        if end >= candidate.end:
            break
        cursor += step

    ordered_windows: list[tuple[float, float, float, str]] = []
    for score, start, end, reason in sorted(windows, key=lambda item: item[0], reverse=True):
        if end - start < 12:
            continue
        if any(max(0.0, min(end, used_end) - max(start, used_start)) / max(1.0, min(end - start, used_end - used_start)) > 0.55 for _, used_start, used_end, _ in ordered_windows):
            continue
        ordered_windows.append((score, start, end, reason))
    ordered_windows.sort(key=lambda item: item[1])

    splits: list[Candidate] = []
    for score, start, end, reason in ordered_windows:
        split = candidate_from_window(f"{candidate.id}_part_{len(splits):02d}", start, end, segments, duration)
        if split and split.duration >= 12:
            signals = {
                **split.signals,
                "candidate_type": "subclip",
                "parent_candidate_id": candidate.id,
                "split_reason": reason,
                "split_event_score": round(score, 3),
            }
            splits.append(Candidate(split.id, split.start, split.end, split.transcript, signals))
    return splits


def expand_with_subclips(candidates: list[Candidate], segments: list[dict[str, Any]], duration: float) -> list[Candidate]:
    expanded: list[Candidate] = []
    for candidate in candidates:
        expanded.append(candidate)
        expanded.extend(split_long_candidate(candidate, segments, duration))
    return expanded


def generate_candidates_from_transcript(transcript: dict[str, Any], source_duration: Optional[float] = None) -> list[dict[str, Any]]:
    segments = transcript_segments(transcript)
    duration = source_duration or float(transcript.get("duration_sec") or (segments[-1]["end"] if segments else 0.0))
    raw: list[Candidate] = []

    for seg in segments:
        if text_hits(seg["text"], KEYWORDS):
            candidate = candidate_from_window(f"raw_{len(raw):04d}", seg["start"] - 8, seg["end"] + 20, segments, duration)
            if candidate:
                raw.append(candidate)

    window_size = 30.0
    step = 10.0
    cursor = 0.0
    while cursor < duration:
        candidate = candidate_from_window(f"raw_{len(raw):04d}", cursor, min(duration, cursor + window_size), segments, duration)
        if candidate and quick_window_score(candidate) >= 2.5:
            raw.append(candidate)
        cursor += step

    raw.extend(generate_speech_cluster_candidates(segments, duration))

    merged = merge_candidates(raw)
    trimmed = [trim_candidate(candidate) for candidate in merged if candidate.duration >= 8]
    expanded = expand_with_subclips(trimmed, segments, duration)
    return [candidate_to_dict(renumber_candidate(candidate, i)) for i, candidate in enumerate(expanded)]


def generate_speech_cluster_candidates(segments: list[dict[str, Any]], duration: float) -> list[Candidate]:
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for segment in segments:
        if not segment["text"]:
            continue
        if current and segment["start"] - current[-1]["end"] > 15:
            clusters.append(current)
            current = []
        current.append(segment)
    if current:
        clusters.append(current)

    candidates: list[Candidate] = []
    for cluster in clusters:
        start = cluster[0]["start"] - 5
        end = cluster[-1]["end"] + 7
        candidate = candidate_from_window(f"raw_{len(candidates):04d}", start, end, segments, duration)
        if candidate:
            signals = {**candidate.signals, "fallback_reason": "speech_cluster"}
            candidates.append(Candidate(candidate.id, candidate.start, candidate.end, candidate.transcript, signals))
    return candidates


def quick_window_score(candidate: Candidate) -> float:
    signals = candidate.signals
    return (
        len(signals.get("keywords", [])) * 1.5
        + len(signals.get("emotion_words", [])) * 0.8
        + len(signals.get("place_words", [])) * 0.6
        + float(signals.get("speech_density", 0)) * 3.0
        + min(2.0, float(signals.get("question_exclamation_count", 0)) * 0.5)
    )


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "start": candidate.start,
        "end": candidate.end,
        "duration_sec": round(candidate.duration, 3),
        "transcript": candidate.transcript,
        "signals": candidate.signals,
    }


def sample_timestamps(start: float, end: float, count: int = 3) -> list[float]:
    duration = max(0.0, end - start)
    if duration == 0 or count <= 0:
        return []
    if count == 1:
        return [round(start + duration / 2, 3)]
    padding = min(2.0, duration * 0.15)
    inner_start = start + padding
    inner_end = end - padding
    if inner_end <= inner_start:
        return [round(start + duration / 2, 3)]
    step = (inner_end - inner_start) / (count - 1)
    return [round(inner_start + step * index, 3) for index in range(count)]


def frame_quality_from_gray(raw: bytes, width: int = QUALITY_FRAME_SIZE, height: int = QUALITY_FRAME_SIZE) -> dict[str, float]:
    expected = width * height
    if len(raw) < expected:
        return {"brightness": 0.0, "contrast": 0.0, "sharpness": 0.0}
    pixels = raw[:expected]
    values = list(pixels)
    mean = sum(values) / expected
    variance = sum((value - mean) ** 2 for value in values) / expected
    horizontal_diff = 0
    vertical_diff = 0
    horizontal_count = 0
    vertical_count = 0
    for y in range(height):
        row = y * width
        for x in range(width - 1):
            horizontal_diff += abs(pixels[row + x] - pixels[row + x + 1])
            horizontal_count += 1
    for y in range(height - 1):
        row = y * width
        next_row = (y + 1) * width
        for x in range(width):
            vertical_diff += abs(pixels[row + x] - pixels[next_row + x])
            vertical_count += 1
    sharpness = (horizontal_diff + vertical_diff) / max(1, horizontal_count + vertical_count)
    return {
        "brightness": round(mean / 255.0, 3),
        "contrast": round((variance ** 0.5) / 255.0, 3),
        "sharpness": round(sharpness / 255.0, 3),
    }


def extract_quality_frame(source_video: Path, timestamp: float) -> bytes:
    return run_binary_capture(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(timestamp),
            "-i",
            str(source_video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={QUALITY_FRAME_SIZE}:{QUALITY_FRAME_SIZE},format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )


def extract_thumbnail(source_video: Path, timestamp: float, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            str(timestamp),
            "-i",
            str(source_video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={THUMB_WIDTH}:-1",
            str(output_path),
        ]
    )


def ocr_thumbnail(image_path: Path, languages: str) -> str:
    if shutil.which("tesseract") is None:
        return ""
    try:
        output = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", languages],
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError:
        return ""
    return " ".join(output.split())


def parse_vision_response(text: str) -> dict[str, Any]:
    try:
        parsed = parse_first_json(text)
    except Exception:
        parsed = {"description": " ".join(text.split())}
    return {
        "description": str(parsed.get("description", "")).strip(),
        "subjects": parsed.get("subjects", []) if isinstance(parsed.get("subjects", []), list) else [],
        "setting": str(parsed.get("setting", "")).strip(),
        "actions": parsed.get("actions", []) if isinstance(parsed.get("actions", []), list) else [],
        "visual_hook": str(parsed.get("visual_hook", "")).strip(),
        "quality_note": str(parsed.get("quality_note", "")).strip(),
    }


def vision_response_missing_image(parsed: dict[str, Any]) -> bool:
    text = " ".join(
        str(parsed.get(key, ""))
        for key in ("description", "setting", "visual_hook", "quality_note")
    ).lower()
    patterns = [
        "no image",
        "no thumbnail",
        "image missing",
        "missing visual",
        "unable to access",
        "cannot access",
        "cannot view",
        "not provided",
        "please upload",
    ]
    return any(pattern in text for pattern in patterns)


def describe_thumbnail_with_ollama(image_path: Path, model: str, ollama_url: str, timeout_sec: float = 120.0) -> dict[str, Any]:
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    prompt = (
        "You are inspecting one actual video frame for highlight editing. "
        "Use only visible evidence in the image. Describe broad visible categories such as people, water, rocks, animals, vehicles, food, signs, or buildings when present. "
        "Use 'uncertain' only for ambiguous subjects. Do not infer sports, crowds, indoor venues, readable signs, or actions unless clearly visible. "
        "Return JSON only with keys: description, subjects, setting, actions, visual_hook, quality_note. "
        "Keep the description factual and concrete. Mention readable signs only if clearly visible. Do not invent text."
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        ollama_url.rstrip("/") + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": str(exc), "description": "", "subjects": [], "setting": "", "actions": [], "visual_hook": "", "quality_note": ""}
    content = raw.get("message", {}).get("content", "")
    parsed = parse_vision_response(str(content))
    if vision_response_missing_image(parsed):
        return {
            "error": "vision_model_did_not_receive_image",
            "description": "",
            "subjects": [],
            "setting": "",
            "actions": [],
            "visual_hook": "",
            "quality_note": parsed.get("quality_note", ""),
        }
    return parsed


def summarize_vision_captions(captions: list[dict[str, Any]]) -> dict[str, Any]:
    descriptions = [caption.get("description", "") for caption in captions if caption.get("description")]
    subjects: list[str] = []
    normalized_subjects: list[str] = []
    actions: list[str] = []
    hooks: list[str] = []
    settings: list[str] = []
    for caption in captions:
        caption_subjects = [str(item) for item in caption.get("subjects", []) if item]
        subjects.extend(caption_subjects)
        caption_text = " ".join(
            [
                caption.get("description", ""),
                caption.get("setting", ""),
                caption.get("visual_hook", ""),
                " ".join(caption_subjects),
            ]
        )
        caption_focuses = set(canonical_focus_hits(caption_text))
        caption_focuses.update(normalize_focus_subject(subject) for subject in caption_subjects)
        normalized_subjects.extend(focus for focus in caption_focuses if focus)
        actions.extend(str(item) for item in caption.get("actions", []) if item)
        if caption.get("visual_hook"):
            hooks.append(str(caption["visual_hook"]))
        if caption.get("setting"):
            settings.append(str(caption["setting"]))
    subject_counts = Counter(normalized_subjects)
    stable_threshold = 2 if len(captions) >= 3 else 1
    stable_subjects = [subject for subject, count in subject_counts.most_common() if count >= stable_threshold]
    unstable_subjects = [subject for subject, count in subject_counts.most_common() if count < stable_threshold]
    return {
        "description": " ".join(descriptions[:3]),
        "subjects": sorted(set(subjects)),
        "normalized_subjects": stable_subjects or [subject for subject, _ in subject_counts.most_common()],
        "subject_counts": dict(subject_counts.most_common()),
        "stable_subjects": stable_subjects,
        "unstable_subjects": unstable_subjects,
        "actions": sorted(set(actions)),
        "settings": sorted(set(settings)),
        "visual_hooks": hooks[:3],
    }


def average_quality(samples: list[dict[str, float]]) -> dict[str, float]:
    if not samples:
        return {"brightness": 0.0, "contrast": 0.0, "sharpness": 0.0}
    keys = ("brightness", "contrast", "sharpness")
    return {key: round(sum(sample[key] for sample in samples) / len(samples), 3) for key in keys}


def quality_penalty_from_visuals(quality: dict[str, float]) -> float:
    penalty = 0.0
    brightness = quality.get("brightness", 0.0)
    contrast = quality.get("contrast", 0.0)
    sharpness = quality.get("sharpness", 0.0)
    if brightness < 0.18 or brightness > 0.88:
        penalty += 1.0
    if contrast < 0.08:
        penalty += 0.8
    if sharpness < 0.025:
        penalty += 0.8
    return round(penalty, 3)


def visual_event_score_from_summary(summary: dict[str, Any]) -> float:
    subject_counts = summary.get("subject_counts", {})
    repeated_subjects = 0
    if isinstance(subject_counts, dict):
        repeated_subjects = sum(1 for count in subject_counts.values() if isinstance(count, (int, float)) and count >= 2)
    action_count = len(listify(summary.get("actions")))
    hook_count = len(listify(summary.get("visual_hooks")))
    stable_count = len(listify(summary.get("stable_subjects")))
    raw_subject_count = len(listify(summary.get("subjects")))
    return min(10.0, stable_count * 2.5 + repeated_subjects * 2.0 + min(2, action_count) * 1.0 + min(2, hook_count) * 0.8 + min(1, raw_subject_count) * 0.7)


def analyze_candidate_visuals(
    source_video: Path,
    out_dir: Path,
    candidate: dict[str, Any],
    thumbnail_count: int,
    ocr_languages: str,
    vision_model: str,
    ollama_url: str,
) -> dict[str, Any]:
    timestamps = sample_timestamps(candidate["start"], candidate["end"], thumbnail_count)
    thumbnails = []
    quality_samples = []
    ocr_texts = []
    vision_captions = []
    for index, timestamp in enumerate(timestamps):
        thumb_rel = Path("thumbnails") / candidate["id"] / f"thumb_{index:02d}.jpg"
        thumb_path = out_dir / thumb_rel
        extract_thumbnail(source_video, timestamp, thumb_path)
        thumbnails.append({"time": timestamp, "path": thumb_rel.as_posix()})
        quality_samples.append(frame_quality_from_gray(extract_quality_frame(source_video, timestamp)))
        ocr_text = ocr_thumbnail(thumb_path, ocr_languages)
        if ocr_text:
            ocr_texts.append(ocr_text)
        if vision_model:
            caption = describe_thumbnail_with_ollama(thumb_path, vision_model, ollama_url)
            caption["time"] = timestamp
            caption["path"] = thumb_rel.as_posix()
            vision_captions.append(caption)

    ocr_text = " ".join(dict.fromkeys(ocr_texts))
    ocr_hits = text_hits(ocr_text, OCR_PLACE_WORDS) if ocr_text else []
    quality = average_quality(quality_samples)
    return {
        "id": candidate["id"],
        "thumbnails": thumbnails,
        "visual_quality": quality,
        "visual_quality_samples": quality_samples,
        "ocr": {
            "enabled": shutil.which("tesseract") is not None,
            "languages": ocr_languages,
            "text": ocr_text,
            "place_hits": ocr_hits,
        },
        "vision": {
            "enabled": bool(vision_model),
            "model": vision_model,
            "captions": vision_captions,
            "summary": summarize_vision_captions(vision_captions),
        },
        "visual_quality_penalty": quality_penalty_from_visuals(quality),
    }


def analyze_visuals(
    out_dir: Path,
    thumbnail_count: int = 3,
    ocr_languages: str = "chi_tra+eng",
    vision_model: str = "",
    ollama_url: str = "http://127.0.0.1:11434",
) -> list[dict[str, Any]]:
    require_tool("ffmpeg")
    source = read_json(out_dir / "source.json")
    candidates = read_json(out_dir / "candidates.json")
    source_video = Path(source["source_video"])
    visual_segments = [
        analyze_candidate_visuals(source_video, out_dir, candidate, thumbnail_count, ocr_languages, vision_model, ollama_url)
        for candidate in candidates
    ]
    write_json(out_dir / "visual_segments.json", visual_segments)
    return visual_segments


def load_visual_signals(out_dir: Path) -> dict[str, dict[str, Any]]:
    path = out_dir / "visual_segments.json"
    if not path.exists():
        return {}
    return {item["id"]: item for item in read_json(path)}


def attach_visual_signals(candidates: list[dict[str, Any]], visuals_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for candidate in candidates:
        visual = visuals_by_id.get(candidate["id"])
        if not visual:
            enriched.append(candidate)
            continue
        signals = {
            **candidate.get("signals", {}),
            "visual_quality": visual.get("visual_quality", {}),
            "visual_quality_penalty": visual.get("visual_quality_penalty", 0.0),
            "ocr": visual.get("ocr", {}),
            "vision": visual.get("vision", {}),
            "thumbnails": visual.get("thumbnails", []),
        }
        enriched.append({**candidate, "signals": signals})
    return enriched


def listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def vision_summary_text(summary: dict[str, Any]) -> str:
    parts = [
        summary.get("description", ""),
        summary.get("setting", ""),
        summary.get("visual_hook", ""),
        summary.get("quality_note", ""),
        " ".join(listify(summary.get("subjects"))),
        " ".join(listify(summary.get("normalized_subjects"))),
        " ".join(listify(summary.get("stable_subjects"))),
        " ".join(listify(summary.get("settings"))),
        " ".join(listify(summary.get("actions"))),
        " ".join(listify(summary.get("visual_hooks"))),
    ]
    return " ".join(str(part) for part in parts if str(part).strip())


def canonical_focus_hits(text: str) -> list[str]:
    hits = []
    lowered = text.lower()
    for canonical, aliases in FOCUS_ALIAS_GROUPS.items():
        if any(alias.lower() in lowered for alias in aliases):
            hits.append(canonical)
    return hits


def normalize_focus_subject(subject: str) -> str:
    cleaned = subject.lower().strip()
    cleaned = re.sub(r"[^a-z0-9\u4e00-\u9fff -]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or cleaned in FOCUS_GENERIC_TERMS:
        return ""
    hits = canonical_focus_hits(cleaned)
    if hits:
        return hits[0]
    if len(cleaned) < 3 and not re.search(r"[\u4e00-\u9fff]", cleaned):
        return ""
    return cleaned


def infer_project_focus(candidates: list[dict[str, Any]], max_terms: int = 6) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    sources: dict[str, set[str]] = {}
    candidate_support: dict[str, set[str]] = {}
    for candidate in candidates:
        signals = candidate.get("signals", {})
        summary = signals.get("vision", {}).get("summary", {})
        candidate_id = candidate.get("id", "")
        for subject in listify(summary.get("stable_subjects")) or listify(summary.get("normalized_subjects")):
            focus = normalize_focus_subject(subject)
            if focus:
                counts[focus] += 4
                sources.setdefault(focus, set()).add("vision_subject")
                candidate_support.setdefault(focus, set()).add(candidate_id)
        subject_counts = summary.get("subject_counts", {})
        if isinstance(subject_counts, dict):
            for subject, support in subject_counts.items():
                focus = normalize_focus_subject(str(subject))
                if focus:
                    counts[focus] += min(3.0, float(support))
                    sources.setdefault(focus, set()).add("vision_majority")
                    candidate_support.setdefault(focus, set()).add(candidate_id)
        for subject in listify(summary.get("subjects")):
            focus = normalize_focus_subject(subject)
            if focus:
                counts[focus] += 1
                sources.setdefault(focus, set()).add("vision_subject_raw")
                candidate_support.setdefault(focus, set()).add(candidate_id)
        visual_text = vision_summary_text(summary)
        for focus in canonical_focus_hits(visual_text):
            counts[focus] += 2
            sources.setdefault(focus, set()).add("vision_text")
            candidate_support.setdefault(focus, set()).add(candidate_id)
        ocr_text = signals.get("ocr", {}).get("text", "")
        for focus in canonical_focus_hits(ocr_text):
            counts[focus] += 1
            sources.setdefault(focus, set()).add("ocr")
            candidate_support.setdefault(focus, set()).add(candidate_id)
        transcript = candidate.get("transcript", "")
        for focus in canonical_focus_hits(transcript):
            counts[focus] += 1
            sources.setdefault(focus, set()).add("transcript")
            candidate_support.setdefault(focus, set()).add(candidate_id)

    focus_terms = []
    for term, count in counts.most_common(max_terms):
        if count <= 0:
            continue
        support_count = len(candidate_support.get(term, set()))
        if support_count <= 1 and term not in FOCUS_ALIAS_GROUPS:
            continue
        if support_count <= 1 and count < 5:
            continue
        aliases = FOCUS_ALIAS_GROUPS.get(term, [term])
        focus_terms.append(
            {
                "term": term,
                "display": FOCUS_DISPLAY_NAMES.get(term, term),
                "weight": round(min(10.0, float(count) * (1.0 if support_count > 1 else 0.45)), 3),
                "aliases": aliases,
                "sources": sorted(sources.get(term, set())),
                "candidate_support": support_count,
            }
        )
    return {
        "version": "project_focus_v1",
        "focus_terms": focus_terms,
        "summary": "、".join(item["display"] for item in focus_terms[:3]),
    }


def candidate_focus_text(candidate: dict[str, Any]) -> str:
    signals = candidate.get("signals", {})
    summary = signals.get("vision", {}).get("summary", {})
    return " ".join(
        [
            candidate.get("transcript", ""),
            vision_summary_text(summary),
            signals.get("ocr", {}).get("text", ""),
        ]
    )


def candidate_subject_support(candidate: dict[str, Any], term: str) -> int:
    summary = candidate.get("signals", {}).get("vision", {}).get("summary", {})
    subject_counts = summary.get("subject_counts", {})
    if isinstance(subject_counts, dict):
        direct = subject_counts.get(term)
        if direct is not None:
            try:
                return int(direct)
            except (TypeError, ValueError):
                return 0
    stable_subjects = listify(summary.get("stable_subjects"))
    normalized_subjects = listify(summary.get("normalized_subjects"))
    if term in stable_subjects:
        return 2
    if term in normalized_subjects:
        return 1
    return 0


def attach_focus_signals(candidates: list[dict[str, Any]], project_focus: dict[str, Any]) -> list[dict[str, Any]]:
    enriched = []
    focus_terms = project_focus.get("focus_terms", [])
    for candidate in candidates:
        text = candidate_focus_text(candidate).lower()
        matched = []
        score = 0.0
        for item in focus_terms:
            aliases = item.get("aliases") or [item.get("term", "")]
            if any(str(alias).lower() in text for alias in aliases if str(alias).strip()):
                support = candidate_subject_support(candidate, str(item.get("term", "")))
                project_support = int(item.get("candidate_support", 1) or 1)
                support_multiplier = 1.0
                if support == 1 and project_support <= 1:
                    support_multiplier = 0.35
                elif support == 1:
                    support_multiplier = 0.65
                matched.append(
                    {
                        "term": item.get("term", ""),
                        "display": item.get("display", item.get("term", "")),
                        "weight": item.get("weight", 0.0),
                        "support": support,
                    }
                )
                score += float(item.get("weight", 0.0)) * 0.7 * support_multiplier
        signals = {
            **candidate.get("signals", {}),
            "focus": {
                "matched_terms": matched,
                "score": round(min(10.0, score), 3),
                "project_summary": project_focus.get("summary", ""),
            },
        }
        enriched.append({**candidate, "signals": signals})
    return enriched


def heuristic_scores(candidate: dict[str, Any]) -> dict[str, float]:
    signals = candidate.get("signals", {})
    keyword_score = min(10.0, len(signals.get("keywords", [])) * 2.0)
    speech_density_score = min(10.0, float(signals.get("speech_density", 0.0)) * 10.0)
    interaction_score = min(10.0, signals.get("utterance_count", 0) / max(1.0, candidate["duration_sec"]) * 20.0)
    ocr_place_hits = signals.get("ocr", {}).get("place_hits", [])
    vision_summary = signals.get("vision", {}).get("summary", {})
    vision_text = " ".join(
        [
            vision_summary.get("description", ""),
            " ".join(vision_summary.get("settings", [])),
            " ".join(vision_summary.get("subjects", [])),
            " ".join(vision_summary.get("visual_hooks", [])),
        ]
    )
    vision_place_hits = text_hits(vision_text, VISION_PLACE_WORDS)
    vision_interest_hits = text_hits(vision_text, VISION_INTEREST_WORDS)
    place_score = min(10.0, len(signals.get("place_words", [])) * 2.5 + len(ocr_place_hits) * 2.0 + len(vision_place_hits) * 1.5)
    emotion_score = min(10.0, len(signals.get("emotion_words", [])) * 2.5 + signals.get("question_exclamation_count", 0))
    visual_interest_score = min(10.0, len(vision_interest_hits) * 1.5)
    visual_event_score = visual_event_score_from_summary(vision_summary)
    focus_score = min(10.0, float(signals.get("focus", {}).get("score", 0.0)))
    quality_penalty = (1.0 if candidate["duration_sec"] < 12 else 0.0) + float(signals.get("visual_quality_penalty", 0.0))
    total = (
        keyword_score * 0.15
        + speech_density_score * 0.15
        + interaction_score * 0.2
        + place_score * 0.15
        + max(emotion_score, visual_interest_score, visual_event_score) * 0.15
        + focus_score * 0.2
        - quality_penalty
    )
    return {
        "keyword_score": round(keyword_score, 3),
        "speech_density_score": round(speech_density_score, 3),
        "interaction_score": round(interaction_score, 3),
        "place_score": round(place_score, 3),
        "emotion_score": round(emotion_score, 3),
        "visual_interest_score": round(visual_interest_score, 3),
        "visual_event_score": round(visual_event_score, 3),
        "focus_score": round(focus_score, 3),
        "quality_penalty": round(quality_penalty, 3),
        "total_heuristic_score": round(max(0.0, total), 3),
    }


def score_with_heuristic(candidate: dict[str, Any]) -> dict[str, Any]:
    scores = heuristic_scores(candidate)
    total = scores["total_heuristic_score"]
    return {
        **candidate,
        "summary": summarize_transcript(candidate["transcript"]),
        "title": summarize_transcript(candidate["transcript"], max_chars=18),
        "tags": infer_tags(candidate),
        "scores": {
            "hook": round(max(total, scores["emotion_score"]), 3),
            "fun": scores["emotion_score"],
            "interaction": scores["interaction_score"],
            "place": scores["place_score"],
            "emotion": scores["emotion_score"],
            "clarity": scores["speech_density_score"],
            "focus": scores["focus_score"],
        },
        "heuristic_scores": scores,
        "is_standalone": candidate["duration_sec"] >= 12 and bool(candidate["transcript"]),
        "avoid_reason": "none",
        "scoring_source": "heuristic",
        "final_score": round(final_score_from_scores(scores, None), 3),
    }


def summarize_transcript(text: str, max_chars: int = 42) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"


def infer_tags(candidate: dict[str, Any]) -> list[str]:
    signals = candidate.get("signals", {})
    tags = []
    if signals.get("emotion_words"):
        tags.append("反應")
    if signals.get("place_words"):
        tags.append("地點")
    if signals.get("ocr", {}).get("place_hits"):
        tags.append("文字地點")
    vision_summary = signals.get("vision", {}).get("summary", {})
    vision_text = " ".join(
        [
            vision_summary.get("description", ""),
            " ".join(vision_summary.get("subjects", [])),
            " ".join(vision_summary.get("settings", [])),
        ]
    )
    if text_hits(vision_text, VISION_PLACE_WORDS):
        tags.append("視覺地點")
    if text_hits(vision_text, VISION_INTEREST_WORDS):
        tags.append("視覺亮點")
    if signals.get("focus", {}).get("score", 0) > 0:
        tags.append("主體重點")
    if signals.get("question_exclamation_count", 0) > 0:
        tags.append("情緒")
    if not tags:
        tags.append("對話")
    return tags


def final_score_from_scores(heuristic: dict[str, float], llm_scores: Optional[dict[str, Any]]) -> float:
    if not llm_scores:
        return heuristic["total_heuristic_score"]
    quality_penalty = heuristic.get("quality_penalty", 0.0)
    return (
        float(llm_scores.get("hook", 0)) * 0.25
        + float(llm_scores.get("fun", 0)) * 0.15
        + float(llm_scores.get("interaction", 0)) * 0.20
        + float(llm_scores.get("place", 0)) * 0.15
        + float(llm_scores.get("emotion", 0)) * 0.15
        + float(llm_scores.get("clarity", 0)) * 0.10
        - quality_penalty
    )


def score_with_ollama(candidate: dict[str, Any], model: str) -> dict[str, Any]:
    prompt = {
        "task": "Score this highlight candidate. Return JSON only with id, summary, title, tags, scores, is_standalone, avoid_reason.",
        "rubric": {
            "scores": "0 to 10 for hook, fun, interaction, place, emotion, clarity",
            "avoid_reason": "Use 'none' if usable.",
        },
        "candidate": candidate,
    }
    output = run_capture(["ollama", "run", model, json.dumps(prompt, ensure_ascii=False)])
    parsed = parse_first_json(output)
    heuristic = heuristic_scores(candidate)
    llm_scores = parsed.get("scores", {}) if isinstance(parsed, dict) else {}
    return {
        **score_with_heuristic(candidate),
        "summary": parsed.get("summary") or summarize_transcript(candidate["transcript"]),
        "title": parsed.get("title") or summarize_transcript(candidate["transcript"], max_chars=18),
        "tags": parsed.get("tags") or infer_tags(candidate),
        "scores": llm_scores,
        "is_standalone": bool(parsed.get("is_standalone", True)),
        "avoid_reason": parsed.get("avoid_reason", "none"),
        "scoring_source": "ollama",
        "final_score": round(final_score_from_scores(heuristic, llm_scores), 3),
    }


def parse_first_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data


def score_candidates(candidates: list[dict[str, Any]], planner: str, model: str) -> list[dict[str, Any]]:
    if planner == "ollama" and shutil.which("ollama") is None:
        log("Ollama not found; falling back to heuristic scoring.")
        planner = "heuristic"
    scored = []
    for candidate in candidates:
        if planner == "ollama":
            try:
                scored.append(score_with_ollama(candidate, model))
                continue
            except Exception as exc:  # noqa: BLE001 - fallback should keep local pipeline usable.
                log(f"Ollama scoring failed for {candidate['id']}; using heuristic. Reason: {exc}")
        scored.append(score_with_heuristic(candidate))
    return sorted(scored, key=lambda item: item["final_score"], reverse=True)


def overlap_ratio(left: dict[str, Any], right: dict[str, Any]) -> float:
    overlap = max(0.0, min(left["end"], right["end"]) - max(left["start"], right["start"]))
    return overlap / max(1.0, min(left["duration_sec"], right["duration_sec"]))


SCENE_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "with",
    "in",
    "on",
    "at",
    "to",
    "is",
    "are",
    "appears",
    "image",
    "shows",
    "scene",
    "view",
    "water",
    "glass",
    "clear",
    "blue",
    "greenish",
}


def scene_tokens(candidate: dict[str, Any]) -> set[str]:
    summary = candidate.get("signals", {}).get("vision", {}).get("summary", {})
    text = " ".join(
        [
            " ".join(listify(summary.get("stable_subjects"))),
            " ".join(listify(summary.get("normalized_subjects"))),
            " ".join(listify(summary.get("settings"))),
            summary.get("description", ""),
        ]
    ).lower()
    tokens = set(canonical_focus_hits(text))
    for token in re.findall(r"[a-z0-9\u4e00-\u9fff]+", text):
        if len(token) < 3 and not re.search(r"[\u4e00-\u9fff]", token):
            continue
        if token in SCENE_STOPWORDS:
            continue
        normalized = normalize_focus_subject(token) or token
        if normalized not in FOCUS_GENERIC_TERMS:
            tokens.add(normalized)
    return tokens


def scene_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = scene_tokens(left)
    right_tokens = scene_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def too_visually_similar(candidate: dict[str, Any], existing: dict[str, Any]) -> bool:
    similarity = scene_similarity(candidate, existing)
    if similarity < 0.58:
        return False
    center_gap = abs(((candidate["start"] + candidate["end"]) / 2) - ((existing["start"] + existing["end"]) / 2))
    return center_gap < 90 or similarity >= 0.82


def select_segments(scored: list[dict[str, Any]], target_duration: float) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    total = 0.0
    budget = target_duration * 1.1
    subclip_duration = sum(item["duration_sec"] for item in scored if item.get("signals", {}).get("candidate_type") == "subclip")
    prefer_subclips = subclip_duration >= target_duration * 0.8
    pool = [
        item
        for item in scored
        if not prefer_subclips or item.get("signals", {}).get("candidate_type") == "subclip" or item["duration_sec"] <= 32
    ]
    for candidate in sorted(pool, key=lambda item: item["final_score"], reverse=True):
        if not candidate.get("is_standalone", True):
            continue
        if candidate.get("avoid_reason") not in (None, "", "none"):
            continue
        if any(overlap_ratio(candidate, existing) > 0.2 for existing in selected):
            continue
        if any(abs(candidate["start"] - existing["start"]) < 4 for existing in selected):
            continue
        if any(too_visually_similar(candidate, existing) for existing in selected):
            continue
        if selected and total + candidate["duration_sec"] > budget:
            continue
        selected.append(candidate)
        total += candidate["duration_sec"]
        if total >= target_duration:
            break
    return sorted(selected, key=lambda item: item["start"])


def padded_segment_bounds(selected: list[dict[str, Any]], source_duration: float, padding: float) -> list[tuple[float, float]]:
    bounds = [
        (
            max(0.0, float(item["start"]) - padding),
            min(source_duration, float(item["end"]) + padding),
        )
        for item in selected
    ]
    for index in range(len(bounds) - 1):
        left_start, left_end = bounds[index]
        right_start, right_end = bounds[index + 1]
        if left_end <= right_start:
            continue
        original_gap_midpoint = (float(selected[index]["end"]) + float(selected[index + 1]["start"])) / 2
        boundary = max(left_start, min(right_end, original_gap_midpoint))
        bounds[index] = (left_start, min(left_end, boundary))
        bounds[index + 1] = (max(right_start, boundary), right_end)
    return [(round(start, 3), round(end, 3)) for start, end in bounds]


def build_edit_plan(out_dir: Path, target_duration: float, clip_padding: float = DEFAULT_CLIP_PADDING) -> dict[str, Any]:
    source = read_json(out_dir / "source.json")
    scored = read_json(out_dir / "scored_segments.json")
    selected = select_segments(scored, target_duration)
    padded_bounds = padded_segment_bounds(selected, float(source.get("duration_sec", 0.0)), max(0.0, clip_padding))
    segments = []
    for index, item in enumerate(selected):
        role = "hook" if index == 0 else ("ending" if index == len(selected) - 1 else "highlight")
        source_start, source_end = padded_bounds[index]
        segments.append(
            {
                "segment_id": item["id"],
                "role": role,
                "source_start": source_start,
                "source_end": source_end,
                "duration_sec": round(source_end - source_start, 3),
                "original_source_start": item["start"],
                "original_source_end": item["end"],
                "clip_padding_sec": clip_padding,
                "title": item.get("title", item["id"]),
                "reason": item.get("summary", ""),
                "final_score": item.get("final_score"),
            }
        )
    return {
        "version": "edit_plan_v1",
        "source_video": source["source_video"],
        "output_video": str((out_dir / "output" / "highlight.mp4").resolve()),
        "target_duration_sec": target_duration,
        "selected_duration_sec": round(sum(item["duration_sec"] for item in segments), 3),
        "selected_segments": segments,
    }


def write_project_summary(out_dir: Path, target_duration: float) -> None:
    scored = read_json(out_dir / "scored_segments.json")
    focus_path = out_dir / "project_focus.json"
    project_focus = read_json(focus_path) if focus_path.exists() else {}
    summary = {
        "target_duration_sec": target_duration,
        "style": "travel_funny_highlight",
        "project_focus": project_focus,
        "segments": [
            {
                "id": item["id"],
                "time": f"{format_time(item['start'])}-{format_time(item['end'])}",
                "duration": round(item["duration_sec"], 1),
                "summary": item.get("summary", ""),
                "tags": item.get("tags", []),
                "scores": item.get("scores", {}),
                "quality": "good" if item.get("final_score", 0) >= 5 else "okay",
                "visual_quality": item.get("signals", {}).get("visual_quality", {}),
                "ocr_excerpt": summarize_transcript(item.get("signals", {}).get("ocr", {}).get("text", ""), max_chars=90),
                "visual_description": summarize_transcript(
                    item.get("signals", {}).get("vision", {}).get("summary", {}).get("description", ""),
                    max_chars=120,
                ),
                "focus": item.get("signals", {}).get("focus", {}),
                "transcript_excerpt": summarize_transcript(item.get("transcript", ""), max_chars=90),
            }
            for item in scored
        ],
    }
    write_json(out_dir / "project.summary.json", summary)
    task = (
        "# Codex Edit Plan Task\n\n"
        "Read:\n\n- `project.summary.json`\n\n"
        "Create:\n\n- `edit_plan.json`\n\n"
        "Rules:\n\n"
        "- Output valid JSON only.\n"
        "- Total selected duration should be target duration +/- 10%.\n"
        "- First segment must be a strong hook.\n"
        "- Avoid repeated scenes, repeated topics, unclear context, poor audio, or poor visuals.\n"
        "- Prefer varied roles: hook, context, place_highlight, interaction, payoff, ending.\n"
        "- Do not modify source video files.\n"
        "- Do not re-transcribe or analyze the whole video unless explicitly asked.\n"
    )
    (out_dir / "codex_task.md").write_text(task, encoding="utf-8")


def render_edit_plan(out_dir: Path, settings: RenderSettings) -> None:
    require_tool("ffmpeg")
    plan = read_json(out_dir / "edit_plan.json")
    source_video = Path(plan["source_video"])
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    concat_path = out_dir / "ffmpeg_concat.txt"
    clip_paths = []
    for index, segment in enumerate(plan.get("selected_segments", [])):
        clip_path = clips_dir / f"clip_{index:03d}.mp4"
        clip_paths.append(clip_path)
        run_command(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(segment["source_start"]),
                "-to",
                str(segment["source_end"]),
                "-i",
                str(source_video),
                *render_encoding_args(settings),
                str(clip_path),
            ]
        )
    if not clip_paths:
        raise SystemExit("edit_plan.json has no selected_segments to render.")
    concat_lines = [f"file '{clip.resolve().as_posix()}'" for clip in clip_paths]
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    output_video = Path(plan["output_video"])
    output_video.parent.mkdir(parents=True, exist_ok=True)
    run_command(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(output_video)])


def command_prepare(args: argparse.Namespace) -> None:
    source_video = Path(args.input).expanduser()
    if not source_video.exists():
        raise SystemExit(f"Input video not found: {source_video}")
    out_dir = Path(args.out)
    init_work_dir(out_dir, source_video)
    audio_path = extract_audio(source_video, out_dir)
    transcript_path = transcribe_audio(audio_path, out_dir, args.whisper_model)
    transcript = read_json(transcript_path)
    source = read_json(out_dir / "source.json")
    candidates = generate_candidates_from_transcript(transcript, source["duration_sec"])
    write_json(out_dir / "candidates.json", candidates)
    log(f"Wrote {len(candidates)} candidates to {out_dir / 'candidates.json'}")


def command_score(args: argparse.Namespace) -> None:
    out_dir = Path(args.work_dir)
    candidates = read_json(out_dir / "candidates.json")
    candidates = attach_visual_signals(candidates, load_visual_signals(out_dir))
    project_focus = infer_project_focus(candidates)
    write_json(out_dir / "project_focus.json", project_focus)
    candidates = attach_focus_signals(candidates, project_focus)
    scored = score_candidates(candidates, args.planner, args.model)
    write_json(out_dir / "scored_segments.json", scored)
    write_project_summary(out_dir, args.target_duration)
    log(f"Wrote {len(scored)} scored segments to {out_dir / 'scored_segments.json'}")


def command_analyze_visuals(args: argparse.Namespace) -> None:
    visual_segments = analyze_visuals(
        Path(args.work_dir),
        args.thumbnail_count,
        args.ocr_languages,
        args.vision_model,
        args.ollama_url,
    )
    log(f"Wrote visual metadata for {len(visual_segments)} candidates to {Path(args.work_dir) / 'visual_segments.json'}")


def command_plan(args: argparse.Namespace) -> None:
    out_dir = Path(args.work_dir)
    plan = build_edit_plan(out_dir, args.target_duration, args.clip_padding)
    write_json(out_dir / "edit_plan.json", plan)
    write_project_summary(out_dir, args.target_duration)
    log(f"Wrote edit plan with {len(plan['selected_segments'])} segments to {out_dir / 'edit_plan.json'}")


def command_render(args: argparse.Namespace) -> None:
    settings = RenderSettings(
        output_size=args.output_size,
        crf=args.crf,
        preset=args.preset,
        audio_bitrate=args.audio_bitrate,
        video_bitrate=args.video_bitrate,
    )
    render_edit_plan(Path(args.work_dir), settings)


def command_run(args: argparse.Namespace) -> None:
    prepare_args = argparse.Namespace(input=args.input, out=args.out, whisper_model=args.whisper_model)
    command_prepare(prepare_args)
    if args.visuals:
        command_analyze_visuals(
            argparse.Namespace(
                work_dir=args.out,
                thumbnail_count=args.thumbnail_count,
                ocr_languages=args.ocr_languages,
                vision_model=args.vision_model,
                ollama_url=args.ollama_url,
            )
        )
    score_args = argparse.Namespace(work_dir=args.out, planner=args.planner, model=args.model, target_duration=args.target_duration)
    command_score(score_args)
    plan_args = argparse.Namespace(work_dir=args.out, target_duration=args.target_duration, clip_padding=args.clip_padding)
    command_plan(plan_args)
    command_render(
        argparse.Namespace(
            work_dir=args.out,
            output_size=args.output_size,
            crf=args.crf,
            preset=args.preset,
            audio_bitrate=args.audio_bitrate,
            video_bitrate=args.video_bitrate,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-first automatic highlight editor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Extract audio, transcribe, and generate candidates")
    prepare.add_argument("input", help="Input video path")
    prepare.add_argument("--out", required=True, help="Work directory")
    prepare.add_argument("--whisper-model", default="small", help="faster-whisper model name or path")
    prepare.set_defaults(func=command_prepare)

    score = subparsers.add_parser("score", help="Score candidate segments")
    score.add_argument("work_dir", help="Work directory")
    score.add_argument("--planner", choices=["heuristic", "ollama"], default="heuristic")
    score.add_argument("--model", default="qwen3:6b", help="Ollama model")
    score.add_argument("--target-duration", type=float, default=180)
    score.set_defaults(func=command_score)

    analyze_visuals_parser = subparsers.add_parser("analyze-visuals", help="Extract thumbnails and visual/OCR metadata for candidates")
    analyze_visuals_parser.add_argument("work_dir", help="Work directory")
    analyze_visuals_parser.add_argument("--thumbnail-count", type=int, default=3)
    analyze_visuals_parser.add_argument("--ocr-languages", default="chi_tra+eng")
    analyze_visuals_parser.add_argument("--vision-model", default="", help="Optional Ollama vision model for thumbnail descriptions")
    analyze_visuals_parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    analyze_visuals_parser.set_defaults(func=command_analyze_visuals)

    plan = subparsers.add_parser("plan", help="Create edit_plan.json from scored segments")
    plan.add_argument("work_dir", help="Work directory")
    plan.add_argument("--target-duration", type=float, default=180)
    plan.add_argument("--clip-padding", type=float, default=DEFAULT_CLIP_PADDING, help="Seconds to add before and after each selected segment")
    plan.set_defaults(func=command_plan)

    render = subparsers.add_parser("render", help="Render highlight.mp4 from edit_plan.json")
    render.add_argument("work_dir", help="Work directory")
    render.add_argument("--output-size", type=output_size_arg, default=DEFAULT_OUTPUT_SIZE, help="Maximum render size as WIDTHxHEIGHT")
    render.add_argument("--crf", type=crf_arg, default=DEFAULT_RENDER_CRF, help="x264 CRF, lower is higher quality/larger files")
    render.add_argument("--preset", default=DEFAULT_RENDER_PRESET, help="x264 preset such as medium, slow, or veryfast")
    render.add_argument("--audio-bitrate", default=DEFAULT_AUDIO_BITRATE, help="AAC audio bitrate")
    render.add_argument("--video-bitrate", default="", help="Optional video bitrate such as 3500k; overrides CRF when set")
    render.set_defaults(func=command_render)

    run = subparsers.add_parser("run", help="Run the full pipeline")
    run.add_argument("input", help="Input video path")
    run.add_argument("--out", required=True, help="Work directory")
    run.add_argument("--target-duration", type=float, default=180)
    run.add_argument("--planner", choices=["heuristic", "ollama"], default="heuristic")
    run.add_argument("--model", default="qwen3:6b", help="Ollama model")
    run.add_argument("--whisper-model", default="small", help="faster-whisper model name or path")
    run.add_argument("--visuals", action="store_true", help="Analyze thumbnails and optional OCR before scoring")
    run.add_argument("--thumbnail-count", type=int, default=3)
    run.add_argument("--ocr-languages", default="chi_tra+eng")
    run.add_argument("--vision-model", default="", help="Optional Ollama vision model for thumbnail descriptions")
    run.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    run.add_argument("--output-size", type=output_size_arg, default=DEFAULT_OUTPUT_SIZE, help="Maximum render size as WIDTHxHEIGHT")
    run.add_argument("--crf", type=crf_arg, default=DEFAULT_RENDER_CRF, help="x264 CRF, lower is higher quality/larger files")
    run.add_argument("--preset", default=DEFAULT_RENDER_PRESET, help="x264 preset such as medium, slow, or veryfast")
    run.add_argument("--audio-bitrate", default=DEFAULT_AUDIO_BITRATE, help="AAC audio bitrate")
    run.add_argument("--video-bitrate", default="", help="Optional video bitrate such as 3500k; overrides CRF when set")
    run.add_argument("--clip-padding", type=float, default=DEFAULT_CLIP_PADDING, help="Seconds to add before and after each selected segment")
    run.set_defaults(func=command_run)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
