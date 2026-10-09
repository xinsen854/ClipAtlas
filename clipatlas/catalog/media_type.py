"""Material-ingest media type annotation (one of the two allowed API call sites).

Classifies each catalog segment's representative frame into a media type so the
rough-cut retriever can keep title cards / posters out of the edit timeline.

API usage: one call per segment at ingest time (or on demand via the CLI).
The editing stage never calls this; it only reads the persisted table.

Classification uses the frame's primary narrative content. A presenter beside
a dominant presentation screen does not turn the screen content into a scene.
"""

import asyncio
import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from clipatlas.catalog.store import CatalogStore
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)

DEFAULT_MODEL = "qwen3.8-flash"
MEDIA_TYPE_PROMPT_VERSION = "media-type-v3-primary-content"

# Subject media values that must never enter the edit timeline by default.
TITLE_CARD = "title_card"
NON_EDITABLE = {TITLE_CARD, "technical_chart", "screen_capture"}

_MEDIA_TYPE_SYSTEM_PROMPT = (
    "You are the ingest annotation layer of an automatic rough-cut system. "
    "You look at ONE video frame and decide whether it is editable narrative "
    "footage or a title card that should be kept out of the edit. "
    "Output ONLY a single JSON object with this exact shape: "
    '{"subject_medium": "...", "text_ratio": 0.0, "text_block_count": 0, '
    '"has_real_subject": true, "reason": "..."}.\n'
    "subject_medium must be exactly one of:\n"
    '- "title_card": the frame itself is text/poster (black-background white-text '
    "promo card, centred big headline, full-screen text poster, vertical banner / "
    "promo image with stacked text blocks and no real scene) - NOT editable\n"
    '- "scene": real narrative footage with a real subject (person, vehicle, road, '
    "mountain, stage, object); text is only overlaid info - editable\n"
    '- "technical_chart": technical diagram / chart (structure drawing, route map, '
    "data chart)\n"
    '- "screen_capture": screen / big-screen display (event screen, car head unit)\n'
    '- "cg": 3D render / CG footage\n'
    "Classification rules, in order:\n"
    "1. Text/poster occupies most of the frame (>=60%), or the frame is a full "
    "black-background white-text card, or a vertical banner/promo image whose main "
    "content is stacked text -> title_card.\n"
    "2. A display/chart/screen occupying most of the frame or carrying the primary "
    "claim -> screen_capture or technical_chart, even when a presenter is also visible.\n"
    "3. A filmed person/vehicle/road/mountain is the primary content and any text/screen "
    "is supporting -> scene.\n"
    "4. Solid or black background with a centred big headline -> title_card.\n"
    "5. Real footage with small corner/top text -> scene.\n"
    "text_ratio: estimated fraction of the frame covered by ALL text (0.0 to 1.0). "
    "Small corner logos/watermarks count as ~0.02-0.08; a huge headline band counts "
    "0.3-0.5; a full text poster counts >=0.6.\n"
    "text_block_count: the number of SEPARATE text blocks/regions in the frame "
    "(corner logo=1, headline+subtitle+footer=3, a dense 4+ region text poster=4+).\n"
    "has_real_subject: whether a real filmed subject exists in the frame.\n"
    "No prose before or after the JSON."
)

_DATA_URI_PREFIX = "data:image/jpeg;base64,"
_MAX_DATA_URI_BYTES = 10_000_000


class MediaTypeResult(BaseModel):
    # AI 结构化输出偶会附带未要求的附加字段，忽略多余字段而不是让整段画面类型标注失败。
    model_config = ConfigDict(extra="ignore")

    subject_medium: str
    text_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    text_block_count: int = Field(default=0, ge=0)
    has_real_subject: bool = True
    reason: str = ""


def is_editable(medium: str) -> bool:
    """True when the annotated medium may enter the edit timeline."""
    return medium not in NON_EDITABLE


class MediaTypeAnalyzer:
    """OpenAI-compatible visual classifier; one call per segment frame."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = DEFAULT_MODEL,
        prompt_version: str = MEDIA_TYPE_PROMPT_VERSION,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key is required")
        if not base_url.strip():
            raise ValueError("base_url is required")
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()
        self._prompt_version = prompt_version
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def classify(self, image_path: Path) -> MediaTypeResult:
        image_path = image_path.resolve()
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        raw_size = image_path.stat().st_size
        encoded_size = 4 * ((raw_size + 2) // 3) + len(_DATA_URI_PREFIX)
        if encoded_size > _MAX_DATA_URI_BYTES:
            raise ProviderRequestError("media type image exceeds the 10 MB API limit")
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload: dict[str, Any] = {
            "model": self._model,
            "enable_thinking": False,
            "messages": [
                {"role": "system", "content": _MEDIA_TYPE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"{_DATA_URI_PREFIX}{encoded}",
                            },
                        },
                        {"type": "text", "text": "Classify this frame."},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }
        if self._client is not None:
            content = await self._post_content(self._client, payload)
        else:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                content = await self._post_content(client, payload)
        try:
            decoded = json.loads(content)
        except ValueError as exc:
            raise ProviderRequestError("Media type analyzer returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ProviderRequestError("Media type analyzer returned invalid structured output")
        try:
            return MediaTypeResult.model_validate(decoded)
        except Exception as exc:  # pydantic.ValidationError
            raise ProviderRequestError(
                "Media type analyzer returned invalid structured output"
            ) from exc

    async def _post_content(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> str:
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise ProviderRequestError("Media type analyzer upstream request failed") from exc
        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError(
                f"Media type analyzer upstream returned HTTP {response.status_code}"
            )
        if response.status_code == 429:
            raise ProviderRateLimitError("Media type analyzer upstream returned HTTP 429")
        if response.is_error:
            raise ProviderRequestError(
                f"Media type analyzer upstream returned HTTP {response.status_code}"
            )
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderRequestError("Media type analyzer returned an invalid response payload") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("Media type analyzer returned an invalid response payload")
        return content


def _representative_frame(store: CatalogStore, segment_id: UUID) -> Path | None:
    """Middle frame of a segment, if frames were persisted."""
    with store._connect() as connection:
        rows = connection.execute(
            "SELECT uri FROM catalog_segment_frames WHERE segment_id = ? ORDER BY ordinal",
            (str(segment_id),),
        ).fetchall()
    if not rows:
        return None
    mid = len(rows) // 2
    return _uri_to_path(rows[mid]["uri"])


def _uri_to_path(uri: str) -> Path:
    """Turn a stored frame URI (file:///D:/...) into a usable local Path."""
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        path_text = unquote(parsed.path)
        if (
            len(path_text) >= 3
            and path_text[0] == "/"
            and path_text[1].isalpha()
            and path_text[2] == ":"
        ):
            path_text = path_text[1:]
        return Path(path_text)
    return Path(uri)


async def annotate_video(
    store: CatalogStore,
    analyzer: MediaTypeAnalyzer,
    video_id: UUID,
    *,
    force: bool = False,
    limit: int | None = None,
    concurrency: int = 2,
) -> dict[str, int]:
    """Annotate every segment of one video. Returns per-medium counts."""
    segments = store.list_segments(video_id, limit=limit or 100_000, offset=0)
    counts: dict[str, int] = {}
    done = 0
    sem = asyncio.Semaphore(max(1, concurrency))

    async def process_segment(segment) -> None:
        nonlocal done
        async with sem:
            if not force and store.get_segment_media_type(segment.id) is not None:
                return
            frame = _representative_frame(store, segment.id)
            if frame is None or not frame.is_file():
                return
            try:
                result = await analyzer.classify(frame)
            except ProviderRequestError:
                return
            store.save_segment_media_type(
                segment_id=segment.id,
                subject_medium=result.subject_medium,
                text_ratio=result.text_ratio,
                text_block_count=result.text_block_count,
                has_real_subject=result.has_real_subject,
                basis=f"{analyzer._model} {analyzer._prompt_version}",
            )
            counts[result.subject_medium] = counts.get(result.subject_medium, 0) + 1
            done += 1

    await asyncio.gather(*(process_segment(seg) for seg in segments))
    counts["_annotated"] = done
    return counts


async def annotate_library(
    store: CatalogStore,
    analyzer: MediaTypeAnalyzer,
    *,
    force: bool = False,
    video_limit: int | None = None,
) -> dict[str, int]:
    """Annotate all videos in the catalog. Returns per-medium counts."""
    video_ids = store.list_video_ids(limit=video_limit or 100_000, offset=0)
    totals: dict[str, int] = {}
    for video_id in video_ids:
        counts = await annotate_video(store, analyzer, video_id, force=force)
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    return totals


def run_cli() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Annotate catalog segments with media types")
    parser.add_argument("--library-db", default=None, help="catalog sqlite path")
    parser.add_argument("--video-id", default=None, help="annotate only this video")
    parser.add_argument("--force", action="store_true", help="re-annotate existing rows")
    parser.add_argument("--limit", type=int, default=None, help="max segments per video")
    args = parser.parse_args()

    library_db = Path(args.library_db or os.getenv("CLIPATLAS_LIBRARY_DB", "./data/library/library.sqlite3"))
    api_key = os.getenv("CLIPATLAS_BAILIAN_API_KEY", "").strip()
    base_url = os.getenv("CLIPATLAS_BAILIAN_BASE_URL", "").strip()
    if not api_key or not base_url:
        raise SystemExit("CLIPATLAS_BAILIAN_API_KEY / CLIPATLAS_BAILIAN_BASE_URL are required")

    from clipatlas.settings.bailian import derive_bailian_endpoints

    endpoints = derive_bailian_endpoints(base_url)
    store = CatalogStore(library_db)
    analyzer = MediaTypeAnalyzer(api_key=api_key, base_url=endpoints.openai_compatible)
    if args.video_id:
        counts = asyncio.run(annotate_video(
            store, analyzer, UUID(args.video_id), force=args.force, limit=args.limit,
        ))
    else:
        counts = asyncio.run(annotate_library(store, analyzer, force=args.force))
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    run_cli()
