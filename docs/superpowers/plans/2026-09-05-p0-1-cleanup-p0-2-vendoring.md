# P0-1 Cleanup + P0-2 SentrySearch Vendoring

## Scope

1. Remove only verified P0-1 frontend redundancy:
   - unused `listSettingsModels` client helper and response type
   - duplicate `SettingsPage.bailian.test.tsx`
2. Vendor only the locked SentrySearch core from commit `a89d1282fe52dd98aa71593cda86f8e8b4fbdd3b`:
   - `base_embedder.py`
   - `chunker.py`
   - `qwen_cloud_embedder.py`
   - `dlq.py`
   - attribution/NOTICE
3. Do not wire the vendored code into production indexing yet. Runtime replacement belongs to P0-3.
4. Preserve upstream code as closely as possible; patch only import paths or packaging necessities required for the vendored files to import and test in ClipAtlas.

## Verification

- RED: tests fail before vendored core exists.
- GREEN: vendored modules import and locked source/provenance tests pass.
- Full CI: Ruff, Mypy, Pytest, frontend tests, typecheck, build.
- Reverse diff: no ASR/OCR/TTS/retrieval/runtime wiring changes.
