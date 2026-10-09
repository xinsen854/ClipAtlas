from uuid import uuid4

import pytest

from clipatlas.integrations.finecut.media_bridge import media_reference
from clipatlas.library.models import LibraryItem, LibraryItemStatus


def _item(*, status: LibraryItemStatus, with_video_id: bool = True) -> LibraryItem:
    return LibraryItem(
        root_id=uuid4(),
        source_path="D:/media/source.mp4",
        size_bytes=123,
        mtime_ns=456,
        fingerprint="fingerprint",
        status=status,
        video_id=uuid4() if with_video_id else None,
    )


def test_media_bridge_exposes_only_media_id_and_source_uri() -> None:
    item = _item(status=LibraryItemStatus.COMPLETED)

    result = media_reference(item)

    assert result is not None
    assert result.media_id == item.video_id
    assert result.source_uri == item.source_path
    assert set(result.model_dump()) == {"media_id", "source_uri"}


@pytest.mark.parametrize("status", [LibraryItemStatus.MISSING, LibraryItemStatus.FAILED])
def test_media_bridge_hides_missing_or_failed_items(status: LibraryItemStatus) -> None:
    assert media_reference(_item(status=status)) is None


def test_media_bridge_hides_item_without_video_id() -> None:
    assert media_reference(_item(status=LibraryItemStatus.COMPLETED, with_video_id=False)) is None


def test_media_bridge_does_not_invent_completed_only_policy() -> None:
    result = media_reference(_item(status=LibraryItemStatus.PROBING))

    assert result is not None
