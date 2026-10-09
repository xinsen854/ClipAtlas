from clipatlas.library.models import LibraryItem, LibraryItemStatus
from finecut.models import MediaReference


def media_reference(item: LibraryItem) -> MediaReference | None:
    if item.video_id is None or item.status in {LibraryItemStatus.MISSING, LibraryItemStatus.FAILED}:
        return None
    return MediaReference(media_id=item.video_id, source_uri=item.source_path)
