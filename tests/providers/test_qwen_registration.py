from pathlib import Path

from clipatlas.app_state import build_provider_registry
from clipatlas.providers.qwen import QwenVideoUnderstandingProvider


def test_build_provider_registry_registers_qwen_when_api_key_is_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_ENABLE_FAKE_PROVIDER", "false")
    monkeypatch.setenv("CLIPATLAS_QWEN_API_KEY", "test-key")
    monkeypatch.setenv("CLIPATLAS_QWEN_BASE_URL", "https://example.test/compatible-mode/v1")
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.delenv("CLIPATLAS_QWEN_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("CLIPATLAS_QWEN_LONG_CONTEXT_MODEL", raising=False)

    registry = build_provider_registry()

    provider = registry.get("qwen")
    assert isinstance(provider, QwenVideoUnderstandingProvider)
    assert provider.capabilities.image_input is True
    assert provider._default_model == "qwen3.8-flash"
    assert provider._long_context_model == "qwen3.8-flash"
    assert [item.name for item in registry.list_descriptors()] == ["qwen"]


def test_build_provider_registry_accepts_dashscope_key_and_skips_qwen_without_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_ENABLE_FAKE_PROVIDER", "false")
    monkeypatch.delenv("CLIPATLAS_QWEN_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    with_dashscope = build_provider_registry()
    assert isinstance(with_dashscope.get("qwen"), QwenVideoUnderstandingProvider)

    monkeypatch.delenv("DASHSCOPE_API_KEY")
    without_key = build_provider_registry()
    assert without_key.list_descriptors() == []
