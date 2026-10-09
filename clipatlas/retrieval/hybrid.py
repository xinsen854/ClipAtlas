from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from clipatlas.asr.models import ASRTextMatch
from clipatlas.asr.store import ASRStore
from clipatlas.domain.models import VideoAsset
from clipatlas.ocr.models import OCRTextMatch
from clipatlas.ocr.store import OCRStore
from clipatlas.retrieval.search import CoarseVideoSearchHit
from clipatlas.retrieval.video_profiles import DEFAULT_VIDEO_INDEX_PROFILE, VideoIndexProfile
from clipatlas.retrieval.text_normalization import expand_search_terms

RecallSource = Literal["visual", "asr", "ocr"]

_ASR_PROVIDER = "bailian-asr"
_ASR_MODEL = "qwen-audio-3.0-asr-flash"
_OCR_PROVIDER = "bailian-ocr"
_OCR_MODEL = "qwen3.5-ocr"
_SOURCE_ORDER: tuple[RecallSource, ...] = ("visual", "asr", "ocr")


class HybridSearchHit(BaseModel):
    video_id: UUID
    filename: str
    source_uri: str
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0)
    visual_score: float | None = None
    asr_score: float | None = None
    ocr_score: float | None = None
    sources: list[RecallSource] = Field(default_factory=list)
    asr_texts: list[str] = Field(default_factory=list)
    ocr_texts: list[str] = Field(default_factory=list)


class HybridSearchLike(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[HybridSearchHit]: ...


class CatalogLookupLike(Protocol):
    def get_video(self, video_id: UUID) -> VideoAsset | None: ...


class VisualSearchLike(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
        profile: VideoIndexProfile = ...,
    ) -> list[CoarseVideoSearchHit]: ...


class ASRTextStoreLike(Protocol):
    def search_text(
        self,
        query: str,
        provider: str,
        model: str,
        *,
        limit: int,
        video_ids: list[UUID] | None = None,
    ) -> list[ASRTextMatch]: ...


class OCRTextStoreLike(Protocol):
    def search_text(
        self,
        query: str,
        provider: str,
        model: str,
        *,
        limit: int,
        video_ids: list[UUID] | None = None,
    ) -> list[OCRTextMatch]: ...


@dataclass(slots=True)
class _Candidate:
    video_id: UUID
    filename: str
    source_uri: str
    start_ms: int
    end_ms: int
    visual_score: float | None = None
    asr_score: float | None = None
    ocr_score: float | None = None
    asr_texts: list[str] = field(default_factory=list)
    ocr_texts: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return sum(
            score
            for score in (self.visual_score, self.asr_score, self.ocr_score)
            if score is not None
        )

    def to_hit(self) -> HybridSearchHit:
        present = {
            "visual": self.visual_score is not None,
            "asr": self.asr_score is not None,
            "ocr": self.ocr_score is not None,
        }
        return HybridSearchHit(
            video_id=self.video_id,
            filename=self.filename,
            source_uri=self.source_uri,
            source_start_ms=self.start_ms,
            source_end_ms=self.end_ms,
            score=self.score,
            visual_score=self.visual_score,
            asr_score=self.asr_score,
            ocr_score=self.ocr_score,
            sources=[source for source in _SOURCE_ORDER if present[source]],
            asr_texts=self.asr_texts,
            ocr_texts=self.ocr_texts,
        )


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def text_specificity_score(query: str, text: str) -> float | None:
    normalized_query = _normalize_text(query)
    normalized_text = _normalize_text(text)
    if not normalized_query or not normalized_text:
        return None
    if normalized_query not in normalized_text:
        return None
    return min(1.0, len(normalized_query) / len(normalized_text))


def _visual_score(score: float) -> float:
    return max(0.0, min(1.0, score))


def _max_score(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _append_unique(values: list[str], additions: list[str]) -> None:
    for value in additions:
        if value not in values:
            values.append(value)


class HybridSearchService:
    def __init__(
        self,
        *,
        catalog: CatalogLookupLike,
        visual: VisualSearchLike | None,
        asr_store: ASRTextStoreLike,
        ocr_store: OCRTextStoreLike,
        profile: VideoIndexProfile = DEFAULT_VIDEO_INDEX_PROFILE,
    ) -> None:
        self._catalog = catalog
        self._visual = visual
        self._asr_store = asr_store
        self._ocr_store = ocr_store
        self._profile = profile

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[HybridSearchHit]:
        query = query.strip()
        if not query or limit <= 0:
            return []
        if video_ids is not None and not video_ids:
            return []

        candidates: list[_Candidate] = []
        if self._visual is not None:
            visual_hits = await self._visual.search(
                query,
                limit=limit,
                video_ids=video_ids,
                profile=self._profile,
            )
            candidates.extend(self._from_visual(hit) for hit in visual_hits)

        asr_hits = self._asr_store.search_text(
            query,
            _ASR_PROVIDER,
            _ASR_MODEL,
            limit=limit,
            video_ids=video_ids,
        )
        for hit in asr_hits:
            candidate = self._from_asr(query, hit)
            if candidate is not None:
                candidates.append(candidate)

        ocr_hits = self._ocr_store.search_text(
            query,
            _OCR_PROVIDER,
            _OCR_MODEL,
            limit=limit,
            video_ids=video_ids,
        )
        for ocr_hit in ocr_hits:
            candidate = self._from_ocr(query, ocr_hit)
            if candidate is not None:
                candidates.append(candidate)

        merged = self._merge_candidates(candidates)
        merged.sort(
            key=lambda candidate: (
                -candidate.score,
                str(candidate.video_id),
                candidate.start_ms,
                candidate.end_ms,
            )
        )
        return [candidate.to_hit() for candidate in merged[:limit]]

    async def search_evidence(
        self, *, visual_queries: list[str], keywords: list[str], evidence: str,
        limit: int = 12, video_ids: list[UUID] | None = None,
    ) -> list[HybridSearchHit]:
        """Internal planned recall: route literal keywords separately from visual meaning.

        Reciprocal-rank fusion avoids comparing cosine and substring-specificity scales.
        The public search() behavior is deliberately unchanged.
        """
        if limit <= 0 or video_ids == []:
            return []
        channels: list[tuple[str, list[_Candidate]]] = []
        if self._visual is not None:
            for query in visual_queries[:2]:
                hits = await self._visual.search(query, limit=limit, video_ids=video_ids,
                                                 profile=self._profile)
                channels.append(("visual", [self._from_visual(hit) for hit in hits]))
        # Search several prioritized canonical concepts and their bilingual
        # variants. The former three-term cap routinely discarded the actual
        # brand/product words behind dates and statistics.
        for keyword in expand_search_terms(keywords, limit=16):
            asr = self._asr_store.search_text(keyword, _ASR_PROVIDER, _ASR_MODEL,
                                              limit=limit, video_ids=video_ids)
            ocr = self._ocr_store.search_text(keyword, _OCR_PROVIDER, _OCR_MODEL,
                                              limit=limit, video_ids=video_ids)
            channels.append(("asr", [c for hit in asr if (c := self._from_asr(keyword, hit)) is not None]))
            channels.append(("ocr", [c for hit in ocr if (c := self._from_ocr(keyword, hit)) is not None]))
        fused: dict[tuple[UUID, int, int], tuple[_Candidate, float]] = {}
        votes: dict[tuple[UUID, int, int], dict[str, float]] = {}
        for source, candidates in channels:
            weight = 2.0 if source == evidence else 1.0
            # Several synonyms in one evidence channel must not multiply its vote.
            for rank, candidate in enumerate(candidates, 1):
                key = (candidate.video_id, candidate.start_ms, candidate.end_ms)
                existing, _ = fused.get(key, (candidate, 0.0))
                existing.visual_score = _max_score(existing.visual_score, candidate.visual_score)
                existing.asr_score = _max_score(existing.asr_score, candidate.asr_score)
                existing.ocr_score = _max_score(existing.ocr_score, candidate.ocr_score)
                _append_unique(existing.asr_texts, candidate.asr_texts)
                _append_unique(existing.ocr_texts, candidate.ocr_texts)
                per_source = votes.setdefault(key, {})
                per_source[source] = max(per_source.get(source, 0.0), weight / (60 + rank))
                fused[key] = (existing, sum(per_source.values()))
        ordered = sorted(fused.values(), key=lambda item: (
            -item[1], str(item[0].video_id), item[0].start_ms, item[0].end_ms))
        return [candidate.to_hit().model_copy(update={"score": score})
                for candidate, score in ordered[:limit]]

    @staticmethod
    def _from_visual(hit: CoarseVideoSearchHit) -> _Candidate:
        return _Candidate(
            video_id=hit.video_id,
            filename=hit.filename,
            source_uri=hit.source_uri,
            start_ms=hit.source_start_ms,
            end_ms=hit.source_end_ms,
            visual_score=_visual_score(hit.score),
        )

    def _from_asr(self, query: str, hit: ASRTextMatch) -> _Candidate | None:
        score = text_specificity_score(query, hit.text)
        video = self._catalog.get_video(hit.video_id)
        if score is None or video is None:
            return None
        return _Candidate(
            video_id=video.id,
            filename=video.filename,
            source_uri=video.source_uri,
            start_ms=hit.start_ms,
            end_ms=hit.end_ms,
            asr_score=score,
            asr_texts=[hit.text],
        )

    def _from_ocr(self, query: str, hit: OCRTextMatch) -> _Candidate | None:
        score = text_specificity_score(query, hit.text)
        video = self._catalog.get_video(hit.video_id)
        if score is None or video is None:
            return None
        return _Candidate(
            video_id=video.id,
            filename=video.filename,
            source_uri=video.source_uri,
            start_ms=hit.start_ms,
            end_ms=hit.end_ms,
            ocr_score=score,
            ocr_texts=[hit.text],
        )

    def _merge_candidates(self, candidates: list[_Candidate]) -> list[_Candidate]:
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                str(candidate.video_id),
                candidate.start_ms,
                candidate.end_ms,
            ),
        )
        merged: list[_Candidate] = []
        for candidate in ordered:
            if not merged:
                merged.append(candidate)
                continue
            current = merged[-1]
            same_video = current.video_id == candidate.video_id
            close_enough = candidate.start_ms <= current.end_ms + self._profile.overlap_ms
            if not same_video or not close_enough:
                merged.append(candidate)
                continue

            current.end_ms = max(current.end_ms, candidate.end_ms)
            current.visual_score = _max_score(current.visual_score, candidate.visual_score)
            current.asr_score = _max_score(current.asr_score, candidate.asr_score)
            current.ocr_score = _max_score(current.ocr_score, candidate.ocr_score)
            _append_unique(current.asr_texts, candidate.asr_texts)
            _append_unique(current.ocr_texts, candidate.ocr_texts)
        return merged


def build_hybrid_search_service(
    *,
    catalog: CatalogLookupLike,
    visual_service: VisualSearchLike | None,
    db_path: Path,
) -> HybridSearchService:
    return HybridSearchService(
        catalog=catalog,
        visual=visual_service,
        asr_store=ASRStore(db_path),
        ocr_store=OCRStore(db_path),
    )
