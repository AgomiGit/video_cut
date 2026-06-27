# Auto Highlight Editor Plan

This document describes a local-first, low-token automatic highlight editor.
It is designed to start as a one-command script, then grow into a more precise
pipeline without requiring a frontend.

## Goal

Given a large video file, automatically extract highlight moments such as:

- funny moments
- real interaction
- important places or landmarks
- emotional reactions
- surprising or viral moments
- useful standalone clips

Then assemble selected clips into a new highlight video.

The key design principle is:

> Use cheap local tools to reduce the video into structured metadata, then use
> LLMs only on small candidate segments.

## Available Tools

Current target environment:

- `ffmpeg`
  - extract audio
  - cut clips
  - generate thumbnails
  - concatenate clips
  - normalize audio
  - burn subtitles later
- `uv`
  - run Python script and manage dependencies
- `faster-whisper`
  - local transcription with timestamps
- `ollama + qwen`
  - cheap local segment scoring, tagging, summarization
- optional `codex cli`
  - complex planning, debugging, edit plan refinement, file/schema edits

## Design Philosophy

Do not ask an LLM to watch the whole video.

Instead:

1. Convert video into transcript, timestamps, audio signals, and thumbnails.
2. Use rules to generate candidate segments.
3. Use Ollama for repetitive per-segment scoring.
4. Use Codex CLI only for complex global decisions if needed.
5. Render final video with ffmpeg.

## Recommended MVP

The first version should be a single script that can run end-to-end:

```bash
uv run python auto_highlight.py input.mp4 --out work/video1 --target-duration 180
```

It should:

1. Extract audio with ffmpeg.
2. Transcribe with faster-whisper.
3. Generate candidate clips using transcript rules.
4. Optionally score candidates with Ollama.
5. Pick top segments.
6. Create `edit_plan.json`.
7. Render `highlight.mp4` with ffmpeg.

No frontend. No database. No heavy visual AI in V1.

## Pipeline

```text
input.mp4
  ↓
ffmpeg extract audio
  ↓
faster-whisper transcript
  ↓
rule-based candidate generation
  ↓
audio/text heuristic scoring
  ↓
ollama local scoring, optional
  ↓
dedupe and select clips
  ↓
edit_plan.json
  ↓
ffmpeg render
  ↓
highlight.mp4
```

## Work Directory

Each run should create a self-contained work directory:

```text
work/video1/
  source.json
  audio.wav
  transcript.json
  candidates.json
  scored_segments.json
  project.summary.json
  edit_plan.json
  ffmpeg_concat.txt
  clips/
  thumbnails/
  output/
    highlight.mp4
```

This makes the pipeline debuggable and resumable.

## Script Modes

Even if the first script supports one-command execution, internally it should
be split into resumable steps:

```bash
uv run python auto_highlight.py prepare input.mp4 --out work/video1
uv run python auto_highlight.py score work/video1 --planner ollama --model qwen3:6b
uv run python auto_highlight.py plan work/video1 --target-duration 180
uv run python auto_highlight.py render work/video1
```

Also provide a shortcut:

```bash
uv run python auto_highlight.py run input.mp4 --out work/video1 --target-duration 180
```

## Candidate Generation

Use transcript segments and cheap signals first.

### Keyword Triggers

Start with Chinese/English keywords commonly found around highlights:

```text
哈哈
笑死
真的假的
你看
哇
靠
太扯
超猛
等一下
重點是
這個很重要
這邊
這裡
第一次看到
有名
排隊
景點
夜市
車站
老街
入口
好吃
推薦
地標
```

For each hit:

```text
candidate_start = hit_start - 8 seconds
candidate_end = hit_end + 20 seconds
```

Clamp to video bounds.

### Sliding Window

Use a sliding window so segment boundaries are not controlled only by Whisper:

```text
window size: 20-45 seconds
step size: 5-10 seconds
```

Score each window with heuristics:

- keyword count
- speech density
- question/exclamation count
- short back-and-forth utterances
- emotional words
- place-related words

Keep top candidates before calling Ollama.

### Merge Nearby Candidates

Merge candidates when they are close:

```text
if next.start - current.end < 10 seconds:
    merge
```

Apply length limits:

```text
minimum duration: 12 seconds
maximum duration: 75 seconds
```

## Heuristic Scoring

Each candidate should get a rule score before LLM scoring.

Suggested fields:

```json
{
  "keyword_score": 7.0,
  "speech_density_score": 6.5,
  "interaction_score": 5.0,
  "place_score": 8.0,
  "emotion_score": 7.5,
  "quality_penalty": 0.0,
  "total_heuristic_score": 7.1
}
```

This lets the pipeline work even without Ollama.

## Ollama Segment Scoring

Ollama should handle repetitive local judgments.

Good tasks for Ollama:

- summarize each candidate
- classify tags
- score hook, interaction, emotion, place value, clarity
- judge whether the clip is standalone
- generate a short title
- provide avoid reasons

Ollama should not make the final global edit unless Codex is unavailable or
the user explicitly wants full local mode.

### Ollama Prompt Shape

Send one candidate or a small batch at a time:

```json
{
  "id": "seg_023",
  "start": 832.4,
  "end": 871.2,
  "transcript": "哇這邊人也太多，你看那個隊伍...",
  "signals": {
    "keywords": ["哇", "你看", "太多"],
    "speech_density": 0.82,
    "volume_spike": true,
    "ocr": []
  }
}
```

Expected response:

```json
{
  "id": "seg_023",
  "summary": "夜市排隊人潮引發驚訝反應",
  "title": "這隊伍也太誇張",
  "tags": ["景點", "人潮", "反應"],
  "scores": {
    "hook": 8,
    "fun": 6,
    "interaction": 7,
    "place": 9,
    "emotion": 7,
    "clarity": 8
  },
  "is_standalone": true,
  "avoid_reason": "none"
}
```

The script should validate JSON and fall back to heuristic scores if parsing
fails.

## Final Score

Suggested weighted score:

```text
final_score =
  hook * 0.25
  + fun * 0.15
  + interaction * 0.20
  + place * 0.15
  + emotion * 0.15
  + clarity * 0.10
  - quality_penalty
```

For travel content, increase `place`.
For funny clips, increase `fun` and `interaction`.
For commentary/podcast clips, increase `clarity`.

## Deduplication

Avoid selecting too many clips from the same moment.

Simple rules:

- clips overlapping in time cannot both be selected
- clips within the same 5-minute block should be limited
- if two clips have very similar transcript text, keep the higher score
- if total target duration is reached, stop

Good initial rule:

```text
sort candidates by final_score desc
select candidate if:
  - it does not overlap selected clips by more than 20%
  - it is not within 30 seconds of an already selected clip
  - total duration remains under target + 10%
```

## Edit Plan

The render step should not decide what to cut.
It should only follow `edit_plan.json`.

Example:

```json
{
  "version": "edit_plan_v1",
  "source_video": "/absolute/path/input.mp4",
  "output_video": "work/video1/output/highlight.mp4",
  "target_duration_sec": 180,
  "selected_segments": [
    {
      "segment_id": "seg_023",
      "role": "hook",
      "source_start": 829.4,
      "source_end": 872.2,
      "title": "這隊伍也太誇張",
      "reason": "開頭有強反應，且地點與人潮明確。"
    }
  ]
}
```

## Render Strategy

Use ffmpeg to cut each selected segment into a temporary clip, then concatenate.

Basic robust approach:

```text
for each selected segment:
  ffmpeg -ss START -to END -i input.mp4 -c:v libx264 -c:a aac clip_N.mp4

create ffmpeg_concat.txt

ffmpeg -f concat -safe 0 -i ffmpeg_concat.txt -c copy highlight.mp4
```

This is slower than stream copy, but more reliable for arbitrary cut points.

Later optimization:

- use stream copy for fast drafts
- re-encode only final output
- add subtitles
- normalize loudness

## Codex CLI Handoff

Codex CLI should be used for complex global planning, not repetitive segment
scoring.

Use Codex CLI when:

- user wants a more nuanced final edit
- the script needs debugging
- edit plan should follow a creative direction
- selected clips need global ordering
- the user wants to keep or reject specific segments

Do not require Codex CLI for the default one-command script.

### Codex-Friendly Files

Generate:

```text
project.summary.json
codex_task.md
```

`project.summary.json` should be compact:

```json
{
  "target_duration_sec": 180,
  "style": "travel_funny_highlight",
  "segments": [
    {
      "id": "seg_023",
      "time": "00:13:49-00:14:32",
      "duration": 43,
      "summary": "夜市排隊人潮引發驚訝反應",
      "tags": ["景點", "人潮", "互動"],
      "scores": {
        "hook": 8,
        "place": 9,
        "interaction": 7,
        "emotion": 7,
        "clarity": 8
      },
      "quality": "good",
      "transcript_excerpt": "哇這邊人也太多..."
    }
  ]
}
```

Example handoff command:

```bash
codex "Read work/video1/codex_task.md and work/video1/project.summary.json. Create work/video1/edit_plan.json for a 3-minute highlight."
```

## Suggested Codex Task Template

```md
# Codex Edit Plan Task

Read:

- `project.summary.json`

Create:

- `edit_plan.json`

Rules:

- Output valid JSON only.
- Total selected duration should be target duration ± 10%.
- First segment must be a strong hook.
- Avoid repeated scenes, repeated topics, unclear context, poor audio, or poor visuals.
- Prefer varied roles: hook, context, place_highlight, interaction, payoff, ending.
- Do not modify source video files.
- Do not re-transcribe or analyze the whole video unless explicitly asked.
```

## Future V2 Improvements

After MVP works:

- add audio RMS and volume spike detection
- refine cut points using nearby silence
- add subtitle generation
- add better Qwen rubric scoring
- add a report HTML for manual review
- support `--keep seg_001,seg_003`
- support `--reject seg_010`
- support `--style funny|travel|educational|viral`

## Future V3 Improvements

Add visual metadata without becoming expensive:

- extract 3-5 thumbnails per candidate
- use OpenCV blur and brightness checks
- use PySceneDetect for scene boundaries
- optionally use OCR for signs, shops, landmarks, menus
- optionally add CLIP/SigLIP visual tags
- generate `report.html` with thumbnails, transcript, scores, and selected status

## One-Command Target Behavior

Desired command:

```bash
uv run python auto_highlight.py run /path/to/input.mp4 \
  --out work/video1 \
  --target-duration 180 \
  --model qwen3:6b \
  --planner ollama
```

Expected outputs:

```text
work/video1/transcript.json
work/video1/candidates.json
work/video1/scored_segments.json
work/video1/project.summary.json
work/video1/edit_plan.json
work/video1/output/highlight.mp4
```

The script should still work if Ollama is unavailable:

```bash
uv run python auto_highlight.py run input.mp4 --out work/video1 --planner heuristic
```

## Implementation Notes

- Prefer plain Python standard library where possible.
- Use subprocess for ffmpeg and Ollama calls.
- Store every intermediate JSON file.
- Make each step idempotent when practical.
- Print clear progress logs.
- Fail with actionable messages when a tool is missing.
- Keep the first implementation small and direct.

## Success Criteria

The first usable version is successful if it can:

1. Accept one input video path.
2. Produce a transcript with timestamps.
3. Generate candidate highlight segments.
4. Score and select a reasonable subset.
5. Render a playable highlight video.
6. Save enough metadata for debugging and future Codex CLI handoff.

