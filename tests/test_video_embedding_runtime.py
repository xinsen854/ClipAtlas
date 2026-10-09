from pathlib import Path

import clipatlas.app_state as app_state_module
import clipatlas.main as main_module
from clipatlas.embeddings.contracts import EmbeddingVector


class _FakeVideoEmbeddingProvider:
    name = "qwen-vl-video"
    model = "qwen3-vl-embedding"
    effective_dimensions = 2560

    async def embed_query(self, text: str) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0] + [0.0] * 2559)

    async def embed_video(self, video_path: Path) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0] + [0.0] * 2559)


def test_app_shares_one_video_embedding_provider_between_index_and_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "one-video-key")
    monkeypatch.setenv("CLIPATLAS_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPATLAS_PROJECT_DB", str(tmp_path / "projects.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "library-cache"))
    monkeypatch.setenv("CLIPATLAS_VIDEO_ROOT", str(tmp_path / "videos"))
    monkeypatch.setenv("CLIPATLAS_NARRATION_ROOT", str(tmp_path / "narration"))
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(tmp_path / "roughcut.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.setenv("CLIPATLAS_FRONTEND_DIST", str(tmp_path / "frontend-dist"))
    created: list[_FakeVideoEmbeddingProvider] = []

    def fake_provider(
        *,
        api_key: str,
        base_http_api_url: str,
    ) -> _FakeVideoEmbeddingProvider:
        assert api_key == "one-video-key"
        assert base_http_api_url == "https://dashscope.aliyuncs.com/api/v1"
        provider = _FakeVideoEmbeddingProvider()
        created.append(provider)
        return provider

    monkeypatch.setattr(app_state_module, "QwenVLVideoEmbeddingProvider", fake_provider)

    app = main_module.create_app()

    assert len(created) == 1
    assert app.state.video_embedding_provider is created[0]
    assert app.state.library_worker.video_indexer is not None
    assert app.state.library_worker.video_indexer._provider is created[0]
    assert app.state.video_chunk_search_service is not None
    assert app.state.video_chunk_search_service._provider is created[0]
