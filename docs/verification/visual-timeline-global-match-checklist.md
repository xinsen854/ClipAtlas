# Visual Timeline / Global Match Verification Checklist

This branch is not merge-ready until every item below is backed by executable test evidence.

- [x] Same visual schema on script/video sides: subject/action/scene/environment/objects/configurations/quantities/relations/state_changes.
- [x] Chinese-first semantics with bilingual aliases for legacy English annotations.
- [x] Event -> Sequence uses content-driven boundaries; OCR changes do not fragment a stable process.
- [x] Complete sentence prefers one continuous source window before extra cuts.
- [x] Source evidence anchor is retained after trimming and can be positioned near Director anchor_phrase timing.
- [x] Whole-script reservation protects scarce S/DIRECT evidence from earlier sentences.
- [x] One output cannot silently reuse overlapping source ranges as fresh footage.
- [x] Batch reuse cooldown is configurable; fresh slightly-lower-score footage is preferred during cooldown.
- [x] Per-segment generic role is persistent and exposed through API.
- [x] Segment editor exposes 普通素材 / 通用空镜 / 审片占位 / 禁止使用 without a per-row role lookup.
- [x] Review-placeholder role is explicit, last-resort, local and still passes pollution admission.
- [x] Fallback remains exact -> related -> generic -> source -> reuse; placeholder is only used after legal neutral/source exhaustion.
- [x] PPT/title-card/technical-chart and mismatched text cannot bypass the media gate through generic/source/placeholder.
- [x] Focused regression suite green in CI (96 passed).
- [x] Full Python suite green in CI (998 passed).
- [ ] Frontend typecheck and full Vitest suite green with segment-role UI.
- [ ] Real API end-to-end sample confirms Chinese semantic output and candidate rerank behavior.
- [ ] Human visual acceptance sample confirms practical shot quality / repetition rate.

Notes:
- `anchor_phrase` alignment falls back to deterministic phrase-position timing when word-level narration timing is unavailable; it does not fabricate ASR word timestamps.
- Provider word-level timing already exists in the narration store and is the next precision improvement for exact spoken-anchor alignment.
- No change should be merged to `main` while the executable test items above are unchecked.
