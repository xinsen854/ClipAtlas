# ClipAtlas Narration / TTS V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 provider-neutral 的旁白/TTS 子系统，让 TTS 或用户导入的真实音频成为后续自动剪辑的权威时间轴，并支持音色/性别/年龄/语速/音高/音量/情绪、可复现随机、项目级锁定、自定义 HTTP、本地 HTTP、断点续作和版本历史。

**Architecture:** `SpeechProvider` 只负责合成能力；`VoiceSelector` 负责筛选、随机和项目锁定；`NarrationStore` 负责 SQLite 版本历史与 checkpoint；`AudioNormalizer` 使用 FFmpeg/ffprobe 生成 canonical WAV 并实测时长；`NarrationService` 按 Narration Unit 分段合成并拼接为 Track。后续 RoughCut 只读取 `NarrationTrack + NarrationUnit + optional NarrationWordTiming`，绝不直接依赖某家 TTS。

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, httpx, FFmpeg/ffprobe, pytest, Ruff, strict Mypy.

**Spec:** `docs/superpowers/specs/2026-09-02-narration-tts-v0.1-design.md`

## Global Constraints

- 已存在真实音频时，真实音频时长是剪辑权威；文字估算只能用于 `NONE/ESTIMATED` 模式。
- `TTS` 与 `IMPORTED` 由项目当前激活模式决定权威来源，切换模式不删除旧 Track/Profile。
- 默认“项目随机一次并锁定”，禁止默认每句随机声音。
- 随机必须保存 `random_seed`，同 seed + 同 voice pool + 同约束必须可复现。
- Provider 不支持的参数不得偷偷发送；capabilities 是 UI/服务层权威。
- TTS 以 Unit 为 checkpoint；失败后重试跳过已成功 Unit。
- Provider duration/timestamps 只是证据；最终 canonical duration 必须由 ClipAtlas 对规范化音频重新测量。
- Imported narration 没有 aligner 时必须标 `TRACK_ONLY`，禁止伪造句/词时间码。
- V0.1 canonical narration 为 WAV/PCM，默认 48 kHz。
- 自定义/本地 Provider 只能通过受控 HTTP；V0.1 不执行用户提供的任意 shell/code。
- 所有旧 Track/Profile/Unit revision 保留，不覆盖历史。
- 后续 RoughCut 只消费 canonical narration types，不读取 provider 私有对象。

---

### Task 1: Speech domain models, capabilities, errors, and provider protocol

**Files:**
- Create: `clipatlas/speech/__init__.py`
- Create: `clipatlas/speech/models.py`
- Create: `clipatlas/speech/contracts.py`
- Create: `clipatlas/speech/errors.py`
- Test: `tests/speech/test_speech_models.py`
- Test: `tests/speech/test_speech_contracts.py`

**Interfaces:**
- Produces `VoiceGender`, `AgeStyle`, `RandomMode`, `NarrationSourceMode`, `TimingQuality` enums.
- Produces `VoiceDescriptor`, `SpeechProfile`, `NarrationTrack`, `NarrationUnit`, `NarrationWordTiming`, `SpeechSynthesisRequest`, `SpeechSynthesisResult`.
- Produces runtime-checkable `SpeechProvider` protocol with `name`, `model`, `capabilities`, `list_voices()`, `synthesize()`.
- Produces normalized speech errors.

- [ ] **Step 1: Write failing model tests**

```python
from uuid import uuid4

from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    RandomMode,
    SpeechProfile,
    TimingQuality,
)


def test_profile_is_project_scoped_and_can_be_locked() -> None:
    project_id = uuid4()
    profile = SpeechProfile(
        project_id=project_id,
        provider="fake",
        model="fake-tts",
        voice_id="voice-a",
        random_mode=RandomMode.RANDOM_VOICE,
        random_seed=42,
        locked=True,
    )
    assert profile.project_id == project_id
    assert profile.locked is True


def test_track_preserves_real_duration_and_revision() -> None:
    track = NarrationTrack(
        project_id=uuid4(),
        source_mode=NarrationSourceMode.TTS,
        script_hash="abc",
        provider="fake",
        model="fake-tts",
        audio_uri="file:///track.wav",
        duration_ms=1234,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=1,
    )
    assert track.duration_ms == 1234
    assert track.revision == 1
```

- [ ] **Step 2: Write failing protocol/capability tests**

```python
from clipatlas.speech.contracts import SpeechProviderCapabilities


def test_capabilities_default_to_false() -> None:
    capabilities = SpeechProviderCapabilities()
    assert capabilities.speed_control is False
    assert capabilities.word_timestamps is False
```

- [ ] **Step 3: Run RED**

Run: `pytest tests/speech/test_speech_models.py tests/speech/test_speech_contracts.py -v`
Expected: FAIL because `clipatlas.speech` does not exist.

- [ ] **Step 4: Implement the minimal domain layer**

Use Pydantic models with ClipAtlas-owned UUIDs and UTC timestamps. Validate `speed > 0`, nonnegative `duration_ms/start_ms`, and `end_ms > start_ms` for timed units/words. `NarrationUnit` may have `start_ms/end_ms=None` only before synthesis; persisted completed units must have real timing.

`SpeechProviderCapabilities` fields:

```python
preset_voices: bool = False
voice_metadata: bool = False
speed_control: bool = False
pitch_control: bool = False
volume_control: bool = False
emotion_control: bool = False
instruction_control: bool = False
voice_clone: bool = False
voice_design: bool = False
word_timestamps: bool = False
streaming: bool = False
languages: list[str] = Field(default_factory=list)
```

Normalized errors:

```python
class SpeechError(Exception):
    pass

class SpeechAuthenticationError(SpeechError):
    pass

class SpeechRateLimitError(SpeechError):
    pass

class SpeechRequestError(SpeechError):
    pass

class SpeechConfigurationError(SpeechError):
    pass

class SpeechAudioValidationError(SpeechError):
    pass
```

- [ ] **Step 5: Run GREEN and full static checks**

Run:
```bash
ruff check clipatlas/speech tests/speech/test_speech_models.py tests/speech/test_speech_contracts.py
mypy clipatlas/speech
pytest tests/speech/test_speech_models.py tests/speech/test_speech_contracts.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add clipatlas/speech tests/speech/test_speech_models.py tests/speech/test_speech_contracts.py
git commit -m "feat: add speech domain contracts"
```

---

### Task 2: Voice selection, deterministic randomization, and project lock

**Files:**
- Create: `clipatlas/speech/voices.py`
- Test: `tests/speech/test_voice_selector.py`

**Interfaces:**
- Consumes `VoiceDescriptor`, `SpeechProfile`, `RandomMode`, `SpeechProviderCapabilities`.
- Produces `VoiceConstraints`.
- Produces `VoiceSelector.select(project_id, provider, model, voices, constraints, mode, seed, capabilities, voice_id=None) -> SpeechProfile`.

- [ ] **Step 1: Write failing tests for filtering and reproducibility**

```python
from uuid import uuid4

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.models import RandomMode, VoiceDescriptor
from clipatlas.speech.voices import VoiceConstraints, VoiceSelector


def _voices() -> list[VoiceDescriptor]:
    return [
        VoiceDescriptor(
            provider="fake",
            voice_id="m1",
            display_name="M1",
            gender="male",
            languages=["zh-CN"],
        ),
        VoiceDescriptor(
            provider="fake",
            voice_id="f1",
            display_name="F1",
            gender="female",
            languages=["zh-CN"],
        ),
    ]


def test_random_voice_stays_inside_constraints() -> None:
    selector = VoiceSelector()
    profile = selector.select(
        project_id=uuid4(),
        provider="fake",
        model="fake",
        voices=_voices(),
        constraints=VoiceConstraints(gender="female", language="zh-CN"),
        mode=RandomMode.RANDOM_VOICE,
        seed=7,
        capabilities=SpeechProviderCapabilities(speed_control=True),
    )
    assert profile.voice_id == "f1"


def test_same_seed_is_reproducible() -> None:
    selector = VoiceSelector()
    project_id = uuid4()
    kwargs = dict(
        project_id=project_id,
        provider="fake",
        model="fake",
        voices=_voices(),
        constraints=VoiceConstraints(language="zh-CN"),
        mode=RandomMode.RANDOM_ALL,
        seed=123,
        capabilities=SpeechProviderCapabilities(speed_control=True),
    )
    first = selector.select(**kwargs)
    second = selector.select(**kwargs)
    assert first.voice_id == second.voice_id
    assert first.speed == second.speed
```

Also test empty eligible pool raises `SpeechConfigurationError`; `RANDOM_PARAMETERS` preserves supplied `voice_id`; unsupported controls remain unset; locked profile reuse returns the exact persisted configuration.

- [ ] **Step 2: Run RED**

Run: `pytest tests/speech/test_voice_selector.py -v`
Expected: FAIL because `clipatlas.speech.voices` does not exist.

- [ ] **Step 3: Implement deterministic selection**

Use `random.Random(seed)`. Sort the eligible pool by `(provider, voice_id)` before selection. Parameter randomization may only touch capability-enabled controls.

- [ ] **Step 4: Run GREEN**

Run: `pytest tests/speech/test_voice_selector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clipatlas/speech/voices.py tests/speech/test_voice_selector.py
git commit -m "feat: add deterministic voice selection"
```

---

### Task 3: Narration SQLite store with version history and unit checkpoints

**Files:**
- Create: `clipatlas/speech/store.py`
- Test: `tests/speech/test_narration_store.py`

**Interfaces:**
- Produces `NarrationStore(db_path)`.
- Methods: `save_profile`, `get_profile`, `get_latest_locked_profile`, `save_track`, `save_unit`, `save_word_timings`, `get_track`, `list_units`, `list_word_timings`, `activate_track`, `get_active_track`, `next_track_revision`, `get_completed_unit`.

- [ ] **Step 1: Write failing persistence/version tests**

Cover profile/track persistence across reopen, multiple revisions without overwrite, active pointer changes without deletion, unit checkpoint recovery, ordered word timings, and old-track retrieval after activation changes.

- [ ] **Step 2: Run RED**

Run: `pytest tests/speech/test_narration_store.py -v`
Expected: FAIL because store does not exist.

- [ ] **Step 3: Implement SQLite schema and transactions**

Use tables `speech_profiles`, `narration_tracks`, `narration_units`, `narration_word_timings`, `active_narration_tracks`. Use foreign keys and unique constraints for `(track_id, sequence)` and `(project_id)` active pointer. Serialize enum/list metadata as JSON. Never delete old revisions in normal operations.

- [ ] **Step 4: Run GREEN**

Run:
```bash
ruff check clipatlas/speech/store.py tests/speech/test_narration_store.py
mypy clipatlas/speech/store.py
pytest tests/speech/test_narration_store.py -v
```

- [ ] **Step 5: Commit**

```bash
git add clipatlas/speech/store.py tests/speech/test_narration_store.py
git commit -m "feat: persist narration revisions and checkpoints"
```

---

### Task 4: Canonical audio normalization, duration probe, and concatenation

**Files:**
- Create: `clipatlas/speech/audio.py`
- Test: `tests/speech/test_audio.py`

**Interfaces:**
- Consumes existing `AsyncCommandRunner` / `SubprocessCommandRunner`.
- Produces `AudioNormalizer.normalize(source, destination, sample_rate=48000) -> Path`, `probe_duration_ms(path) -> int`, `concat(inputs, destination) -> Path`.

- [ ] **Step 1: Write RED using a recording fake command runner**

Assert normalization argv uses `ffmpeg -y -i <source> -ar 48000 -c:a pcm_s16le <destination>`. Assert ffprobe seconds convert to integer milliseconds. Assert concat rejects missing inputs and nonzero commands raise `SpeechAudioValidationError`.

- [ ] **Step 2: Run RED**

Run: `pytest tests/speech/test_audio.py -v`
Expected: FAIL because `clipatlas.speech.audio` does not exist.

- [ ] **Step 3: Implement using existing command runner contract**

Never invoke shell strings. Ensure destination parents exist. Generate concat manifest only inside ClipAtlas-controlled output directory.

- [ ] **Step 4: Run GREEN**

Run: `pytest tests/speech/test_audio.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clipatlas/speech/audio.py tests/speech/test_audio.py
git commit -m "feat: add canonical narration audio pipeline"
```

---

### Task 5: Fake SpeechProvider and capability-safe parameter filtering

**Files:**
- Create: `clipatlas/speech/fake.py`
- Create: `clipatlas/speech/request_policy.py`
- Test: `tests/speech/test_fake_provider.py`
- Test: `tests/speech/test_request_policy.py`

**Interfaces:**
- Produces deterministic `FakeSpeechProvider`.
- Produces `filter_supported_controls(request, capabilities)` used by real providers.

- [ ] **Step 1: Write RED**

Test deterministic valid WAV output for same request. Test unsupported `pitch/emotion/instruction` are removed while supported `speed` remains.

- [ ] **Step 2: Run RED**

Run: `pytest tests/speech/test_fake_provider.py tests/speech/test_request_policy.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Generate a tiny valid PCM WAV using standard-library `wave` + `BytesIO`; do not add audio synthesis dependencies.

- [ ] **Step 4: Run GREEN and commit**

```bash
pytest tests/speech/test_fake_provider.py tests/speech/test_request_policy.py -v
git add clipatlas/speech/fake.py clipatlas/speech/request_policy.py tests/speech/test_fake_provider.py tests/speech/test_request_policy.py
git commit -m "feat: add fake speech provider"
```

---

### Task 6: DashScope / CosyVoice provider adapter

**Files:**
- Create: `clipatlas/speech/dashscope.py`
- Test: `tests/speech/test_dashscope_provider.py`

**Interfaces:**
- Implements `SpeechProvider`.
- Constructor accepts `api_key`, `model="cosyvoice-v3.5-flash"`, `base_url`, optional `httpx.AsyncClient`.

- [ ] **Step 1: Re-check current official DashScope TTS endpoint immediately before coding**

Use Alibaba Cloud / Model Studio official docs only. Record endpoint/auth/response encoding and model support for voice/speed/pitch/volume/instruction/timestamps. Provider implementation may adapt to current vendor format; core contracts must stay unchanged.

- [ ] **Step 2: Write provider RED with `httpx.MockTransport`**

Cover configured model/voice, supported controls, omission of unsupported controls, official response audio mode, 401/403 auth errors, 429 rate limit, other HTTP/request failures, malformed/empty audio.

- [ ] **Step 3: Run RED**

Run: `pytest tests/speech/test_dashscope_provider.py -v`
Expected: FAIL because provider module does not exist.

- [ ] **Step 4: Implement minimal adapter**

Keep vendor payload parsing inside `dashscope.py`; preserve `raw_payload` and return only canonical `SpeechSynthesisResult` to callers.

- [ ] **Step 5: Run GREEN**

Run:
```bash
ruff check clipatlas/speech/dashscope.py tests/speech/test_dashscope_provider.py
mypy clipatlas/speech/dashscope.py
pytest tests/speech/test_dashscope_provider.py -v
```

- [ ] **Step 6: Commit**

```bash
git add clipatlas/speech/dashscope.py tests/speech/test_dashscope_provider.py
git commit -m "feat: add DashScope speech provider"
```

---

### Task 7: Controlled Generic HTTP and Local HTTP speech providers

**Files:**
- Create: `clipatlas/speech/http_provider.py`
- Test: `tests/speech/test_http_provider.py`

**Interfaces:**
- Produces `HttpSpeechProviderConfig` with endpoint/method/header mappings/field mappings/response mode/timeout/max response bytes.
- Produces `GenericHttpSpeechProvider` and `LocalHttpSpeechProvider`.

- [ ] **Step 1: Write security-first RED**

Test scheme allowlist, local endpoint restrictions, httpx timeout, max response bytes, explicit bytes/base64/URL response modes, bounded remote audio fetch, and declared field mapping only.

- [ ] **Step 2: Run RED**

Run: `pytest tests/speech/test_http_provider.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement controlled HTTP mapping**

No eval, executable templates, or shell. Header values are runtime config/secrets and are not persisted into `SpeechProfile`. Normalize failures into speech errors.

- [ ] **Step 4: Run GREEN and commit**

```bash
pytest tests/speech/test_http_provider.py -v
git add clipatlas/speech/http_provider.py tests/speech/test_http_provider.py
git commit -m "feat: add configurable HTTP speech providers"
```

---

### Task 8: NarrationService unit synthesis, checkpoint resume, and canonical track assembly

**Files:**
- Create: `clipatlas/speech/service.py`
- Test: `tests/speech/test_narration_service.py`

**Interfaces:**
- Produces `NarrationService.create_tts_track(project_id, script, profile) -> NarrationTrack`.
- Produces deterministic `split_narration_units(script) -> list[str]`.
- Depends on `SpeechProvider`, `NarrationStore`, `AudioNormalizer`, narration root.

- [ ] **Step 1: Write RED for exact-time assembly**

With measured durations `[1200, 800, 1500]`, assert unit ranges `0..1200`, `1200..2000`, `2000..3500` and track duration `3500` with `UNIT_EXACT`.

- [ ] **Step 2: Write RED for failure/retry checkpoint**

Provider succeeds Units 0/1 and fails Unit 2 once. Retry must not call provider for Units 0/1 again.

- [ ] **Step 3: Write RED for versioning and script hash**

Changing script creates a new Track revision. Regenerating the same script/profile also creates a new Track revision and never overwrites the old Track.

- [ ] **Step 4: Run RED**

Run: `pytest tests/speech/test_narration_service.py -v`
Expected: FAIL.

- [ ] **Step 5: Implement service**

Flow: split script -> create Track revision -> synthesize/checkpoint each Unit -> write provider audio to controlled file -> normalize -> probe each Unit -> concat -> probe final Track -> save cumulative timings -> save optional word timings offset by Unit start -> activate only after full success.

If final concat duration differs by boundary rounding, canonical Track uses probed final duration and final Unit `end_ms` is adjusted to equal Track duration while keeping monotonic ranges.

- [ ] **Step 6: Run GREEN**

Run:
```bash
ruff check clipatlas/speech tests/speech
mypy clipatlas/speech
pytest tests/speech -v
```

- [ ] **Step 7: Commit**

```bash
git add clipatlas/speech/service.py tests/speech/test_narration_service.py
git commit -m "feat: generate resumable narration tracks"
```

---

### Task 9: Imported narration and alignment-quality boundary

**Files:**
- Create: `clipatlas/speech/importer.py`
- Create: `clipatlas/speech/alignment.py`
- Test: `tests/speech/test_imported_narration.py`

**Interfaces:**
- `AlignmentProvider` returns optional unit/word timings.
- `ImportedNarrationService.import_track(project_id, source_path, script, aligner=None) -> NarrationTrack`.

- [ ] **Step 1: Write RED for no-aligner behavior**

Assert real normalized duration, `source_mode=IMPORTED`, `timing_quality=TRACK_ONLY`, and no fabricated exact Unit timestamps.

- [ ] **Step 2: Write RED for aligner behavior**

Fake aligner ranges must persist as `ALIGNED`, be monotonic and within Track duration. Invalid overlapping/out-of-range data raises `SpeechAudioValidationError`.

- [ ] **Step 3: Run RED**

Run: `pytest tests/speech/test_imported_narration.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement importer/alignment boundary**

Original input remains read-only. Canonical WAV is ClipAtlas-owned. Optional original copy lives only under the controlled narration root.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest tests/speech/test_imported_narration.py -v
git add clipatlas/speech/importer.py clipatlas/speech/alignment.py tests/speech/test_imported_narration.py
git commit -m "feat: import authoritative narration audio"
```

---

### Task 10: Speech registry and runtime configuration

**Files:**
- Create: `clipatlas/speech/registry.py`
- Modify: `clipatlas/app_state.py`
- Modify: `.env.example`
- Test: `tests/speech/test_registry.py`
- Test: `tests/test_speech_app_state.py`

**Interfaces:**
- Produces `SpeechProviderRegistry.register/get/list_descriptors`.
- Runtime builds `NarrationStore`, `AudioNormalizer`, `NarrationService`, `ImportedNarrationService`.
- Env: `CLIPATLAS_NARRATION_ROOT`, `CLIPATLAS_SPEECH_PROVIDER`, `CLIPATLAS_SPEECH_API_KEY`, `CLIPATLAS_SPEECH_BASE_URL`, `CLIPATLAS_SPEECH_MODEL`, `CLIPATLAS_SPEECH_WORKSPACE_ID`, `CLIPATLAS_ENABLE_FAKE_SPEECH_PROVIDER`.
- `CLIPATLAS_SPEECH_API_KEY` falls back to `DASHSCOPE_API_KEY`.

- [ ] **Step 1: Write RED**

Test duplicate provider rejection, DashScope registration only with key, fake provider toggle, startup without real key, and persisted NarrationStore runtime.

- [ ] **Step 2: Run RED**

Run: `pytest tests/speech/test_registry.py tests/test_speech_app_state.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement runtime**

Keep video and speech provider registries separate. Expose `app.state.speech_registry`, `app.state.narration_service`, `app.state.imported_narration_service`, `app.state.narration_store`.

- [ ] **Step 4: Run GREEN and commit**

```bash
pytest tests/speech/test_registry.py tests/test_speech_app_state.py -v
git add clipatlas/speech/registry.py clipatlas/app_state.py .env.example tests/speech/test_registry.py tests/test_speech_app_state.py
git commit -m "feat: wire narration runtime"
```

---

### Task 11: Narration and voice API

**Files:**
- Create: `clipatlas/api/routes/speech.py`
- Modify: `clipatlas/main.py`
- Test: `tests/api/test_speech.py`

**Interfaces:**
- `GET /api/v1/speech/providers`
- `GET /api/v1/speech/providers/{provider}/voices`
- `POST /api/v1/speech/profiles/randomize`
- `POST /api/v1/narration/tts`
- `POST /api/v1/narration/import`
- `GET /api/v1/narration/{track_id}`
- `POST /api/v1/narration/{track_id}/activate`

- [ ] **Step 1: Write API RED**

Test provider/voice listing, constrained randomization, deterministic seed, TTS duration/units, imported `TRACK_ONLY`, stable 404 for unknown provider/track, and validation errors.

- [ ] **Step 2: Run RED**

Run: `pytest tests/api/test_speech.py -v`
Expected: FAIL/404 because router is absent.

- [ ] **Step 3: Implement thin router**

Delegate to services. Do not put provider or FFmpeg logic in routes. Imported multipart audio uses controlled narration storage, never arbitrary client write paths.

- [ ] **Step 4: Run GREEN and commit**

```bash
pytest tests/api/test_speech.py -v
git add clipatlas/api/routes/speech.py clipatlas/main.py tests/api/test_speech.py
git commit -m "feat: expose narration and voice API"
```

---

### Task 12: Documentation, full verification, and RoughCut handoff contract

**Files:**
- Modify: `README.md`
- Create: `docs/narration-tts-v0.1.md`
- Test: `tests/speech/test_roughcut_handoff.py`

**Interfaces:**
- Verifies active `NarrationTrack`, ordered exact `NarrationUnit` windows, optional words for the next Script Beat/RoughCut subsystem.

- [ ] **Step 1: Write handoff test**

Create a completed TTS track and assert active track duration equals final Unit end, first Unit begins at 0, and every adjacent Unit is contiguous.

- [ ] **Step 2: Update Chinese-first docs**

Document current chain `本地素材 -> 语义索引/检索` and `文案 -> TTS/导入旁白 -> 真实时间轴`, plus next chain `NarrationUnit -> Script Beat -> Top-K 素材 -> rerank -> RoughCutPlan -> OTIO -> 剪映草稿`.

- [ ] **Step 3: Run final full verification**

Run:
```bash
ruff check .
mypy clipatlas
pytest -v
```
Expected: zero Ruff errors, zero Mypy errors, zero Pytest failures.

- [ ] **Step 4: Review spec coverage**

Verify DashScope, Generic HTTP, Local HTTP, imported audio boundary, checkpoint resume, random seed/project lock, active Track semantics, capabilities filtering, and exact measured timing are all implemented.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/narration-tts-v0.1.md tests/speech/test_roughcut_handoff.py
git commit -m "docs: complete narration TTS v0.1"
```
