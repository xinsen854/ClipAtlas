from pathlib import Path

from clipatlas.catalog.store import CatalogStore
from clipatlas.retrieval.hybrid import build_hybrid_search_service


def test_hybrid_builder_uses_existing_library_database_and_allows_text_only_mode(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "library.sqlite3"
    catalog = CatalogStore(db_path)

    service = build_hybrid_search_service(
        catalog=catalog,
        visual_service=None,
        db_path=db_path,
    )

    assert service._asr_store._db_path == db_path.resolve()
    assert service._ocr_store._db_path == db_path.resolve()
    assert service._visual is None
