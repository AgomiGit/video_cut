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
- `uv run python auto_highlight.py score work/video1 --planner ollama --model qwen3:1.7b`: score candidate clips locally.
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
Read `PROJECT_MEMORY.md` at the start of future work to catch up on the current implementation status, latest handoff notes, and likely next steps.

## Codex CLI Operating Mode

The user usually operates this project by opening Codex CLI and asking the agent to cut videos. Do not assume the user will configure an external LLM provider API key. If a future workflow mentions GPT-5.5 review, treat the current Codex CLI agent as the reviewer/reranker unless the user explicitly asks for an external provider.

Within `/Users/aksilver/Documents/video_cut`, run normal read/write, tests, formatting, and local pipeline commands directly. Ask for escalation only for network access, GUI actions, writes outside the workspace, large deletions, or destructive git operations.

## Scheme C Review Handoff

The long-term design for GPT-assisted review is documented in `gpt_review_scheme_c_plan.md`. The intended flow is:

```text
prepare
=> analyze-visuals
=> score
=> plan
=> confidence-gate
   green: render directly
   yellow: Codex CLI reviews the current plan and may make small edits
   red: Codex CLI reranks top candidates and may rebuild the plan
=> render
```

Important: GPT/Codex must not decide whether it should be called. A local deterministic confidence gate should decide `green`, `yellow`, or `red`. If that gate is not implemented yet, manually apply the rules from `gpt_review_scheme_c_plan.md` and write down the reasoning in the final response or a review artifact.

When a run reaches `green`:

- Render directly from `edit_plan.json`.
- Do not perform extra GPT/Codex editorial changes unless the user asks.

When a run reaches `yellow`:

- Read `edit_plan.json`, `scored_segments.json`, `review_report.json` or `review_report.md`, and the contact sheet if available.
- Act as a constrained senior editor.
- Only allow these changes: approve current plan, reorder selected segments, replace a selected segment with a near miss, or remove a weak segment.
- Do not invent segment IDs or choose clips outside the available scored/near-miss candidates.
- Write `codex_review_result.json` explaining the decision and every change.
- Run `uv run python auto_highlight.py apply-review <work-dir>` to validate and apply the result.
- Render only after `apply-review` accepts the reviewed plan.

When a run reaches `red`:

- Read `scored_segments.json`, `review_report.json` or `review_report.md`, `project_focus.json`, and visual summaries/thumbnails if available.
- Act as a rescue editor and rerank a bounded set of candidates, preferably the top 20 plus near misses.
- Write `codex_review_result.json` with the rejected local-plan issues, selected replacement segments, and reasoning.
- Run `uv run python auto_highlight.py apply-review <work-dir>` so the program rebuilds `edit_plan.json` only from existing candidate IDs and valid source time ranges.
- Render only after `apply-review` validates duration, overlap, source bounds, and segment IDs.

Use this review result schema:

```json
{
  "version": "codex_review_result_v1",
  "decision": "approve",
  "reason": "current plan is good"
}
```

```json
{
  "version": "codex_review_result_v1",
  "decision": "revise",
  "reason": "replace weak segment with a stronger near miss",
  "operations": [
    {"op": "replace", "remove": "seg_010", "add": "seg_012"},
    {"op": "reorder", "segment_ids": ["seg_000", "seg_012", "seg_008"]}
  ]
}
```

```json
{
  "version": "codex_review_result_v1",
  "decision": "rerank",
  "reason": "red rescue plan",
  "selected_segment_ids": ["seg_000", "seg_012", "seg_008"]
}
```

Do not use stale artifacts silently. If `scored_segments.json`, `visual_segments.json`, `review_report.json`, or thumbnails are missing or clearly from an older run, regenerate the relevant pipeline stage before reviewing. Generated media and `work/` outputs should not be committed.
