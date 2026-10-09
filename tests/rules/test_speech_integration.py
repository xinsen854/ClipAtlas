from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.rules.models import ProjectRule, RuleKind
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.errors import SpeechRequestError
from clipatlas.speech.models import (
    SpeechProfile,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
)
from clipatlas.speech.service import NarrationService
from clipatlas.speech.store import NarrationStore


class RecordingSpeechProvider:
    name = "recording"
    model = "recording-v1"
    capabilities = SpeechProviderCapabilities()

    def __init__(self, *, fail_text_once: str | None = None) -> None:
        self.calls: list[str] = []
        self._fail_text_once = fail_text_once
        self._failed = False

    async def list_voices(self) -> list[object]:
        return []

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        self.calls.append(request.text)
        if request.text == self._fail_text_once and not self._failed:
            self._failed = True
            raise SpeechRequestError("temporary synthesis failure")
        return SpeechSynthesisResult(
            provider=self.name,
            model=self.model,
            audio_bytes=request.text.encode(),
            output_format="wav",
            sample_rate=48_000,
        )


class FixedAudioNormalizer:
    def __init__(self) -> None:
        self._durations: dict[Path, int] = {}

    async def normalize(
        self,
        source: Path,
        destination: Path,
        sample_rate: int = 48_000,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        self._durations[destination] = 1000
        return destination

    async def probe_duration_ms(self, source: Path) -> int:
        return self._durations[source]

    async def concat(self, inputs: list[Path], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"".join(path.read_bytes() for path in inputs))
        self._durations[destination] = sum(self._durations[path] for path in inputs)
        return destination


def _profile(project_id: UUID) -> SpeechProfile:
    return SpeechProfile(
        project_id=project_id,
        provider="recording",
        model="recording-v1",
        voice_id="voice-1",
        locked=True,
    )


def _service(tmp_path: Path, project_rule_store: ProjectRuleStore, provider: RecordingSpeechProvider):
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    service = NarrationService(
        provider=provider,
        store=narration_store,
        audio_normalizer=FixedAudioNormalizer(),
        narration_root=tmp_path / "narration",
        rule_store=project_rule_store,
    )
    return service, narration_store


@pytest.mark.asyncio
async def test_active_rules_change_tts_input_but_preserve_canonical_unit_text(tmp_path: Path) -> None:
    project_id = uuid4()
    rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")
    draft = rule_store.save_draft(
        project_id,
        [
            ProjectRule(kind=RuleKind.SPEECH_SUPPRESS, match="Official Media "),
            ProjectRule(
                kind=RuleKind.PRONUNCIATION,
                match="Model 700",
                replacement="Model seven hundred",
            ),
        ],
    )
    rule_store.activate(project_id, draft.revision)

    provider = RecordingSpeechProvider()
    service, narration_store = _service(tmp_path, rule_store, provider)
    source = "Official Media presents Model 700 today."

    track = await service.create_tts_track(project_id, source, _profile(project_id))

    assert provider.calls == ["presents Model seven hundred today."]
    units = narration_store.list_units(track.id)
    assert [unit.text for unit in units] == [source]
    assert units[0].text_hash == sha256(source.encode()).hexdigest()


@pytest.mark.asyncio
async def test_draft_rules_do_not_change_tts_input(tmp_path: Path) -> None:
    project_id = uuid4()
    rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")
    rule_store.save_draft(
        project_id,
        [
            ProjectRule(
                kind=RuleKind.PRONUNCIATION,
                match="Model 700",
                replacement="Model seven hundred",
            )
        ],
    )

    provider = RecordingSpeechProvider()
    service, _ = _service(tmp_path, rule_store, provider)
    source = "Model 700 is ready."

    await service.create_tts_track(project_id, source, _profile(project_id))

    assert provider.calls == [source]


@pytest.mark.asyncio
async def test_active_rules_are_isolated_by_project_for_tts(tmp_path: Path) -> None:
    project_a = uuid4()
    project_b = uuid4()
    rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")
    draft = rule_store.save_draft(
        project_a,
        [
            ProjectRule(
                kind=RuleKind.PRONUNCIATION,
                match="Model 700",
                replacement="Model seven hundred",
            )
        ],
    )
    rule_store.activate(project_a, draft.revision)

    provider = RecordingSpeechProvider()
    service, _ = _service(tmp_path, rule_store, provider)
    source = "Model 700 is ready."

    await service.create_tts_track(project_b, source, _profile(project_b))

    assert provider.calls == [source]


@pytest.mark.asyncio
async def test_rule_revision_change_does_not_reuse_incomplete_tts_checkpoint(tmp_path: Path) -> None:
    project_id = uuid4()
    profile = _profile(project_id)
    source = "Model 700 intro.\nSecond line."
    rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")

    first_pack = rule_store.save_draft(
        project_id,
        [
            ProjectRule(
                kind=RuleKind.PRONUNCIATION,
                match="Model 700",
                replacement="Model seven hundred",
            )
        ],
    )
    rule_store.activate(project_id, first_pack.revision)

    first_provider = RecordingSpeechProvider(fail_text_once="Second line.")
    first_service, first_narration_store = _service(tmp_path, rule_store, first_provider)

    with pytest.raises(SpeechRequestError, match="temporary synthesis failure"):
        await first_service.create_tts_track(project_id, source, profile)

    old_tracks = first_narration_store.list_tracks(project_id)
    assert len(old_tracks) == 1
    old_track = old_tracks[0]
    assert [unit.text for unit in first_narration_store.list_units(old_track.id)] == [
        "Model 700 intro."
    ]

    second_pack = rule_store.save_draft(
        project_id,
        [
            ProjectRule(
                kind=RuleKind.PRONUNCIATION,
                match="Model 700",
                replacement="Model seven zero zero",
            )
        ],
    )
    rule_store.activate(project_id, second_pack.revision)

    second_provider = RecordingSpeechProvider()
    second_service, second_narration_store = _service(tmp_path, rule_store, second_provider)
    new_track = await second_service.create_tts_track(project_id, source, profile)

    assert new_track.id != old_track.id
    assert second_provider.calls == ["Model seven zero zero intro.", "Second line."]
    assert [unit.text for unit in second_narration_store.list_units(new_track.id)] == [
        "Model 700 intro.",
        "Second line.",
    ]
