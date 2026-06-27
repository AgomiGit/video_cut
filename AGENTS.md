# Repository Guidelines

## Project Structure & Module Organization

This repository currently contains planning material for a local-first automatic highlight editor. The main design document is `auto_highlight_editor_plan.md`. The planned implementation centers on a Python entry point named `auto_highlight.py`, with per-run artifacts stored under `work/<video-name>/`.

Expected generated run structure:

```text
work/video1/
  transcript.json
  candidates.json
  scored_segments.json
  edit_plan.json
  clips/
  thumbnails/
  output/highlight.mp4
```

Keep source files at the repository root until the codebase grows enough to justify a package directory. Do not commit large generated media, `work/` outputs, or model/cache artifacts.

## Build, Test, and Development Commands

The project is intended to use `uv` for Python execution and dependency management.

- `uv run python auto_highlight.py run input.mp4 --out work/video1 --target-duration 180`: run the full highlight pipeline once implemented.
- `uv run python auto_highlight.py prepare input.mp4 --out work/video1`: extract audio and prepare metadata.
- `uv run python auto_highlight.py score work/video1 --planner ollama --model qwen3:6b`: score candidate clips locally.
- `uv run python auto_highlight.py render work/video1`: render the final video with `ffmpeg`.

Required local tools are expected to include `ffmpeg`, `uv`, `faster-whisper`, and optionally `ollama`.

## Coding Style & Naming Conventions

Use Python with 4-space indentation, clear function names, and small pipeline steps that can be resumed independently. Prefer descriptive snake_case names such as `generate_candidates`, `score_segments`, and `write_edit_plan`. Store structured pipeline state as JSON with stable, documented keys.

## Testing Guidelines

No test framework is committed yet. When adding code, include focused tests for timestamp math, candidate merging, scoring heuristics, and edit-plan generation. Prefer `pytest` and name tests `test_<behavior>.py`. Keep tests media-light by using small fixtures or synthetic transcript JSON.

## Commit & Pull Request Guidelines

This repository has no commit history yet, so use concise imperative commit messages, for example `Add candidate merging logic`. Pull requests should describe the pipeline stage affected, include the command used for verification, and note any external tools or models required. For rendering changes, include before/after details such as clip count, target duration, and output path.

## Agent-Specific Instructions

Check for existing generated outputs before writing into `work/`. Preserve user-created media and plans unless explicitly asked to regenerate them.
