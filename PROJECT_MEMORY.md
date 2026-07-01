# Project Memory

Last updated: 2026-07-01

## Current State

This repo now has a working local-first automatic highlight editor in `auto_highlight.py`.
The normal user flow is still Codex CLI driven: the user asks Codex to cut a video,
and the pipeline should avoid requiring an external LLM provider API key.

Important implemented features:

- `prepare`, `analyze-visuals`, `score`, `plan`, `review-gate`, `review-summary`, `apply-review`, `report`, `subtitles`, `doctor`, `render`, and `run` commands.
- Built-in highlight profiles: `default`, `travel`, `family`, `teaching`, `funny`.
- Custom profile support via `--profile-file`.
- Per-run profile artifact: `work/<name>/highlight_profile.json`.
- Profile scoring audit fields in `scored_segments.json`: `profile_score`, `profile_adjusted_from`, `profile_name`.
- Review outputs: `review_report.json`, `review_report.md`, `review_report.html`, contact sheets, and `gpt_review_packet.json`.
- Subtitle export aligned to the final highlight timeline: `subtitles.srt`, `subtitles.vtt`, `subtitles.json`.
- `doctor` writes `doctor_report.json` and checks source fingerprint, missing/stale artifacts, visual coverage, output freshness, and edit plan validity.

## Latest Local Work

The latest implementation round added:

1. Highlight style profiles and profile-aware candidate/scoring behavior.
2. HTML review report generation.
3. SRT/VTT subtitle export.
4. `doctor` artifact freshness and validity checks.
5. README and `project-guide.html` updates for the new workflow.
6. Tests covering profile candidate generation, profile score audit fields, subtitle timeline mapping, and doctor stale-report detection.

Verification command used:

```bash
python3 -m unittest discover -s tests
```

Result at handoff: 70 tests passing.

## Handoff Notes

- Do not push to GitHub unless the user explicitly asks.
- Do not commit generated media, `work/` outputs, thumbnails, transcripts, audio, or rendered videos.
- Before reviewing a yellow/red run, run `doctor` or manually check artifact freshness.
- If `review-gate` returns green, render directly from `edit_plan.json`; do not make extra editorial changes unless asked.
- If `review-gate` returns yellow/red, write `codex_review_result.json`, run `apply-review`, then render only after validation passes.

## Likely Next Steps

- Add `render --burn-subtitles` to create a subtitle-burned video, likely `output/highlight_subtitled.mp4`.
- Add `--keep` and `--reject` segment controls for user-directed selection.
- Consider splitting `auto_highlight.py` into modules once the next feature round starts.
- Improve `review_report.html` with inline clip preview once clip paths are stable after render.
