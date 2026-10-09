from pathlib import Path
from uuid import uuid4

from clipatlas.app_state import build_narration_runtime, build_speech_provider_registry
from clipatlas.main import create_app
from clipatlas.speech.fake import FakeSpeechProvider
from clipatlas.speech.models import SpeechProfile
from clipatlas.speech.registry import SpeechProviderRegistry


def _clear_speech_env(monkeypatch: object) -> None:
    for name in (
        "CLIPATLAS_SPEECH_API_KEY",
        "DASHSCOPE_API_KEY",
        "CLIPATLAS_SPEECH_BASE_URL",
        "CLIPATLAS_SPEECH_MODEL",
        "CLIPATLAS_SPEECH_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)


def test_speech_registry_fake_toggle_and_dashscope_key_registration(monkeypatch: object) -> None:
    _clear_speech_env(monkeypatch)
    monkeypatch.setenv("CLIPATLAS_ENABLE_FAKE_SPEECH_PROVIDER", "false")

    assert build_speech_provider_registry().list_descriptors() == []

    monkeypatch.setenv("CLIPATLAS_ENABLE_FAKE_SPEECH_PROVIDER", "true")
    assert [item.name for item in build_speech_provider_registry().list_descriptors()] == ["fake"]

    monkeypatch.setenv("CLIPATLAS_ENABLE_FAKE_SPEECH_PROVIDER", "false")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fallback-secret")
    descriptors = build_speech_provider_registry().list_descriptors()
    assert [item.name for item in descriptors] == ["dashscope"]
    assert descriptors[0].model == "cosyvoice-v3.5-flash"


def test_narration_runtime_reuses_persisted_store_and_selected_provider(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    root = tmp_path / "narration"
    monkeypatch.setenv("CLIPATLAS_NARRATION_ROOT", str(root))
    monkeypatch.setenv("CLIPATLAS_SPEECH_PROVIDER", "fake")
    registry = SpeechProviderRegistry()
    registry.register(FakeSpeechProvider())

    first = build_narration_runtime(registry)
    project_id = uuid4()
    profile = SpeechProfile(
        project_id=project_id,
        provider="fake",
        model="fake-tts-v0.1",
        voice_id="fake-female",
        locked=True,
    )
    first.store.save_profile(profile)

    second = build_narration_runtime(registry)

    assert second.store.get_profile(profile.id) == profile
    assert second.narration_service is not None
    assert second.imported_narration_service is not None
    assert second.audio_normalizer is not None


def test_app_exposes_speech_runtime_without_real_api_key(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    _clear_speech_env(monkeypatch)
    monkeypatch.setenv("CLIPATLAS_ENABLE_FAKE_SPEECH_PROVIDER", "true")
    monkeypatch.setenv("CLIPATLAS_NARRATION_ROOT", str(tmp_path / "narration"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "library-cache"))
    monkeypatch.setenv("CLIPATLAS_VIDEO_ROOT", str(tmp_path / "videos"))

    app = create_app()

    assert app.state.speech_registry.get("fake").name == "fake"
    assert app.state.narration_store is not None
    assert app.state.narration_service is not None
    assert app.state.imported_narration_service is not None
