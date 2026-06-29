# Auto Highlight Editor

Local-first automatic highlight editor for turning long videos into short highlight reels.

This project uses cheap local steps first: extract audio, transcribe speech, find likely highlight moments, score candidate segments, build an edit plan, then render the final video with `ffmpeg`.

## What It Does

Given a source video, the tool can:

- extract audio from the video
- create a timestamped transcript with `faster-whisper`
- find candidate clips from keywords, speech density, interaction, emotion, place words, and optional visual signals
- optionally use local Ollama models for text scoring and thumbnail description
- select clips that fit a target duration
- render `highlight.mp4`

The main idea is simple:

```text
input video
  -> audio + transcript
  -> candidate clips
  -> scoring
  -> edit_plan.json
  -> highlight.mp4
```

## Why Local First

The project avoids sending an entire video to a large remote model. Instead, it turns the video into smaller structured data first, then only asks AI models to judge smaller candidate segments.

This keeps the workflow:

- cheaper
- easier to debug
- easier to resume
- safer for private videos

## Requirements

Required:

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/)
- [`ffmpeg`](https://ffmpeg.org/) and `ffprobe`
- [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper)

Optional:

- [`ollama`](https://ollama.com/)
- `qwen3:6b` for text segment scoring
- `qwen2.5vl:7b` for thumbnail / screenshot descriptions
- OCR tools if you want richer visual analysis

## Installation

macOS with Homebrew:

```bash
brew install ffmpeg uv ollama
uv pip install faster-whisper
ollama pull qwen3:6b
ollama pull qwen2.5vl:7b
```

Ubuntu / Debian:

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-pip
curl -LsSf https://astral.sh/uv/install.sh | sh
uv pip install faster-whisper
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:6b
ollama pull qwen2.5vl:7b
```

Windows users can install `ffmpeg` with `winget`, install `uv` from Astral's installer, and install Ollama from the official website.

## Quick Start

Run the full pipeline:

```bash
uv run python auto_highlight.py run input.mp4 --out work/video1 --target-duration 180
```

Run with visual thumbnail analysis:

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --target-duration 180 \
  --visuals \
  --vision-model qwen2.5vl:7b
```

Use Ollama for text scoring:

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --target-duration 180 \
  --planner ollama \
  --model qwen3:6b
```

The final video is written to:

```text
work/video1/output/highlight.mp4
```

## Step-by-Step Mode

The pipeline can be resumed one stage at a time:

```bash
uv run python auto_highlight.py prepare input.mp4 --out work/video1
uv run python auto_highlight.py analyze-visuals work/video1 --vision-model qwen2.5vl:7b
uv run python auto_highlight.py score work/video1 --planner heuristic
uv run python auto_highlight.py plan work/video1 --target-duration 180
uv run python auto_highlight.py render work/video1
```

This is useful when a long video fails halfway through, or when you want to inspect intermediate JSON files before rendering.

## Output Structure

Each run writes files under `work/<video-name>/`:

```text
work/video1/
  source.json
  audio.wav
  transcript.json
  candidates.json
  visual_segments.json
  scored_segments.json
  project.summary.json
  edit_plan.json
  review_report.md
  clips/
  thumbnails/
  output/
    highlight.mp4
```

`work/` is intentionally ignored by git because it can contain private videos, transcripts, screenshots, audio, and rendered output.

## How Candidate Selection Works

The script looks for likely highlight moments using multiple signals:

- keywords such as `哈哈`, `哇`, `你看`, `景點`, `好吃`, `recommend`, and `wow`
- dense speech or quick back-and-forth interaction
- emotional words
- place-related words
- optional OCR / visual descriptions from thumbnails
- optional local LLM scoring through Ollama

Nearby candidates are merged so the final cut does not feel chopped up. Long candidate clips can be split into smaller subclips before final selection.

## Documentation Page

A beginner-friendly HTML guide is included:

```text
project-guide.html
```

Open it in a browser to read a visual explanation of the workflow, setup steps, and algorithm.

## Testing

Run the test suite with:

```bash
uv run python -m unittest
```

The current tests focus on timestamp formatting, candidate generation, transcript merging, visual signal handling, project focus inference, and scoring behavior.

## Privacy Notes

Do not commit:

- source videos
- rendered videos
- extracted audio
- transcripts from private videos
- thumbnails or contact sheets
- `.env` files or API keys
- model caches

The repository `.gitignore` is set up to exclude these generated and sensitive files.
