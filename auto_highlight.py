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
DEFAULT_FADE_DURATION = 0.25
DEFAULT_CLIP_PADDING = 2.5
DEFAULT_TEXT_MODEL = "qwen3:1.7b"
DEFAULT_TARGET_RETENTION_RATIO = 0.30
MAX_SELECTED_SEGMENTS = 10
TARGET_SEGMENT_SECONDS = 24.0
HIGHLIGHT_SCORE_RATIO = 0.72
MIN_PRE_TARGET_SCORE_RATIO = 0.5
MIN_HIGHLIGHT_SCORE = 4.5
HARD_DURATION_EXTRA_SEC = 30.0
HARD_DURATION_MULTIPLIER = 1.5
CONTACT_SHEET_LABELS = {
    "selected": "Selected",
    "near_miss": "Near Misses",
}
GENERATED_ARTIFACT_FILES = [
    "audio.wav",
    "analysis_video.mp4",
    "transcript.json",
    "candidates.json",
    "visual_segments.json",
    "scored_segments.json",
    "project_focus.json",
    "project.summary.json",
    "edit_plan.json",
    "plan_confidence.json",
    "gpt_review_packet.json",
    "codex_review_result.json",
    "codex_review_apply_result.json",
    "edit_plan.before_codex_review.json",
    "edit_plan.gpt_reviewed.json",
    "review_report.json",
    "review_report.md",
    "ffmpeg_concat.txt",
]
GENERATED_ARTIFACT_DIRS = ["clips", "thumbnails", "output"]
CONTACT_SHEET_FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
}


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
    fade_duration: float = DEFAULT_FADE_DURATION


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


def source_fingerprint(source_video: Path) -> dict[str, Any]:
    stat = source_video.stat()
    return {
        "path": str(source_video.resolve()),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def source_matches(existing: dict[str, Any], current: dict[str, Any]) -> bool:
    existing_path = existing.get("source_video") or existing.get("fingerprint", {}).get("path")
    if existing_path and Path(str(existing_path)).expanduser().resolve() != Path(str(current["source_video"])).resolve():
        return False
    existing_fingerprint = existing.get("fingerprint")
    if isinstance(existing_fingerprint, dict):
        return (
            existing_fingerprint.get("size_bytes") == current["fingerprint"]["size_bytes"]
            and existing_fingerprint.get("mtime_ns") == current["fingerprint"]["mtime_ns"]
        )
    return True


def ensure_work_subdirs(out_dir: Path) -> None:
    for name in GENERATED_ARTIFACT_DIRS:
        (out_dir / name).mkdir(parents=True, exist_ok=True)


def invalidate_generated_artifacts(out_dir: Path) -> None:
    for name in GENERATED_ARTIFACT_FILES:
        path = out_dir / name
        if path.exists():
            path.unlink()
    for path in out_dir.glob("review_contact_sheet*"):
        if path.is_file():
            path.unlink()
    for name in GENERATED_ARTIFACT_DIRS:
        path = out_dir / name
        if path.exists():
            shutil.rmtree(path)


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


def non_negative_float_arg(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a non-negative number") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative number")
    return number


def render_scale_filter(output_size: str) -> str:
    width, height = parse_output_size(output_size)
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1"


def effective_fade_duration(settings: RenderSettings, clip_duration: float) -> float:
    return round(max(0.0, min(settings.fade_duration, clip_duration / 2)), 3)


def render_video_filter(settings: RenderSettings, clip_duration: float = 0.0) -> str:
    filters = [render_scale_filter(settings.output_size)]
    fade_duration = effective_fade_duration(settings, clip_duration)
    if fade_duration > 0:
        fade_out_start = round(max(0.0, clip_duration - fade_duration), 3)
        filters.extend(
            [
                f"fade=t=in:st=0:d={fade_duration}",
                f"fade=t=out:st={fade_out_start}:d={fade_duration}",
            ]
        )
    return ",".join(filters)


def render_audio_filter(settings: RenderSettings, clip_duration: float) -> list[str]:
    fade_duration = effective_fade_duration(settings, clip_duration)
    if fade_duration <= 0:
        return []
    fade_out_start = round(max(0.0, clip_duration - fade_duration), 3)
    return ["-af", f"afade=t=in:st=0:d={fade_duration},afade=t=out:st={fade_out_start}:d={fade_duration}"]


def render_encoding_args(settings: RenderSettings, clip_duration: float = 0.0) -> list[str]:
    args = [
        "-vf",
        render_video_filter(settings, clip_duration),
        *render_audio_filter(settings, clip_duration),
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


def init_work_dir(out_dir: Path, source_video: Path, force: bool = False) -> None:
    if out_dir.exists() and any(out_dir.iterdir()):
        log(f"Using existing work directory: {out_dir}")
        source_path = out_dir / "source.json"
        source = {
            "source_video": str(source_video.resolve()),
            "duration_sec": video_duration(source_video),
            "fingerprint": source_fingerprint(source_video),
        }
        if source_path.exists():
            existing_source = read_json(source_path)
            if not source_matches(existing_source, source) and not force:
                raise SystemExit(
                    f"Work directory {out_dir} was prepared for a different or changed source video. "
                    "Use a new --out directory or rerun prepare/run with --force to regenerate source-dependent artifacts."
                )
        elif not force:
            raise SystemExit(
                f"Work directory {out_dir} is not empty and has no source.json. "
                "Use a new --out directory or rerun with --force if you want to use it anyway."
            )
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        source = {
            "source_video": str(source_video.resolve()),
            "duration_sec": video_duration(source_video),
            "fingerprint": source_fingerprint(source_video),
        }
    ensure_work_subdirs(out_dir)
    write_json(out_dir / "source.json", source)


def extract_audio(source_video: Path, out_dir: Path, force: bool = False) -> Path:
    require_tool("ffmpeg")
    audio_path = out_dir / "audio.wav"
    if audio_path.exists():
        if force:
            audio_path.unlink()
        else:
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


def transcribe_audio(audio_path: Path, out_dir: Path, model: str, force: bool = False) -> Path:
    transcript_path = out_dir / "transcript.json"
    if transcript_path.exists():
        if force:
            transcript_path.unlink()
        else:
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


def ensure_analysis_video(source_video: Path, out_dir: Path, output_size: str = DEFAULT_OUTPUT_SIZE) -> Path:
    analysis_video = out_dir / "analysis_video.mp4"
    if analysis_video.exists():
        return analysis_video
    require_tool("ffmpeg")
    log(f"Creating analysis proxy: {analysis_video}")
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            f"scale={output_size}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            "-movflags",
            "+faststart",
            str(analysis_video),
        ]
    )
    return analysis_video


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
    output_size: str = DEFAULT_OUTPUT_SIZE,
) -> list[dict[str, Any]]:
    require_tool("ffmpeg")
    source = read_json(out_dir / "source.json")
    candidates = read_json(out_dir / "candidates.json")
    source_video = Path(source["source_video"])
    analysis_video = ensure_analysis_video(source_video, out_dir, output_size)
    visual_segments = [
        analyze_candidate_visuals(analysis_video, out_dir, candidate, thumbnail_count, ocr_languages, vision_model, ollama_url)
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


def visual_quality_score(quality: dict[str, Any]) -> float:
    brightness = float(quality.get("brightness", 0.0) or 0.0)
    contrast = float(quality.get("contrast", 0.0) or 0.0)
    sharpness = float(quality.get("sharpness", 0.0) or 0.0)
    brightness_score = max(0.0, 1.0 - abs(brightness - 0.52) / 0.52)
    return round(brightness_score * 1.2 + min(1.0, contrast * 5.0) * 1.0 + min(1.0, sharpness * 12.0) * 1.0, 3)


def visual_caption_score(caption: dict[str, Any], aggregate_summary: dict[str, Any]) -> float:
    summary = summarize_vision_captions([caption]) if caption else {}
    caption_text = vision_summary_text(summary)
    aggregate_subjects = set(listify(aggregate_summary.get("stable_subjects")) or listify(aggregate_summary.get("normalized_subjects")))
    caption_subjects = set(listify(summary.get("normalized_subjects")) + listify(summary.get("stable_subjects")))
    stable_subject_score = 2.0 if aggregate_subjects and aggregate_subjects & caption_subjects else 0.0
    interest_score = len(text_hits(caption_text, VISION_INTEREST_WORDS)) * 0.8
    place_score = len(text_hits(caption_text, VISION_PLACE_WORDS)) * 0.5
    return round(visual_event_score_from_summary(summary) + stable_subject_score + interest_score + place_score, 3)


def visual_caption_event_score(caption: dict[str, Any]) -> float:
    summary = summarize_vision_captions([caption]) if caption else {}
    caption_text = vision_summary_text(summary)
    subject_terms = listify(caption.get("subjects"))
    concrete_subjects = set()
    for term in subject_terms:
        normalized = normalize_focus_subject(term) or term.lower().strip()
        if normalized and normalized not in FOCUS_GENERIC_TERMS:
            concrete_subjects.add(normalized)
    action_count = len(listify(summary.get("actions")))
    hook_count = len(listify(summary.get("visual_hooks")))
    interest_count = len(text_hits(caption_text, VISION_INTEREST_WORDS))
    return round(min(10.0, len(concrete_subjects) * 2.0 + min(2, action_count) * 1.0 + min(2, hook_count) * 1.0 + interest_count * 0.8), 3)


def visual_sample_points(visual: dict[str, Any]) -> list[dict[str, Any]]:
    thumbnails = visual.get("thumbnails", [])
    quality_samples = visual.get("visual_quality_samples", [])
    captions = visual.get("vision", {}).get("captions", [])
    aggregate_summary = visual.get("vision", {}).get("summary", {})
    points = []
    for index, thumbnail in enumerate(thumbnails):
        if not isinstance(thumbnail, dict) or "time" not in thumbnail:
            continue
        caption = captions[index] if index < len(captions) and isinstance(captions[index], dict) else {}
        quality = quality_samples[index] if index < len(quality_samples) and isinstance(quality_samples[index], dict) else {}
        caption_score = visual_caption_score(caption, aggregate_summary)
        event_score = visual_caption_event_score(caption)
        quality_score = visual_quality_score(quality)
        points.append(
            {
                "time": float(thumbnail["time"]),
                "path": thumbnail.get("path", ""),
                "score": round(caption_score + quality_score, 3),
                "caption_score": caption_score,
                "event_score": event_score,
                "quality_score": quality_score,
                "caption": caption,
                "quality": quality,
            }
        )
    return points


def visual_signal_subset(visual: dict[str, Any], start: float, end: float, anchor_time: float) -> dict[str, Any]:
    thumbnails = [
        item
        for item in visual.get("thumbnails", [])
        if isinstance(item, dict) and start <= float(item.get("time", -1.0)) <= end
    ]
    captions = [
        item
        for item in visual.get("vision", {}).get("captions", [])
        if isinstance(item, dict) and start <= float(item.get("time", -1.0)) <= end
    ]
    if not thumbnails:
        thumbnails = sorted(
            [item for item in visual.get("thumbnails", []) if isinstance(item, dict) and "time" in item],
            key=lambda item: abs(float(item.get("time", 0.0)) - anchor_time),
        )[:1]
    if not captions:
        captions = sorted(
            [item for item in visual.get("vision", {}).get("captions", []) if isinstance(item, dict) and "time" in item],
            key=lambda item: abs(float(item.get("time", 0.0)) - anchor_time),
        )[:1]
    quality_samples = [
        point["quality"]
        for point in visual_sample_points(visual)
        if start <= float(point["time"]) <= end and point.get("quality")
    ]
    quality = average_quality(quality_samples) if quality_samples else visual.get("visual_quality", {})
    return {
        "visual_quality": quality,
        "visual_quality_penalty": quality_penalty_from_visuals(quality),
        "ocr": visual.get("ocr", {}),
        "vision": {
            **visual.get("vision", {}),
            "captions": captions,
            "summary": summarize_vision_captions(captions),
        },
        "thumbnails": thumbnails,
    }


def visual_subclip_windows(candidate: dict[str, Any], visual: dict[str, Any], target_duration: float = TARGET_SEGMENT_SECONDS) -> list[tuple[float, float, float]]:
    if float(candidate.get("duration_sec", 0.0)) < 32:
        return []
    points = sorted(visual_sample_points(visual), key=lambda item: item["score"], reverse=True)
    event_points = [point for point in points if float(point.get("event_score", 0.0)) >= 1.5]
    minimum_score = max(2.5, float(event_points[0]["score"]) * 0.55) if event_points else 0.0
    windows = []
    for point in event_points:
        if point["score"] < minimum_score:
            continue
        anchor = point["time"]
        start = max(float(candidate["start"]), anchor - target_duration / 2)
        end = min(float(candidate["end"]), start + target_duration)
        start = max(float(candidate["start"]), end - target_duration)
        if end - start >= 12:
            windows.append((point["score"], start, end))
    accepted: list[tuple[float, float, float]] = []
    for score, start, end in windows:
        if any(max(0.0, min(end, used_end) - max(start, used_start)) / max(1.0, min(end - start, used_end - used_start)) > 0.55 for _, used_start, used_end in accepted):
            continue
        accepted.append((score, start, end))
    return sorted(accepted, key=lambda item: item[1])


def expand_with_visual_subclips(
    candidates: list[dict[str, Any]],
    visuals_by_id: dict[str, dict[str, Any]],
    segments: list[dict[str, Any]],
    duration: float,
) -> list[dict[str, Any]]:
    expanded = list(candidates)
    existing_ids = {candidate["id"] for candidate in expanded}
    for candidate in candidates:
        visual = visuals_by_id.get(candidate["id"])
        if not visual:
            continue
        for index, (score, start, end) in enumerate(visual_subclip_windows(candidate, visual)):
            candidate_id = f"{candidate['id']}_visual_{index:02d}"
            if candidate_id in existing_ids:
                continue
            split = candidate_from_window(candidate_id, start, end, segments, duration)
            if not split:
                continue
            visual_signals = visual_signal_subset(visual, split.start, split.end, (start + end) / 2)
            signals = {
                **split.signals,
                **visual_signals,
                "candidate_type": "subclip",
                "parent_candidate_id": candidate["id"],
                "split_reason": "visual_event",
                "split_event_score": round(score, 3),
            }
            expanded.append(candidate_to_dict(Candidate(split.id, split.start, split.end, split.transcript, signals)))
            existing_ids.add(candidate_id)
    return expanded


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


def number_value(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bool_value(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "standalone", "usable"}:
            return True
        if normalized in {"false", "no", "n", "0", "not_standalone", "not standalone", "unusable"}:
            return False
    return default


def string_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def string_list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、|]", value) if item.strip()]
    return []


def normalize_llm_scores(scores: Any) -> dict[str, float]:
    if not isinstance(scores, dict):
        return {}
    return {
        key: max(0.0, min(10.0, number_value(scores.get(key), 0.0)))
        for key in ("hook", "fun", "interaction", "place", "emotion", "clarity")
    }


def normalize_avoid_reason(value: Any) -> str:
    reason = string_value(value, "none") or "none"
    if reason.strip().lower() in {"none", "no", "n/a", "na", "usable", "ok", "okay"}:
        return "none"
    return reason


def final_score_from_scores(heuristic: dict[str, float], llm_scores: Optional[dict[str, Any]]) -> float:
    if not llm_scores:
        return heuristic["total_heuristic_score"]
    quality_penalty = heuristic.get("quality_penalty", 0.0)
    return (
        number_value(llm_scores.get("hook"), 0.0) * 0.25
        + number_value(llm_scores.get("fun"), 0.0) * 0.15
        + number_value(llm_scores.get("interaction"), 0.0) * 0.20
        + number_value(llm_scores.get("place"), 0.0) * 0.15
        + number_value(llm_scores.get("emotion"), 0.0) * 0.15
        + number_value(llm_scores.get("clarity"), 0.0) * 0.10
        - quality_penalty
    )


def compact_candidate_for_llm(candidate: dict[str, Any]) -> dict[str, Any]:
    signals = candidate.get("signals", {})
    vision = signals.get("vision", {}) if isinstance(signals.get("vision"), dict) else {}
    vision_summary = vision.get("summary", {}) if isinstance(vision.get("summary"), dict) else {}
    captions = vision.get("captions", []) if isinstance(vision.get("captions"), list) else []
    compact_captions = [
        {
            "time": caption.get("time"),
            "description": caption.get("description", ""),
            "subjects": caption.get("subjects", []),
            "setting": caption.get("setting", ""),
            "actions": caption.get("actions", []),
            "visual_hook": caption.get("visual_hook", ""),
        }
        for caption in captions[:3]
        if isinstance(caption, dict)
    ]
    return {
        "id": candidate.get("id"),
        "start": candidate.get("start"),
        "end": candidate.get("end"),
        "duration_sec": candidate.get("duration_sec"),
        "transcript": candidate.get("transcript", ""),
        "audio_text_signals": {
            "keywords": signals.get("keywords", []),
            "emotion_words": signals.get("emotion_words", []),
            "place_words": signals.get("place_words", []),
            "speech_density": signals.get("speech_density"),
            "utterance_count": signals.get("utterance_count"),
        },
        "visual": {
            "description": vision_summary.get("description", ""),
            "subjects": vision_summary.get("subjects", []),
            "stable_subjects": vision_summary.get("stable_subjects", []),
            "visual_hooks": vision_summary.get("visual_hooks", []),
            "captions": compact_captions,
        },
        "focus": signals.get("focus", {}),
    }


def run_ollama_chat_text(model: str, prompt: dict[str, Any], ollama_url: str = "http://127.0.0.1:11434", timeout_sec: float = 180.0) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        ollama_url.rstrip("/") + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_sec) as response:
        raw = json.loads(response.read().decode("utf-8"))
    return str(raw.get("message", {}).get("content", ""))


def score_with_ollama(candidate: dict[str, Any], model: str) -> dict[str, Any]:
    prompt = {
        "task": "Score this highlight candidate for a short video edit. Return valid JSON only with id, summary, title, tags, scores, is_standalone, avoid_reason.",
        "rubric": {
            "scores": "0 to 10 for hook, fun, interaction, place, emotion, clarity",
            "avoid_reason": "Use 'none' if usable.",
            "notes": "Prefer moments with clear visual action, viewer reaction, animal interaction, coherent context, and standalone value. Penalize unclear, repetitive, or weak moments.",
        },
        "candidate": compact_candidate_for_llm(candidate),
    }
    output = run_ollama_chat_text(model, prompt)
    parsed = parse_first_json(output)
    heuristic = heuristic_scores(candidate)
    llm_scores = normalize_llm_scores(parsed.get("scores", {}))
    tags = string_list_value(parsed.get("tags")) or infer_tags(candidate)
    avoid_reason = normalize_avoid_reason(parsed.get("avoid_reason", "none"))
    return {
        **score_with_heuristic(candidate),
        "summary": string_value(parsed.get("summary")) or summarize_transcript(candidate["transcript"]),
        "title": string_value(parsed.get("title")) or summarize_transcript(candidate["transcript"], max_chars=18),
        "tags": tags,
        "scores": llm_scores,
        "is_standalone": bool_value(parsed.get("is_standalone"), True),
        "avoid_reason": avoid_reason,
        "scoring_source": "ollama",
        "final_score": round(final_score_from_scores(heuristic, llm_scores), 3),
    }


def parse_first_json(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder(strict=False)
    for match in re.finditer(r"\{", text):
        try:
            data, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("No JSON object found")


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


def temporal_gap(left: dict[str, Any], right: dict[str, Any]) -> float:
    if float(left["end"]) <= float(right["start"]):
        return float(right["start"]) - float(left["end"])
    if float(right["end"]) <= float(left["start"]):
        return float(left["start"]) - float(right["end"])
    return 0.0


def continues_selected_moment(candidate: dict[str, Any], selected: list[dict[str, Any]], anchor_score_floor: float) -> bool:
    return any(temporal_gap(candidate, existing) <= 8.0 and float(existing.get("final_score", 0.0)) >= anchor_score_floor for existing in selected)


def resolve_target_duration(source_duration: float, requested_target: Optional[float], retention_ratio: float = DEFAULT_TARGET_RETENTION_RATIO) -> float:
    if requested_target is not None:
        return max(1.0, float(requested_target))
    return round(max(1.0, source_duration * max(0.0, retention_ratio)), 3)


def max_segments_for_target(target_duration: float) -> int:
    expected_padded_segment_seconds = TARGET_SEGMENT_SECONDS + DEFAULT_CLIP_PADDING * 2
    dynamic_count = int((target_duration + expected_padded_segment_seconds - 0.001) // expected_padded_segment_seconds)
    return max(3, min(MAX_SELECTED_SEGMENTS, dynamic_count))


def select_segments(scored: list[dict[str, Any]], target_duration: float) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    total = 0.0
    hard_budget = max(target_duration * HARD_DURATION_MULTIPLIER, target_duration + HARD_DURATION_EXTRA_SEC)
    max_selected = max_segments_for_target(target_duration)
    subclip_duration = sum(item["duration_sec"] for item in scored if item.get("signals", {}).get("candidate_type") == "subclip")
    prefer_subclips = subclip_duration >= target_duration * 0.8
    pool = [
        item
        for item in scored
        if not prefer_subclips or item.get("signals", {}).get("candidate_type") == "subclip" or item["duration_sec"] <= 32
    ]
    ranked_pool = sorted(pool, key=lambda item: item["final_score"], reverse=True)
    top_score = float(ranked_pool[0]["final_score"]) if ranked_pool else 0.0
    highlight_floor = max(MIN_HIGHLIGHT_SCORE, top_score * HIGHLIGHT_SCORE_RATIO)
    pre_target_floor = top_score * MIN_PRE_TARGET_SCORE_RATIO
    for candidate in ranked_pool:
        candidate_score = float(candidate["final_score"])
        is_continuation = continues_selected_moment(candidate, selected, pre_target_floor)
        if selected and total < target_duration and candidate_score < pre_target_floor and not is_continuation:
            continue
        if selected and total >= target_duration and candidate_score < highlight_floor:
            break
        if not candidate.get("is_standalone", True):
            continue
        if candidate.get("avoid_reason") not in (None, "", "none"):
            continue
        if any(overlap_ratio(candidate, existing) > 0.2 for existing in selected):
            continue
        if any(abs(candidate["start"] - existing["start"]) < 4 for existing in selected):
            continue
        if any(too_visually_similar(candidate, existing) and not is_continuation for existing in selected):
            continue
        if selected and total + candidate["duration_sec"] > hard_budget:
            continue
        selected.append(candidate)
        total += candidate["duration_sec"]
        if len(selected) >= max_selected:
            break
    return sorted(selected, key=lambda item: item["start"])


def selection_parameters(scored: list[dict[str, Any]], target_duration: float) -> dict[str, Any]:
    hard_budget = max(target_duration * HARD_DURATION_MULTIPLIER, target_duration + HARD_DURATION_EXTRA_SEC)
    max_selected = max_segments_for_target(target_duration)
    subclip_duration = sum(item["duration_sec"] for item in scored if item.get("signals", {}).get("candidate_type") == "subclip")
    prefer_subclips = subclip_duration >= target_duration * 0.8
    pool = [
        item
        for item in scored
        if not prefer_subclips or item.get("signals", {}).get("candidate_type") == "subclip" or item["duration_sec"] <= 32
    ]
    ranked_pool = sorted(pool, key=lambda item: item["final_score"], reverse=True)
    top_score = float(ranked_pool[0]["final_score"]) if ranked_pool else 0.0
    return {
        "hard_budget": hard_budget,
        "max_selected": max_selected,
        "prefer_subclips": prefer_subclips,
        "pre_target_floor": top_score * MIN_PRE_TARGET_SCORE_RATIO,
        "highlight_floor": max(MIN_HIGHLIGHT_SCORE, top_score * HIGHLIGHT_SCORE_RATIO),
    }


def skipped_reason(candidate: dict[str, Any], selected: list[dict[str, Any]], target_duration: float, params: dict[str, Any]) -> str:
    selected_duration = sum(float(item.get("duration_sec", 0.0)) for item in selected)
    if params.get("prefer_subclips") and candidate.get("signals", {}).get("candidate_type") != "subclip" and candidate["duration_sec"] > 32:
        return "filtered_by_subclip_preference"
    is_continuation = continues_selected_moment(candidate, selected, float(params["pre_target_floor"]))
    if selected and selected_duration < target_duration and float(candidate["final_score"]) < float(params["pre_target_floor"]) and not is_continuation:
        return "below_pre_target_floor"
    if selected and selected_duration >= target_duration and float(candidate["final_score"]) < float(params["highlight_floor"]):
        return "below_highlight_floor"
    if not candidate.get("is_standalone", True):
        return "not_standalone"
    if candidate.get("avoid_reason") not in (None, "", "none"):
        return f"avoid_reason:{candidate.get('avoid_reason')}"
    overlapping = next((item for item in selected if overlap_ratio(candidate, item) > 0.2), None)
    if overlapping:
        return f"overlaps_selected:{overlapping.get('id', '')}"
    nearby = next((item for item in selected if abs(candidate["start"] - item["start"]) < 4), None)
    if nearby:
        return f"near_selected_start:{nearby.get('id', '')}"
    similar = next((item for item in selected if too_visually_similar(candidate, item) and not is_continuation), None)
    if similar:
        return f"visually_similar:{similar.get('id', '')}"
    if selected and selected_duration + candidate["duration_sec"] > float(params["hard_budget"]):
        return "hard_duration_cap"
    if len(selected) >= int(params["max_selected"]):
        return "segment_cap"
    return "lower_rank"


def near_miss_segments(plan: dict[str, Any], scored: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    selected_ids = {segment.get("segment_id") for segment in plan.get("selected_segments", [])}
    scored_by_id = {item["id"]: item for item in scored}
    selected = [scored_by_id[segment_id] for segment_id in selected_ids if segment_id in scored_by_id]
    params = selection_parameters(scored, float(plan.get("target_duration_sec", 0.0) or 0.0))
    near_misses = []
    for candidate in sorted(scored, key=lambda item: item.get("final_score", 0), reverse=True):
        if candidate.get("id") in selected_ids:
            continue
        signals = candidate.get("signals", {})
        vision_summary = signals.get("vision", {}).get("summary", {})
        near_misses.append(
            {
                "segment_id": candidate.get("id", ""),
                "time": f"{format_time(float(candidate.get('start', 0.0)))}-{format_time(float(candidate.get('end', 0.0)))}",
                "duration_sec": candidate.get("duration_sec"),
                "title": candidate.get("title", candidate.get("id", "")),
                "summary": candidate.get("summary", ""),
                "final_score": candidate.get("final_score"),
                "skip_reason": skipped_reason(candidate, selected, float(plan.get("target_duration_sec", 0.0) or 0.0), params),
                "tags": candidate.get("tags", []),
                "transcript_excerpt": summarize_transcript(candidate.get("transcript", ""), max_chars=100),
                "visual_description": summarize_transcript(vision_summary.get("description", ""), max_chars=120),
                "visual_subjects": vision_summary.get("stable_subjects") or vision_summary.get("normalized_subjects") or vision_summary.get("subjects", []),
                "thumbnails": signals.get("thumbnails", []),
                "focus_score": signals.get("focus", {}).get("score", 0.0),
            }
        )
        if len(near_misses) >= limit:
            break
    return near_misses


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


def build_edit_plan(
    out_dir: Path,
    target_duration: Optional[float],
    clip_padding: float = DEFAULT_CLIP_PADDING,
    retention_ratio: float = DEFAULT_TARGET_RETENTION_RATIO,
) -> dict[str, Any]:
    source = read_json(out_dir / "source.json")
    scored = read_json(out_dir / "scored_segments.json")
    resolved_target_duration = resolve_target_duration(float(source.get("duration_sec", 0.0)), target_duration, retention_ratio)
    selected = select_segments(scored, resolved_target_duration)
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
        "target_duration_sec": resolved_target_duration,
        "target_duration_source": "explicit" if target_duration is not None else "source_retention_ratio",
        "target_retention_ratio": retention_ratio,
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


def selected_segment_details(plan: dict[str, Any], scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored_by_id = {item["id"]: item for item in scored}
    details = []
    for index, planned in enumerate(plan.get("selected_segments", []), start=1):
        scored_item = scored_by_id.get(planned.get("segment_id"), {})
        signals = scored_item.get("signals", {})
        vision_summary = signals.get("vision", {}).get("summary", {})
        focus = signals.get("focus", {})
        details.append(
            {
                "sequence": index,
                "segment_id": planned.get("segment_id", ""),
                "role": planned.get("role", ""),
                "time": f"{format_time(float(planned.get('source_start', 0.0)))}-{format_time(float(planned.get('source_end', 0.0)))}",
                "source_start": planned.get("source_start"),
                "source_end": planned.get("source_end"),
                "duration_sec": planned.get("duration_sec"),
                "original_source_start": planned.get("original_source_start"),
                "original_source_end": planned.get("original_source_end"),
                "title": planned.get("title") or scored_item.get("title") or planned.get("segment_id", ""),
                "summary": scored_item.get("summary") or planned.get("reason", ""),
                "reason": planned.get("reason", ""),
                "final_score": planned.get("final_score", scored_item.get("final_score")),
                "tags": scored_item.get("tags", []),
                "scores": scored_item.get("scores", {}),
                "heuristic_scores": scored_item.get("heuristic_scores", {}),
                "transcript_excerpt": summarize_transcript(scored_item.get("transcript", ""), max_chars=120),
                "keywords": signals.get("keywords", []),
                "emotion_words": signals.get("emotion_words", []),
                "place_words": signals.get("place_words", []),
                "ocr_excerpt": summarize_transcript(signals.get("ocr", {}).get("text", ""), max_chars=100),
                "visual_description": summarize_transcript(vision_summary.get("description", ""), max_chars=140),
                "visual_subjects": vision_summary.get("stable_subjects") or vision_summary.get("normalized_subjects") or vision_summary.get("subjects", []),
                "thumbnails": signals.get("thumbnails", []),
                "focus_matches": focus.get("matched_terms", []),
                "focus_score": focus.get("score", 0.0),
                "visual_quality": signals.get("visual_quality", {}),
                "avoid_reason": scored_item.get("avoid_reason", "none"),
                "scoring_source": scored_item.get("scoring_source", ""),
            }
        )
    return details


def compact_list(values: Any) -> str:
    items = listify(values)
    return ", ".join(items) if items else "-"


def thumbnail_paths(segment: dict[str, Any]) -> list[str]:
    paths = []
    for item in segment.get("thumbnails", []):
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item["path"]))
    return paths


def markdown_thumbnail_links(segment: dict[str, Any]) -> str:
    paths = thumbnail_paths(segment)
    if not paths:
        return "-"
    return ", ".join(f"`{path}`" for path in paths)


def format_score_map(scores: dict[str, Any], keys: list[str]) -> str:
    parts = []
    for key in keys:
        if key in scores:
            parts.append(f"{key}={scores[key]}")
    return ", ".join(parts) if parts else "-"


def build_review_report(out_dir: Path) -> dict[str, Any]:
    plan = read_json(out_dir / "edit_plan.json")
    scored = read_json(out_dir / "scored_segments.json")
    focus_path = out_dir / "project_focus.json"
    project_focus = read_json(focus_path) if focus_path.exists() else {}
    details = selected_segment_details(plan, scored)
    return {
        "version": "review_report_v1",
        "source_video": plan.get("source_video", ""),
        "output_video": plan.get("output_video", ""),
        "contact_sheet": "review_contact_sheet.jpg",
        "target_duration_sec": plan.get("target_duration_sec"),
        "selected_duration_sec": plan.get("selected_duration_sec"),
        "selected_count": len(details),
        "project_focus": project_focus,
        "selected_segments": details,
        "near_miss_segments": near_miss_segments(plan, scored),
    }


def ensure_review_report(out_dir: Path) -> dict[str, Any]:
    report_path = out_dir / "review_report.json"
    dependencies = [out_dir / "edit_plan.json", out_dir / "scored_segments.json"]
    if report_path.exists() and all(report_path.stat().st_mtime >= path.stat().st_mtime for path in dependencies if path.exists()):
        return read_json(report_path)
    return write_review_report(out_dir)


def scoring_fallback_ratio(scored: list[dict[str, Any]]) -> float:
    if not scored:
        return 1.0
    sources = [str(item.get("scoring_source", "")) for item in scored]
    if "ollama" not in sources:
        return 0.0
    fallback_count = sum(1 for source in sources if source != "ollama")
    return fallback_count / len(scored)


def selected_scored_items(plan: dict[str, Any], scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored_by_id = {item.get("id"): item for item in scored}
    return [scored_by_id[segment.get("segment_id")] for segment in plan.get("selected_segments", []) if segment.get("segment_id") in scored_by_id]


def top_score_spread(scored: list[dict[str, Any]], limit: int = 10) -> float:
    top_scores = [float(item.get("final_score", 0.0)) for item in sorted(scored, key=lambda item: item.get("final_score", 0.0), reverse=True)[:limit]]
    if len(top_scores) < 2:
        return 0.0
    return max(top_scores) - min(top_scores)


def selected_near_miss_gap(report: dict[str, Any]) -> Optional[float]:
    selected_scores = [float(item.get("final_score", 0.0)) for item in report.get("selected_segments", [])]
    near_miss_scores = [float(item.get("final_score", 0.0)) for item in report.get("near_miss_segments", [])]
    if not selected_scores or not near_miss_scores:
        return None
    return max(selected_scores) - max(near_miss_scores)


def selected_visual_repetition(selected: list[dict[str, Any]]) -> float:
    if len(selected) < 2:
        return 0.0
    similarities = []
    for left_index, left in enumerate(selected):
        for right in selected[left_index + 1 :]:
            similarities.append(scene_similarity(left, right))
    return max(similarities) if similarities else 0.0


def role_confidence(plan: dict[str, Any], scored: list[dict[str, Any]], role: str) -> float:
    scored_by_id = {item.get("id"): item for item in scored}
    planned = next((segment for segment in plan.get("selected_segments", []) if segment.get("role") == role), None)
    if not planned:
        return 0.0
    scored_item = scored_by_id.get(planned.get("segment_id"), {})
    scores = scored_item.get("scores", {}) if isinstance(scored_item.get("scores"), dict) else {}
    role_score = number_value(scores.get("hook" if role == "hook" else "clarity"), 0.0)
    final_score = number_value(scored_item.get("final_score", planned.get("final_score", 0.0)), 0.0)
    return max(role_score, final_score)


def all_selected_clarity_below(selected: list[dict[str, Any]], threshold: float) -> bool:
    if not selected:
        return False
    clarity_scores = [number_value(item.get("scores", {}).get("clarity"), 0.0) for item in selected]
    return all(score < threshold for score in clarity_scores)


def validate_edit_plan(plan: dict[str, Any], source_duration: Optional[float] = None) -> list[str]:
    errors = []
    selected = plan.get("selected_segments", [])
    if not isinstance(selected, list):
        return ["selected_segments_not_list"]
    for segment in selected:
        try:
            start = float(segment.get("source_start"))
            end = float(segment.get("source_end"))
        except (TypeError, ValueError):
            errors.append(f"invalid_bounds:{segment.get('segment_id', '')}")
            continue
        if start < 0 or end <= start:
            errors.append(f"invalid_bounds:{segment.get('segment_id', '')}")
        if source_duration is not None and end > source_duration:
            errors.append(f"outside_source:{segment.get('segment_id', '')}")
    for index, left in enumerate(selected):
        for right in selected[index + 1 :]:
            if max(0.0, min(float(left.get("source_end", 0.0)), float(right.get("source_end", 0.0))) - max(float(left.get("source_start", 0.0)), float(right.get("source_start", 0.0)))) > 0.5:
                errors.append(f"overlapping_plan_segments:{left.get('segment_id', '')}:{right.get('segment_id', '')}")
    return errors


def compute_plan_confidence(out_dir: Path) -> dict[str, Any]:
    plan = read_json(out_dir / "edit_plan.json")
    scored = read_json(out_dir / "scored_segments.json")
    report = ensure_review_report(out_dir)
    selected = selected_scored_items(plan, scored)
    selected_count = len(plan.get("selected_segments", []))
    target_duration = max(1.0, float(plan.get("target_duration_sec", 0.0) or 0.0))
    selected_duration = float(plan.get("selected_duration_sec", 0.0) or 0.0)
    duration_ratio = selected_duration / target_duration
    fallback_ratio = scoring_fallback_ratio(scored)
    score_spread = top_score_spread(scored)
    near_miss_gap = selected_near_miss_gap(report)
    repetition = selected_visual_repetition(selected)
    hook_score = role_confidence(plan, scored, "hook")
    ending_score = role_confidence(plan, scored, "ending")
    plan_errors = validate_edit_plan(plan)

    red_rules = []
    if selected_count == 0:
        red_rules.append({"rule": "selected_segments_zero", "detail": "No selected segments are available to render."})
    if duration_ratio < 0.45:
        red_rules.append({"rule": "selected_duration_under_45_percent", "value": round(duration_ratio, 3)})
    if fallback_ratio > 0.35:
        red_rules.append({"rule": "fallback_scoring_ratio_over_35_percent", "value": round(fallback_ratio, 3)})
    if all_selected_clarity_below(selected, 6.0):
        red_rules.append({"rule": "all_selected_clarity_under_6"})
    for error_name in plan_errors:
        red_rules.append({"rule": "invalid_edit_plan", "detail": error_name})

    yellow_rules = []
    if selected_count < 3:
        yellow_rules.append({"rule": "selected_segments_under_3", "value": selected_count})
    if duration_ratio < 0.70:
        yellow_rules.append({"rule": "selected_duration_under_70_percent", "value": round(duration_ratio, 3)})
    if near_miss_gap is not None and near_miss_gap < 0.3:
        yellow_rules.append({"rule": "near_miss_score_close_to_selected", "value": round(near_miss_gap, 3)})
    if len(scored) >= 3 and score_spread < 0.6:
        yellow_rules.append({"rule": "top_10_score_spread_under_0_6", "value": round(score_spread, 3)})
    if fallback_ratio > 0.15:
        yellow_rules.append({"rule": "fallback_scoring_ratio_over_15_percent", "value": round(fallback_ratio, 3)})
    if repetition >= 0.82:
        yellow_rules.append({"rule": "selected_visual_repetition_high", "value": round(repetition, 3)})
    if hook_score < 6.5:
        yellow_rules.append({"rule": "hook_confidence_weak", "value": round(hook_score, 3)})
    if selected_count >= 2 and ending_score < 6.5:
        yellow_rules.append({"rule": "ending_confidence_weak", "value": round(ending_score, 3)})

    if red_rules:
        status = "red"
        recommended_action = "codex_rerank"
    elif len(yellow_rules) >= 2:
        status = "yellow"
        recommended_action = "codex_review"
    else:
        status = "green"
        recommended_action = "render"

    confidence_score = max(0.0, min(1.0, 1.0 - len(red_rules) * 0.35 - len(yellow_rules) * 0.12))
    result = {
        "version": "plan_confidence_v1",
        "status": status,
        "confidence_score": round(confidence_score, 3),
        "recommended_action": recommended_action,
        "triggered_rules": red_rules + yellow_rules,
        "red_rules": red_rules,
        "yellow_rules": yellow_rules,
        "metrics": {
            "selected_count": selected_count,
            "target_duration_sec": round(target_duration, 3),
            "selected_duration_sec": round(selected_duration, 3),
            "duration_ratio": round(duration_ratio, 3),
            "fallback_scoring_ratio": round(fallback_ratio, 3),
            "top_10_score_spread": round(score_spread, 3),
            "selected_near_miss_score_gap": None if near_miss_gap is None else round(near_miss_gap, 3),
            "selected_visual_repetition": round(repetition, 3),
            "hook_confidence": round(hook_score, 3),
            "ending_confidence": round(ending_score, 3),
        },
    }
    write_json(out_dir / "plan_confidence.json", result)
    return result


def candidate_review_entry(candidate: dict[str, Any], skip_reason: str = "") -> dict[str, Any]:
    signals = candidate.get("signals", {})
    vision_summary = signals.get("vision", {}).get("summary", {}) if isinstance(signals.get("vision"), dict) else {}
    return {
        "segment_id": candidate.get("id", ""),
        "time": f"{format_time(float(candidate.get('start', 0.0)))}-{format_time(float(candidate.get('end', 0.0)))}",
        "start": candidate.get("start"),
        "end": candidate.get("end"),
        "duration_sec": candidate.get("duration_sec"),
        "title": candidate.get("title", candidate.get("id", "")),
        "summary": candidate.get("summary", ""),
        "final_score": candidate.get("final_score"),
        "scores": candidate.get("scores", {}),
        "tags": candidate.get("tags", []),
        "is_standalone": candidate.get("is_standalone", True),
        "avoid_reason": candidate.get("avoid_reason", "none"),
        "scoring_source": candidate.get("scoring_source", ""),
        "skip_reason": skip_reason,
        "transcript_excerpt": summarize_transcript(candidate.get("transcript", ""), max_chars=140),
        "visual_description": summarize_transcript(vision_summary.get("description", ""), max_chars=160),
        "visual_subjects": vision_summary.get("stable_subjects") or vision_summary.get("normalized_subjects") or vision_summary.get("subjects", []),
        "thumbnails": signals.get("thumbnails", []),
        "focus": signals.get("focus", {}),
    }


def build_gpt_review_packet(out_dir: Path, confidence: Optional[dict[str, Any]] = None, top_candidate_limit: int = 20) -> dict[str, Any]:
    plan = read_json(out_dir / "edit_plan.json")
    scored = read_json(out_dir / "scored_segments.json")
    report = ensure_review_report(out_dir)
    confidence = confidence or compute_plan_confidence(out_dir)
    focus_path = out_dir / "project_focus.json"
    project_focus = read_json(focus_path) if focus_path.exists() else {}
    selected_ids = {segment.get("segment_id") for segment in plan.get("selected_segments", [])}
    scored_by_id = {item.get("id"): item for item in scored}
    selected = [
        {
            **segment,
            "candidate": candidate_review_entry(scored_by_id.get(segment.get("segment_id"), {})),
        }
        for segment in plan.get("selected_segments", [])
    ]
    params = selection_parameters(scored, float(plan.get("target_duration_sec", 0.0) or 0.0))
    selected_scored = [scored_by_id[segment_id] for segment_id in selected_ids if segment_id in scored_by_id]
    near_misses = near_miss_segments(plan, scored, limit=10)
    top_candidates = []
    for candidate in sorted(scored, key=lambda item: item.get("final_score", 0.0), reverse=True)[:top_candidate_limit]:
        skip_reason = "" if candidate.get("id") in selected_ids else skipped_reason(candidate, selected_scored, float(plan.get("target_duration_sec", 0.0) or 0.0), params)
        top_candidates.append(candidate_review_entry(candidate, skip_reason))
    packet = {
        "version": "gpt_review_packet_v1",
        "reviewer": "codex_cli",
        "instructions": {
            "green": "Render directly from edit_plan.json.",
            "yellow": "Review current plan. Allowed operations: approve, reorder selected segments, replace with near miss, remove weak segment.",
            "red": "Rerank bounded candidates and rebuild edit_plan.json only from existing candidate IDs and valid source ranges.",
            "before_editing": "Copy edit_plan.json to edit_plan.before_codex_review.json.",
            "audit": "Write codex_review_result.json with the decision and reasons.",
        },
        "confidence": confidence,
        "project_focus": project_focus,
        "target_duration_sec": plan.get("target_duration_sec"),
        "selected_duration_sec": plan.get("selected_duration_sec"),
        "current_plan": plan,
        "selected_segments": selected,
        "near_miss_segments": near_misses,
        "top_candidates": top_candidates,
        "review_report": {
            "path": "review_report.md",
            "contact_sheet": report.get("contact_sheet", "review_contact_sheet.jpg"),
            "selected_count": report.get("selected_count", 0),
        },
    }
    write_json(out_dir / "gpt_review_packet.json", packet)
    return packet


def source_duration_for_plan(out_dir: Path, plan: dict[str, Any]) -> float:
    source_path = out_dir / "source.json"
    if source_path.exists():
        source = read_json(source_path)
        return float(source.get("duration_sec", 0.0) or 0.0)
    ends = [float(segment.get("source_end", 0.0) or 0.0) for segment in plan.get("selected_segments", [])]
    return max(ends) if ends else 0.0


def review_packet_allowed_ids(packet: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for key in ("selected_segments", "near_miss_segments", "top_candidates"):
        for item in packet.get(key, []):
            segment_id = item.get("segment_id") or item.get("candidate", {}).get("segment_id")
            if segment_id:
                allowed.add(str(segment_id))
    return allowed


def normalize_review_decision(value: Any) -> str:
    decision = string_value(value, "").lower().replace("-", "_")
    if decision in {"approve", "approved"}:
        return "approve"
    if decision in {"revise", "review", "edit", "modify"}:
        return "revise"
    if decision in {"rerank", "rebuild", "rescue"}:
        return "rerank"
    raise ValueError(f"Unsupported review decision: {value}")


def review_result_selected_ids(result: dict[str, Any], current_ids: list[str], allowed_ids: set[str]) -> list[str]:
    decision = normalize_review_decision(result.get("decision"))
    if decision == "approve":
        return current_ids
    explicit_ids = result.get("selected_segment_ids")
    if explicit_ids is not None:
        selected_ids = [str(item).strip() for item in listify(explicit_ids) if str(item).strip()]
        validate_review_segment_ids(selected_ids, allowed_ids)
        return selected_ids
    selected_ids = list(current_ids)
    operations = result.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("operations must be a list")
    if decision == "rerank" and not operations:
        raise ValueError("rerank requires selected_segment_ids or operations")
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("operation must be an object")
        op_name = string_value(operation.get("op")).lower().replace("-", "_")
        if op_name == "replace":
            remove_id = string_value(operation.get("remove") or operation.get("remove_segment_id"))
            add_id = string_value(operation.get("add") or operation.get("add_segment_id"))
            if remove_id not in selected_ids:
                raise ValueError(f"replace remove id not selected: {remove_id}")
            validate_review_segment_ids([add_id], allowed_ids)
            selected_ids[selected_ids.index(remove_id)] = add_id
        elif op_name == "remove":
            segment_id = string_value(operation.get("segment_id") or operation.get("remove"))
            if segment_id not in selected_ids:
                raise ValueError(f"remove id not selected: {segment_id}")
            selected_ids = [item for item in selected_ids if item != segment_id]
        elif op_name == "reorder":
            order = [str(item).strip() for item in listify(operation.get("segment_ids") or operation.get("order")) if str(item).strip()]
            if set(order) != set(selected_ids) or len(order) != len(selected_ids):
                raise ValueError("reorder must contain exactly the current selected segment ids")
            selected_ids = order
        else:
            raise ValueError(f"Unsupported review operation: {op_name}")
    validate_review_segment_ids(selected_ids, allowed_ids)
    return selected_ids


def validate_review_segment_ids(segment_ids: list[str], allowed_ids: set[str]) -> None:
    if not segment_ids:
        raise ValueError("review result selects no segments")
    duplicates = [segment_id for segment_id, count in Counter(segment_ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate selected segment ids: {', '.join(duplicates)}")
    unknown = [segment_id for segment_id in segment_ids if segment_id not in allowed_ids]
    if unknown:
        raise ValueError(f"segment ids are outside review packet: {', '.join(unknown)}")


def validate_selected_candidates(selected: list[dict[str, Any]], target_duration: float, source_duration: float) -> list[str]:
    errors = []
    for candidate in selected:
        if candidate.get("avoid_reason") not in (None, "", "none"):
            errors.append(f"avoid_reason:{candidate.get('id', '')}:{candidate.get('avoid_reason')}")
        if not candidate.get("is_standalone", True):
            errors.append(f"not_standalone:{candidate.get('id', '')}")
        if float(candidate.get("start", 0.0)) < 0 or float(candidate.get("end", 0.0)) <= float(candidate.get("start", 0.0)):
            errors.append(f"invalid_candidate_bounds:{candidate.get('id', '')}")
        if source_duration and float(candidate.get("end", 0.0)) > source_duration:
            errors.append(f"candidate_outside_source:{candidate.get('id', '')}")
    for index, left in enumerate(selected):
        for right in selected[index + 1 :]:
            if overlap_ratio(left, right) > 0.2:
                errors.append(f"candidate_overlap:{left.get('id', '')}:{right.get('id', '')}")
    selected_duration = sum(float(item.get("duration_sec", 0.0)) + DEFAULT_CLIP_PADDING * 2 for item in selected)
    hard_budget = max(target_duration * HARD_DURATION_MULTIPLIER, target_duration + HARD_DURATION_EXTRA_SEC)
    if selected_duration > hard_budget + 1.0:
        errors.append(f"selected_duration_over_hard_budget:{round(selected_duration, 3)}>{round(hard_budget, 3)}")
    return errors


def build_edit_plan_from_selected(
    base_plan: dict[str, Any],
    selected: list[dict[str, Any]],
    source_duration: float,
    clip_padding: float,
) -> dict[str, Any]:
    padding = max(0.0, clip_padding)
    padded_bounds = [
        (
            round(max(0.0, float(item["start"]) - padding), 3),
            round(min(source_duration, float(item["end"]) + padding) if source_duration else float(item["end"]) + padding, 3),
        )
        for item in selected
    ]
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
        **base_plan,
        "version": "edit_plan_v1",
        "selected_duration_sec": round(sum(item["duration_sec"] for item in segments), 3),
        "selected_segments": segments,
    }


def apply_codex_review(out_dir: Path, review_result_path: Optional[Path] = None) -> dict[str, Any]:
    review_result_path = review_result_path or (out_dir / "codex_review_result.json")
    if not review_result_path.exists():
        raise SystemExit(f"Review result not found: {review_result_path}")
    result = read_json(review_result_path)
    if not isinstance(result, dict):
        raise SystemExit("codex_review_result.json must be a JSON object")
    current_plan = read_json(out_dir / "edit_plan.json")
    scored = read_json(out_dir / "scored_segments.json")
    packet_path = out_dir / "gpt_review_packet.json"
    if packet_path.exists():
        packet = read_json(packet_path)
    else:
        packet = build_gpt_review_packet(out_dir)
    allowed_ids = review_packet_allowed_ids(packet)
    current_ids = [str(segment.get("segment_id")) for segment in current_plan.get("selected_segments", [])]
    try:
        selected_ids = review_result_selected_ids(result, current_ids, allowed_ids)
    except ValueError as exc:
        raise SystemExit(f"Invalid review result: {exc}") from exc

    if normalize_review_decision(result.get("decision")) == "approve" and selected_ids == current_ids:
        applied = {
            "version": "codex_review_apply_result_v1",
            "decision": "approve",
            "changed": False,
            "selected_segment_ids": selected_ids,
            "reason": string_value(result.get("reason")),
        }
        write_json(out_dir / "codex_review_apply_result.json", applied)
        log("Review approved current edit_plan.json without changes.")
        return applied

    scored_by_id = {item.get("id"): item for item in scored}
    selected = [scored_by_id[segment_id] for segment_id in selected_ids if segment_id in scored_by_id]
    if len(selected) != len(selected_ids):
        missing = [segment_id for segment_id in selected_ids if segment_id not in scored_by_id]
        raise SystemExit(f"Selected segment ids missing from scored_segments.json: {', '.join(missing)}")
    source_duration = source_duration_for_plan(out_dir, current_plan)
    target_duration = float(current_plan.get("target_duration_sec", 0.0) or 0.0)
    candidate_errors = validate_selected_candidates(selected, target_duration, source_duration)
    if candidate_errors:
        raise SystemExit("Invalid reviewed candidate selection: " + "; ".join(candidate_errors))
    clip_padding = number_value(
        current_plan.get("selected_segments", [{}])[0].get("clip_padding_sec") if current_plan.get("selected_segments") else None,
        DEFAULT_CLIP_PADDING,
    )
    reviewed_plan = build_edit_plan_from_selected(current_plan, selected, source_duration, clip_padding)
    plan_errors = validate_edit_plan(reviewed_plan, source_duration)
    if plan_errors:
        raise SystemExit("Reviewed edit_plan.json is invalid: " + "; ".join(plan_errors))

    backup_path = out_dir / "edit_plan.before_codex_review.json"
    shutil.copyfile(out_dir / "edit_plan.json", backup_path)
    write_json(out_dir / "edit_plan.gpt_reviewed.json", reviewed_plan)
    write_json(out_dir / "edit_plan.json", reviewed_plan)
    write_review_report(out_dir)
    confidence = compute_plan_confidence(out_dir)
    build_gpt_review_packet(out_dir, confidence)
    applied = {
        "version": "codex_review_apply_result_v1",
        "decision": normalize_review_decision(result.get("decision")),
        "changed": True,
        "selected_segment_ids": selected_ids,
        "backup_path": str(backup_path),
        "reviewed_plan_path": str(out_dir / "edit_plan.gpt_reviewed.json"),
        "reason": string_value(result.get("reason")),
        "post_apply_confidence": confidence,
    }
    write_json(out_dir / "codex_review_apply_result.json", applied)
    log(f"Applied Codex review to {out_dir / 'edit_plan.json'}")
    return applied


def render_review_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Highlight Review Report",
        "",
        f"- Source: `{report.get('source_video', '')}`",
        f"- Output: `{report.get('output_video', '')}`",
        f"- Contact sheet: `{report.get('contact_sheet', '')}`",
        f"- Target duration: {report.get('target_duration_sec', 0)}s",
        f"- Selected duration: {report.get('selected_duration_sec', 0)}s",
        f"- Selected clips: {report.get('selected_count', 0)}",
    ]
    focus_summary = report.get("project_focus", {}).get("summary", "")
    if focus_summary:
        lines.append(f"- Project focus: {focus_summary}")
    lines.append("")
    lines.append("## Selected Segments")
    for segment in report.get("selected_segments", []):
        lines.extend(
            [
                "",
                f"### {segment['sequence']}. {segment['title']} ({segment['segment_id']})",
                "",
                f"- Role/time: {segment['role']} at {segment['time']} ({segment['duration_sec']}s)",
                f"- Score/source: {segment.get('final_score', '-')} from {segment.get('scoring_source') or 'unknown'}",
                f"- Tags: {compact_list(segment.get('tags'))}",
                f"- Reason: {segment.get('reason') or segment.get('summary') or '-'}",
                f"- Transcript: {segment.get('transcript_excerpt') or '-'}",
                f"- Visual: {segment.get('visual_description') or '-'}",
                f"- Thumbnails: {markdown_thumbnail_links(segment)}",
                f"- Visual subjects: {compact_list(segment.get('visual_subjects'))}",
                f"- Focus: {compact_list([item.get('display', '') for item in segment.get('focus_matches', [])])} (score={segment.get('focus_score', 0)})",
                f"- Signals: keywords={compact_list(segment.get('keywords'))}; emotion={compact_list(segment.get('emotion_words'))}; place={compact_list(segment.get('place_words'))}",
                f"- Scores: {format_score_map(segment.get('scores', {}), ['hook', 'fun', 'interaction', 'place', 'emotion', 'clarity', 'focus'])}",
            ]
        )
        if segment.get("ocr_excerpt"):
            lines.append(f"- OCR: {segment['ocr_excerpt']}")
    near_misses = report.get("near_miss_segments", [])
    if near_misses:
        lines.extend(["", "## Near Misses"])
        for segment in near_misses:
            lines.extend(
                [
                    "",
                    f"### {segment['segment_id']}: {segment['title']}",
                    "",
                    f"- Time: {segment['time']} ({segment['duration_sec']}s)",
                    f"- Score: {segment.get('final_score', '-')}",
                    f"- Skip reason: {segment.get('skip_reason', '-')}",
                    f"- Tags: {compact_list(segment.get('tags'))}",
                    f"- Transcript: {segment.get('transcript_excerpt') or '-'}",
                    f"- Visual: {segment.get('visual_description') or '-'}",
                    f"- Thumbnails: {markdown_thumbnail_links(segment)}",
                    f"- Visual subjects: {compact_list(segment.get('visual_subjects'))}",
                    f"- Focus score: {segment.get('focus_score', 0)}",
                ]
            )
    lines.append("")
    return "\n".join(lines)


def contact_sheet_inputs(report: dict[str, Any], out_dir: Path) -> list[Path]:
    return [path for _, paths in contact_sheet_sections(report, out_dir) for path in paths]


def contact_sheet_sections(report: dict[str, Any], out_dir: Path) -> list[tuple[str, list[Path]]]:
    section_names = {
        "selected_segments": "selected",
        "near_miss_segments": "near_miss",
    }
    sections = []
    for section, section_name in section_names.items():
        paths = []
        for segment in report.get(section, []):
            segment_paths = thumbnail_paths(segment)
            if segment_paths:
                path = out_dir / segment_paths[min(1, len(segment_paths) - 1)]
                if path.exists():
                    paths.append(path)
        if paths:
            sections.append((section_name, paths))
    return sections


def contact_sheet_tile_width(columns: int) -> int:
    return columns * 360 + max(0, columns - 1) * 12 + 24


def write_contact_sheet_label_image(label: str, output_path: Path, width: int, height: int = 48) -> None:
    pixels = bytearray([12, 12, 12] * width * height)
    scale = 4
    x = 14
    y = 10
    for char in label.upper():
        if char == " ":
            x += scale * 4
            continue
        glyph = CONTACT_SHEET_FONT.get(char)
        if not glyph:
            x += scale * 6
            continue
        for row_index, row in enumerate(glyph):
            for col_index, bit in enumerate(row):
                if bit != "1":
                    continue
                left = x + col_index * scale
                top = y + row_index * scale
                for dy in range(scale):
                    py = top + dy
                    if py >= height:
                        continue
                    for dx in range(scale):
                        px = left + dx
                        if px >= width:
                            continue
                        offset = (py * width + px) * 3
                        pixels[offset : offset + 3] = b"\xf2\xf2\xf2"
        x += scale * 6
    output_path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + pixels)


def write_contact_sheet_tile(image_paths: list[Path], output_path: Path, columns: int, label: str = "") -> None:
    list_path = output_path.with_suffix(".txt")
    list_lines = [f"file '{path.resolve().as_posix()}'" for path in image_paths]
    list_path.write_text("\n".join(list_lines) + "\n", encoding="utf-8")
    rows = (len(image_paths) + columns - 1) // columns
    tile_path = output_path.with_name(f"{output_path.stem}_tile{output_path.suffix}") if label else output_path
    run_command(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-vf",
            f"scale=360:-1,tile={columns}x{rows}:padding=12:margin=12",
            "-frames:v",
            "1",
            str(tile_path),
        ]
    )
    if label:
        label_path = output_path.with_name(f"{output_path.stem}_label.ppm")
        write_contact_sheet_label_image(label, label_path, contact_sheet_tile_width(columns))
        stack_contact_sheet_tiles([label_path, tile_path], output_path)


def stack_contact_sheet_tiles(tile_paths: list[Path], output_path: Path) -> None:
    if len(tile_paths) == 1:
        shutil.copyfile(tile_paths[0], output_path)
        return
    args = ["ffmpeg", "-y", "-v", "error"]
    for tile_path in tile_paths:
        args.extend(["-i", str(tile_path)])
    args.extend(["-filter_complex", f"vstack=inputs={len(tile_paths)}", "-frames:v", "1", str(output_path)])
    run_command(args)


def write_contact_sheet(out_dir: Path, report: dict[str, Any]) -> Optional[Path]:
    sections = contact_sheet_sections(report, out_dir)
    if not sections or shutil.which("ffmpeg") is None:
        return None
    output_path = out_dir / str(report.get("contact_sheet") or "review_contact_sheet.jpg")
    columns = min(4, max(len(paths) for _, paths in sections))
    tile_paths = []
    for section_name, image_paths in sections:
        tile_path = out_dir / f"review_contact_sheet_{section_name}.jpg"
        write_contact_sheet_tile(image_paths, tile_path, columns, CONTACT_SHEET_LABELS.get(section_name, section_name))
        tile_paths.append(tile_path)
    stack_contact_sheet_tiles(tile_paths, output_path)
    return output_path


def write_review_report(out_dir: Path) -> dict[str, Any]:
    report = build_review_report(out_dir)
    write_contact_sheet(out_dir, report)
    write_json(out_dir / "review_report.json", report)
    (out_dir / "review_report.md").write_text(render_review_markdown(report), encoding="utf-8")
    return report


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
        clip_duration = max(0.0, float(segment["source_end"]) - float(segment["source_start"]))
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
                *render_encoding_args(settings, clip_duration),
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
    init_work_dir(out_dir, source_video, args.force)
    if args.force:
        invalidate_generated_artifacts(out_dir)
        ensure_work_subdirs(out_dir)
    audio_path = extract_audio(source_video, out_dir, args.force)
    transcript_path = transcribe_audio(audio_path, out_dir, args.whisper_model, args.force)
    transcript = read_json(transcript_path)
    source = read_json(out_dir / "source.json")
    candidates = generate_candidates_from_transcript(transcript, source["duration_sec"])
    write_json(out_dir / "candidates.json", candidates)
    log(f"Wrote {len(candidates)} candidates to {out_dir / 'candidates.json'}")


def command_score(args: argparse.Namespace) -> None:
    out_dir = Path(args.work_dir)
    source = read_json(out_dir / "source.json")
    target_duration = resolve_target_duration(float(source.get("duration_sec", 0.0)), args.target_duration, args.retention_ratio)
    candidates = read_json(out_dir / "candidates.json")
    visuals_by_id = load_visual_signals(out_dir)
    if visuals_by_id:
        transcript_path = out_dir / "transcript.json"
        segments = transcript_segments(read_json(transcript_path)) if transcript_path.exists() else []
        candidates = expand_with_visual_subclips(candidates, visuals_by_id, segments, float(source.get("duration_sec", 0.0)))
    candidates = attach_visual_signals(candidates, visuals_by_id)
    project_focus = infer_project_focus(candidates)
    write_json(out_dir / "project_focus.json", project_focus)
    candidates = attach_focus_signals(candidates, project_focus)
    scored = score_candidates(candidates, args.planner, args.model)
    write_json(out_dir / "scored_segments.json", scored)
    write_project_summary(out_dir, target_duration)
    log(f"Wrote {len(scored)} scored segments to {out_dir / 'scored_segments.json'}")


def command_analyze_visuals(args: argparse.Namespace) -> None:
    visual_segments = analyze_visuals(
        Path(args.work_dir),
        args.thumbnail_count,
        args.ocr_languages,
        args.vision_model,
        args.ollama_url,
        args.output_size,
    )
    log(f"Wrote visual metadata for {len(visual_segments)} candidates to {Path(args.work_dir) / 'visual_segments.json'}")


def command_plan(args: argparse.Namespace) -> None:
    out_dir = Path(args.work_dir)
    plan = build_edit_plan(out_dir, args.target_duration, args.clip_padding, args.retention_ratio)
    write_json(out_dir / "edit_plan.json", plan)
    write_project_summary(out_dir, plan["target_duration_sec"])
    write_review_report(out_dir)
    log(f"Wrote edit plan with {len(plan['selected_segments'])} segments to {out_dir / 'edit_plan.json'}")


def command_review_gate(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.work_dir)
    confidence = compute_plan_confidence(out_dir)
    build_gpt_review_packet(out_dir, confidence, args.top_candidates)
    log(
        "Review gate: "
        f"{confidence['status']} "
        f"(confidence={confidence['confidence_score']}, action={confidence['recommended_action']})"
    )
    if confidence["triggered_rules"]:
        for rule in confidence["triggered_rules"]:
            detail = rule.get("detail", rule.get("value", ""))
            log(f"- {rule.get('rule')}: {detail}")
    log(f"Wrote {out_dir / 'plan_confidence.json'} and {out_dir / 'gpt_review_packet.json'}")
    return confidence


def command_apply_review(args: argparse.Namespace) -> None:
    review_result_path = Path(args.review_result) if args.review_result else None
    applied = apply_codex_review(Path(args.work_dir), review_result_path)
    log(
        "Review apply result: "
        f"decision={applied['decision']} "
        f"changed={applied['changed']}"
    )


def command_report(args: argparse.Namespace) -> None:
    out_dir = Path(args.work_dir)
    report = write_review_report(out_dir)
    log(f"Wrote review report for {report['selected_count']} segments to {out_dir / 'review_report.md'}")


def command_render(args: argparse.Namespace) -> None:
    settings = RenderSettings(
        output_size=args.output_size,
        crf=args.crf,
        preset=args.preset,
        audio_bitrate=args.audio_bitrate,
        video_bitrate=args.video_bitrate,
        fade_duration=args.fade_duration,
    )
    render_edit_plan(Path(args.work_dir), settings)


def command_run(args: argparse.Namespace) -> None:
    prepare_args = argparse.Namespace(input=args.input, out=args.out, whisper_model=args.whisper_model, force=args.force)
    command_prepare(prepare_args)
    if args.visuals:
        command_analyze_visuals(
            argparse.Namespace(
                work_dir=args.out,
                thumbnail_count=args.thumbnail_count,
                ocr_languages=args.ocr_languages,
                vision_model=args.vision_model,
                ollama_url=args.ollama_url,
                output_size=args.output_size,
            )
        )
    score_args = argparse.Namespace(
        work_dir=args.out,
        planner=args.planner,
        model=args.model,
        target_duration=args.target_duration,
        retention_ratio=args.retention_ratio,
    )
    command_score(score_args)
    plan_args = argparse.Namespace(
        work_dir=args.out,
        target_duration=args.target_duration,
        clip_padding=args.clip_padding,
        retention_ratio=args.retention_ratio,
    )
    command_plan(plan_args)
    if args.review_mode != "off":
        review_args = argparse.Namespace(work_dir=args.out, top_candidates=args.review_top_candidates)
        confidence = command_review_gate(review_args)
        should_handoff = args.review_mode == "always" or confidence["status"] in {"yellow", "red"}
        if should_handoff:
            raise SystemExit(
                "Review gate requires Codex CLI editorial handoff before render. "
                f"Status={confidence['status']}; action={confidence['recommended_action']}. "
                f"Read {Path(args.out) / 'gpt_review_packet.json'}, update edit_plan.json if needed, "
                "write codex_review_result.json, then run render."
            )
    command_render(
        argparse.Namespace(
            work_dir=args.out,
            output_size=args.output_size,
            crf=args.crf,
            preset=args.preset,
            audio_bitrate=args.audio_bitrate,
            video_bitrate=args.video_bitrate,
            fade_duration=args.fade_duration,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-first automatic highlight editor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Extract audio, transcribe, and generate candidates")
    prepare.add_argument("input", help="Input video path")
    prepare.add_argument("--out", required=True, help="Work directory")
    prepare.add_argument("--whisper-model", default="small", help="faster-whisper model name or path")
    prepare.add_argument("--force", action="store_true", help="Clear generated artifacts and regenerate in an existing work directory")
    prepare.set_defaults(func=command_prepare)

    score = subparsers.add_parser("score", help="Score candidate segments")
    score.add_argument("work_dir", help="Work directory")
    score.add_argument("--planner", choices=["heuristic", "ollama"], default="heuristic")
    score.add_argument("--model", default=DEFAULT_TEXT_MODEL, help="Ollama model")
    score.add_argument("--target-duration", type=float, default=None, help="Explicit soft target duration in seconds; defaults to source duration times retention ratio")
    score.add_argument("--retention-ratio", type=float, default=DEFAULT_TARGET_RETENTION_RATIO, help="Default soft target as a fraction of source duration")
    score.set_defaults(func=command_score)

    analyze_visuals_parser = subparsers.add_parser("analyze-visuals", help="Extract thumbnails and visual/OCR metadata for candidates")
    analyze_visuals_parser.add_argument("work_dir", help="Work directory")
    analyze_visuals_parser.add_argument("--thumbnail-count", type=int, default=3)
    analyze_visuals_parser.add_argument("--ocr-languages", default="chi_tra+eng")
    analyze_visuals_parser.add_argument("--vision-model", default="", help="Optional Ollama vision model for thumbnail descriptions")
    analyze_visuals_parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    analyze_visuals_parser.add_argument("--output-size", type=output_size_arg, default=DEFAULT_OUTPUT_SIZE, help="Analysis proxy maximum size as WIDTHxHEIGHT")
    analyze_visuals_parser.set_defaults(func=command_analyze_visuals)

    plan = subparsers.add_parser("plan", help="Create edit_plan.json from scored segments")
    plan.add_argument("work_dir", help="Work directory")
    plan.add_argument("--target-duration", type=float, default=None, help="Explicit soft target duration in seconds; defaults to source duration times retention ratio")
    plan.add_argument("--retention-ratio", type=float, default=DEFAULT_TARGET_RETENTION_RATIO, help="Default soft target as a fraction of source duration")
    plan.add_argument("--clip-padding", type=float, default=DEFAULT_CLIP_PADDING, help="Seconds to add before and after each selected segment")
    plan.set_defaults(func=command_plan)

    review_gate = subparsers.add_parser("review-gate", help="Evaluate edit_plan confidence and prepare Codex CLI review packet")
    review_gate.add_argument("work_dir", help="Work directory")
    review_gate.add_argument("--top-candidates", type=int, default=20, help="Number of top scored candidates to include in the review packet")
    review_gate.set_defaults(func=command_review_gate)

    apply_review = subparsers.add_parser("apply-review", help="Validate and apply codex_review_result.json to edit_plan.json")
    apply_review.add_argument("work_dir", help="Work directory")
    apply_review.add_argument("--review-result", default="", help="Path to review result JSON; defaults to work_dir/codex_review_result.json")
    apply_review.set_defaults(func=command_apply_review)

    report = subparsers.add_parser("report", help="Create review_report.md and review_report.json from the edit plan")
    report.add_argument("work_dir", help="Work directory")
    report.set_defaults(func=command_report)

    render = subparsers.add_parser("render", help="Render highlight.mp4 from edit_plan.json")
    render.add_argument("work_dir", help="Work directory")
    render.add_argument("--output-size", type=output_size_arg, default=DEFAULT_OUTPUT_SIZE, help="Maximum render size as WIDTHxHEIGHT")
    render.add_argument("--crf", type=crf_arg, default=DEFAULT_RENDER_CRF, help="x264 CRF, lower is higher quality/larger files")
    render.add_argument("--preset", default=DEFAULT_RENDER_PRESET, help="x264 preset such as medium, slow, or veryfast")
    render.add_argument("--audio-bitrate", default=DEFAULT_AUDIO_BITRATE, help="AAC audio bitrate")
    render.add_argument("--video-bitrate", default="", help="Optional video bitrate such as 3500k; overrides CRF when set")
    render.add_argument("--fade-duration", type=non_negative_float_arg, default=DEFAULT_FADE_DURATION, help="Seconds for per-clip audio/video fade in and fade out")
    render.set_defaults(func=command_render)

    run = subparsers.add_parser("run", help="Run the full pipeline")
    run.add_argument("input", help="Input video path")
    run.add_argument("--out", required=True, help="Work directory")
    run.add_argument("--target-duration", type=float, default=None, help="Explicit soft target duration in seconds; defaults to source duration times retention ratio")
    run.add_argument("--retention-ratio", type=float, default=DEFAULT_TARGET_RETENTION_RATIO, help="Default soft target as a fraction of source duration")
    run.add_argument("--planner", choices=["heuristic", "ollama"], default="heuristic")
    run.add_argument("--model", default=DEFAULT_TEXT_MODEL, help="Ollama model")
    run.add_argument("--whisper-model", default="small", help="faster-whisper model name or path")
    run.add_argument("--force", action="store_true", help="Clear generated artifacts and regenerate in an existing work directory")
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
    run.add_argument("--fade-duration", type=non_negative_float_arg, default=DEFAULT_FADE_DURATION, help="Seconds for per-clip audio/video fade in and fade out")
    run.add_argument("--clip-padding", type=float, default=DEFAULT_CLIP_PADDING, help="Seconds to add before and after each selected segment")
    run.add_argument("--review-mode", choices=["off", "auto", "always"], default="off", help="Run Scheme C confidence gate before render")
    run.add_argument("--review-top-candidates", type=int, default=20, help="Number of top scored candidates to include in the Codex review packet")
    run.set_defaults(func=command_run)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
