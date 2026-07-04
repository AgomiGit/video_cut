# Implementation Plan: Scheme C Plan Confidence + Codex Review

## Context

The highlight pipeline is local-first. Current flow:

```text
prepare
=> analyze-visuals
=> score
=> plan
=> render
```

The current implementation does not call a separate reviewer service. Local scoring is done by heuristics, and rendering is done by ffmpeg from `edit_plan.json`.

The desired design is Scheme C:

```text
prepare
=> analyze-visuals
=> score
=> plan
=> confidence-gate
   green: render directly
   yellow: main Codex CLI agent (gpt-5.5) reviews the current plan and may make small edits
   red: main Codex CLI agent (gpt-5.5) reranks top candidates and may rebuild the plan
=> render
```

Codex should not decide whether Codex review is needed. A local deterministic confidence gate decides `green`, `yellow`, or `red`.

The user normally runs this project through Codex CLI and wants the current main agent (`gpt-5.5`) to perform the review/rerank step itself. Simple bounded side checks can be delegated to `gpt-5.4-mini` subagents. Additional reviewer-service integrations are out of scope for this plan.

## Implementation Status

Implemented first slice:

- `review-gate` command.
- `plan_confidence.json`.
- `gpt_review_packet.json`.
- `run --review-mode auto|always|off`.
- Codex CLI handoff for yellow/red.
- `apply-review` command.
- Validation and application of `codex_review_result.json`.
- Backup of the previous plan to `edit_plan.before_codex_review.json` before reviewed changes are applied.
- `review-summary` command for human-readable handoff.
- `review_report.html` alongside JSON/Markdown review reports.
- `doctor` command to detect stale/missing artifacts before review.
- `subtitles` command to export final highlight SRT/VTT.
- Highlight profile metadata included in plans and scoring artifacts.

Not implemented yet:

- Automatic application of a review response from local artifacts.
- Burned-in subtitles during render.

## Architecture Decisions

- Insert the new logic after `command_plan()` and before `command_render()`.
- Keep `render` unaware of review. It should continue to read only `edit_plan.json`.
- Keep local-first behavior as the default. Codex review should only run when the confidence gate requests it.
- Write all intermediate artifacts so decisions are auditable.
- Codex should receive a compact review packet, not the full raw transcript or entire media.
- Yellow mode should be constrained: approve, reorder, replace with near miss, or remove weak segment.
- Red mode can rebuild the plan, but only from a bounded candidate set.
- Codex CLI handoff should be supported without any reviewer service.
- Keep the default path self-contained and driven by local artifacts plus the current agent's reasoning for yellow/red review.

## Planned Artifacts

```text
work/video1/
  edit_plan.json
  plan_confidence.json
  gpt_review_packet.json
  gpt_review_result.json
  edit_plan.before_gpt.json
  edit_plan.gpt_reviewed.json
```

## Phase 1: Local Confidence Gate

### Task 1: Compute Plan Confidence

Description: Add a deterministic confidence evaluator that reads `edit_plan.json`, `scored_segments.json`, and `review_report.json`, then determines whether the local plan is green, yellow, or red.

Acceptance criteria:

- Writes `plan_confidence.json`.
- Includes `status`, `confidence_score`, `triggered_rules`, and `recommended_action`.
- Does not require remote review or network access.
- Can be tested with synthetic plans and scored segments.

Initial red rules:

```text
selected_segments == 0
selected_duration < target_duration * 0.45
fallback_scoring_ratio > 0.35
all selected clarity scores < 6
edit_plan is invalid or cannot be rendered
```

Initial yellow rules:

```text
selected_segments < 3
selected_duration < target_duration * 0.70
top selected score - top near-miss score < 0.3
top 10 score spread < 0.6
fallback_scoring_ratio > 0.15
selected visual repetition is high
hook confidence is weak
ending confidence is weak
```

Decision:

```text
red if any red rule triggers
yellow if two or more yellow rules trigger
green otherwise
```

Files likely touched:

- `auto_highlight.py`
- `tests/test_plan_confidence.py`

Verification:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/video_cut_pycache python3 -m py_compile auto_highlight.py
uv run pytest tests/test_plan_confidence.py
```

### Task 2: Add CLI Command `review-gate`

Description: Add a command that runs only the confidence gate.

Example:

```bash
uv run python auto_highlight.py review-gate work/video1
```

Acceptance criteria:

- Reads existing work artifacts.
- Writes `plan_confidence.json`.
- Prints status and triggered rules.
- Does not modify `edit_plan.json`.

Files likely touched:

- `auto_highlight.py`
- `README.md`

## Checkpoint 1

- `review-gate` runs on an existing work directory.
- No separate reviewer service is needed.
- Existing `plan` and `render` behavior remains unchanged.

## Phase 2: Review Packet

### Task 3: Build Review Packet

Description: Create a compact packet with only the information a reviewer needs to review or rerank the plan.

Packet should include:

```text
project_focus
target_duration
current selected_segments
near_miss_segments
top 20 scored candidates
gate triggered_rules
review_report summary
contact_sheet path
```

Acceptance criteria:

- Writes `gpt_review_packet.json`.
- Packet is small enough to inspect manually.
- Each candidate includes transcript excerpt, visual summary, scores, skip reason, and thumbnails.
- Packet excludes unrelated raw metadata.

Files likely touched:

- `auto_highlight.py`
- `tests/test_review_packet.py`

## Phase 3: Yellow Review

For the user's normal workflow, this phase should support Codex CLI manual/agent review.

### Task 4: Add Review Boundary

Description: Add a boundary for reviewed plan edits without mixing it into scoring or rendering.

Acceptance criteria:

- Review input and output are valid JSON.
- Boundary can be mocked in tests.
- No silent fallback to local heuristics when review was explicitly requested.

Files likely touched:

- `auto_highlight.py`
- `.env.example` if introduced
- `README.md`

### Task 4A: Add Codex CLI Review Handoff

Description: Ensure yellow/red review can be completed by the Codex CLI agent without any external service dependency.

Acceptance criteria:

- `plan_confidence.json` and `gpt_review_packet.json` contain enough information for a Codex CLI agent to review manually.
- Instructions in `AGENTS.md` tell future agents how to handle green, yellow, and red.
- The agent can write `codex_review_result.json` and update `edit_plan.json` after backing up the original plan.
- No external service is required for this path.

Files likely touched:

- `AGENTS.md`
- `auto_highlight.py`
- `README.md`

### Task 5: Apply Yellow Review Results

Description: Let the reviewer make constrained edits to the current plan.

Allowed operations:

```text
approve
reorder selected segments
replace selected segment with a near miss
remove weak segment
```

Acceptance criteria:

- Writes `gpt_review_result.json`.
- Backs up the original plan to `edit_plan.before_review.json`.
- Writes the reviewed plan to `edit_plan.json` and optionally `edit_plan.reviewed.json`.
- Rejects unknown segment IDs.
- Rejects edits outside the provided packet.

Files likely touched:

- `auto_highlight.py`
- `tests/test_apply_gpt_review.py`

## Checkpoint 2

- Yellow path works with a fake local review response.
- All review modifications leave an audit trail.
- `render` still only reads `edit_plan.json`.

## Phase 4: Red Rerank

### Task 6: Apply Red Rerank Results

Description: In red mode, the reviewer may rebuild selected segments from a bounded candidate list.

Acceptance criteria:

- The reviewer can select only from top candidates in `gpt_review_packet.json`.
- Result must pass source bounds, overlap, duration, and segment ID validation.
- Invalid review output is rejected and the local plan is preserved.

Files likely touched:

- `auto_highlight.py`
- `tests/test_apply_gpt_rerank.py`

## Phase 5: Pipeline Integration

### Task 7: Integrate into `run`

Description: Add optional review behavior to the full pipeline.

Proposed flags:

```bash
--review-mode off|auto|always
--review-top-candidates 20
```

Behavior:

```text
off: do not run gate or review
auto: run gate; green renders directly; yellow/red may run review
always: run review regardless of gate status
```

Acceptance criteria:

- Default behavior remains local-only and unchanged.
- `--review-mode auto` does not run review when gate status is green.
- `--review-mode auto` may run review for yellow/red.
- Review artifacts are written before render.

Files likely touched:

- `auto_highlight.py`
- `README.md`
- `project-guide.html`

## Checkpoint 3

Full intended flow:

```bash
uv run python auto_highlight.py prepare input.mp4 --out work/video1
uv run python auto_highlight.py analyze-visuals work/video1
uv run python auto_highlight.py score work/video1
uv run python auto_highlight.py plan work/video1
uv run python auto_highlight.py review-gate work/video1
uv run python auto_highlight.py render work/video1
```

Later, with review enabled:

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --visuals \
  --review-mode auto \
  --review-top-candidates 20
```

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Review over-edits the plan | High | Yellow mode only allows constrained edits |
| Review work grows too much | Medium | Default local-only; auto runs review only for yellow/red |
| Review returns invalid JSON | Medium | Strict parsing and schema validation |
| Gate thresholds are too sensitive | Medium | Persist `triggered_rules` for tuning |
| Review packet is too large | Medium | Send top N candidates and excerpts only |
| Render becomes coupled to review | High | Keep render reading only `edit_plan.json` |

## Open Questions

- Should thresholds be hardcoded first or configurable through CLI?
- In yellow mode, can the reviewer shorten clip boundaries, or only replace/reorder/remove whole segments?
- In red mode, should the reviewer be limited to top 20 candidates or allowed to include near misses beyond top 20?
- Should `review-mode auto` run `review-gate` even if review is not configured, for diagnostics only?

## Recommended First Implementation Slice

Start with Phase 1 and Phase 2 only:

```text
review-gate + plan_confidence.json + gpt_review_packet.json
```

Do not connect any separate reviewer service in the first slice. First verify whether the local gate labels existing videos sensibly. After that, add yellow review with a fake local reviewer, then exercise the handoff flow end to end.
