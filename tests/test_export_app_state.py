from pathlib import Path

from clipatlas.app_state import ExportRuntime, build_export_runtime
from clipatlas.exports.jianying import PyJianYingDraftBackend
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.store import NarrationStore


def _stores(tmp_path: Path) -> tuple[RoughCutStore, NarrationStore]:
    return (
        RoughCutStore(tmp_path / "roughcut.sqlite3"),
        NarrationStore(tmp_path / "narration.sqlite3"),
    )


def test_export_runtime_always_builds_otio_and_respects_export_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    export_root = tmp_path / "custom-exports"
    monkeypatch.setenv("CLIPATLAS_EXPORT_ROOT", str(export_root))
    monkeypatch.delenv("CLIPATLAS_JIANYING_DRAFT_ROOT", raising=False)
    monkeypatch.setattr("clipatlas.app_state.find_spec", lambda name: None)
    rough_cut_store, narration_store = _stores(tmp_path)

    runtime = build_export_runtime(rough_cut_store, narration_store)

    assert isinstance(runtime, ExportRuntime)
    assert runtime.otio_builder is not None
    assert runtime.service is not None
    assert runtime.service._export_root == export_root.resolve()
    assert runtime.jianying_backend is None


def test_export_runtime_uses_supplied_finecut_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("clipatlas.app_state.find_spec", lambda name: None)
    rough_cut_store, narration_store = _stores(tmp_path)
    finecut_store = object()

    runtime = build_export_runtime(
        rough_cut_store,
        narration_store,
        finecut_timeline_store=finecut_store,
    )

    assert runtime.service._finecut_timeline_store is finecut_store


def test_missing_optional_jianying_dependency_only_disables_backend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(tmp_path / "drafts"))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "portable")
    monkeypatch.setattr("clipatlas.app_state.find_spec", lambda name: None)
    rough_cut_store, narration_store = _stores(tmp_path)

    runtime = build_export_runtime(rough_cut_store, narration_store)

    assert runtime.service is not None
    assert runtime.otio_builder is not None
    assert runtime.jianying_backend is None


def test_complete_portable_configuration_injects_jianying_backend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(tmp_path / "drafts"))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "portable")
    rough_cut_store, narration_store = _stores(tmp_path)

    runtime = build_export_runtime(rough_cut_store, narration_store)

    assert isinstance(runtime.jianying_backend, PyJianYingDraftBackend)


def test_jianying_10_8_missing_local_paths_does_not_disable_otio(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(tmp_path / "drafts"))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "jianying_pro_10_8")
    monkeypatch.delenv("CLIPATLAS_JIANYING_INSTALL_DIR", raising=False)
    monkeypatch.delenv("CLIPATLAS_JIANYING_USER_DATA", raising=False)
    rough_cut_store, narration_store = _stores(tmp_path)

    runtime = build_export_runtime(rough_cut_store, narration_store)

    assert runtime.service is not None
    assert runtime.otio_builder is not None
    assert runtime.jianying_backend is None
