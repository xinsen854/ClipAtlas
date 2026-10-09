"""Align imported narration to observed ASR word times, never estimated durations."""
import asyncio
import json
import logging
import re
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import uuid5

from clipatlas.asr.audio import MAX_ASR_CHUNK_DURATION_MS, ASRAudioChunkMaterializer
from clipatlas.asr.models import ASRSentence
from clipatlas.asr.qwen import QwenAudioASRProvider
from clipatlas.speech.alignment import AlignmentResult, AlignmentUnitTiming, validate_alignment
from clipatlas.speech.errors import SpeechAudioValidationError
from clipatlas.speech.alignment import NarrationAlignmentMap
from clipatlas.speech.models import (
    NarrationTrack,
    NarrationUnit,
    NarrationWordTiming,
    TimingQuality,
    utc_now,
)
from clipatlas.speech.store import NarrationStore

logger = logging.getLogger(__name__)


def _normalized(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


def _clauses(text: str) -> list[str]:
    result: list[str] = []
    pending = ""
    for part in re.split(r"(?<=[。！？!?；;，,])|\n+", text):
        pending += part.strip()
        if pending and (len(_normalized(pending)) >= 24 or
                        pending[-1] in "。！？!?；;"):
            result.append(pending)
            pending = ""
    if pending:
        result.append(pending)
    return [part for part in result if _normalized(part)]


def align_script(
    script_units: list[str], sentences: list[ASRSentence], duration_ms: int,
) -> tuple[list[str], AlignmentResult, list[str]]:
    """Monotone text matching; every boundary comes from an observed ASR word."""
    words = [word for sentence in sentences for word in sentence.words
             if _normalized(word.text)]
    if not words:
        raise SpeechAudioValidationError("旁白识别未返回词级时间，无法可靠对齐；请重试。")
    transcript = ""
    word_at: list[int] = []
    for index, word in enumerate(words):
        chars = _normalized(word.text)
        transcript += chars
        word_at.extend([index] * len(chars))
    parts = [(index, part) for index, unit in enumerate(script_units) for part in _clauses(unit)]
    chunks = [part for _, part in parts]
    normalized = [_normalized(part) for part in chunks]
    script = "".join(normalized)
    mapping: dict[int, int] = {}
    for block in SequenceMatcher(None, script, transcript, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = word_at[block.b + offset]
    notes: list[str] = []
    texts: list[str] = []
    timings: list[AlignmentUnitTiming] = []
    cursor = 0
    matched_chars = 0
    included_chars = 0
    previous_owner = -1
    for (owner, part), chars in zip(parts, normalized, strict=True):
        matched = [(i, mapping[i]) for i in range(cursor, cursor + len(chars)) if i in mapping]
        coverage = len(matched) / max(1, len(chars))
        if (coverage < 0.25 and cursor == 0 and len(chars) <= 80
                and not part.endswith(tuple("。！？!?；;"))):
            notes.append(f"开头文案未在旁白中读出，未安排画面：{part}")
            cursor += len(chars)
            continue
        if coverage < 0.65 or not matched:
            raise SpeechAudioValidationError(f"旁白与文案无法可靠对齐，请检查漏句或错配：{part}")
        if matched[0][0] - cursor > 5 or cursor + len(chars) - 1 - matched[-1][0] > 5:
            raise SpeechAudioValidationError(f"旁白句首或句尾无法确认时间：{part}")
        start = words[matched[0][1]].start_ms
        end = words[matched[-1][1]].end_ms
        if start < 0 or end > duration_ms or end <= start:
            raise SpeechAudioValidationError("旁白识别时间超出真实音频范围")
        # A word can span a textual clause boundary: merge, do not invent a split inside it.
        if timings and (start < timings[-1].end_ms or
                        (owner == previous_owner and end - start < 3500
                         and end - timings[-1].start_ms <= 14000)):
            texts[-1] += part
            timings[-1].end_ms = max(timings[-1].end_ms, end)
        else:
            texts.append(part)
            timings.append(AlignmentUnitTiming(sequence=len(timings), start_ms=start, end_ms=end))
        matched_chars += len(matched)
        included_chars += len(chars)
        previous_owner = owner
        cursor += len(chars)
    if not timings or matched_chars / max(1, included_chars) < 0.85:
        raise SpeechAudioValidationError("旁白与文案匹配不足，未生成估算时间或粗剪。")
    observed_start, observed_end = words[0].start_ms, words[-1].end_ms
    if timings[0].start_ms - observed_start > 1500 or observed_end - timings[-1].end_ms > 1500:
        raise SpeechAudioValidationError("旁白含有文案未覆盖的开头或结尾，请检查对应关系。")
    for left, right in pairwise(timings):
        # Speech in this gap indicates unmatched narration, not ordinary silence.
        if right.start_ms - left.end_ms > 2500 and any(
            w.start_ms >= left.end_ms and w.end_ms <= right.start_ms for w in words
        ):
            raise SpeechAudioValidationError("旁白中存在未对齐的语句，请检查文案是否完整。")
    notes.append(f"按实际 ASR 词时间对齐 {len(texts)} 段；文本匹配率 {matched_chars / included_chars:.1%}。")
    return texts, validate_alignment(AlignmentResult(units=timings),
                                    unit_count=len(texts), duration_ms=duration_ms), notes


def align_source_units(
    source_units: list[str], sentences: list[ASRSentence], duration_ms: int,
) -> tuple[AlignmentResult, list[str]]:
    """Map immutable source units to monotone ASR word ranges.

    ASR sentence boundaries are not treated as editing or source-text
    boundaries.  Each source unit keeps its own quote; only its observed word
    interval is returned.
    """
    words = [word for sentence in sentences for word in sentence.words if _normalized(word.text)]
    if not words:
        raise SpeechAudioValidationError("ASR returned no word-level timings")
    transcript = ""
    word_at: list[int] = []
    for index, word in enumerate(words):
        characters = _normalized(word.text)
        transcript += characters
        word_at.extend([index] * len(characters))
    timings: list[AlignmentUnitTiming] = []
    notes: list[str] = []
    cursor = 0
    for sequence, source in enumerate(source_units):
        target = _normalized(source)
        if not target:
            raise SpeechAudioValidationError("Source narration unit is empty")
        match = SequenceMatcher(None, target, transcript[cursor:], autojunk=False).find_longest_match(
            0, len(target), 0, len(transcript) - cursor,
        )
        coverage = match.size / max(1, len(target))
        if coverage < 0.65:
            raise SpeechAudioValidationError(
                f"Source narration unit cannot be aligned reliably: {source}"
            )
        start_character = cursor + match.b
        end_character = start_character + match.size - 1
        start = words[word_at[start_character]].start_ms
        end = words[word_at[end_character]].end_ms
        if end <= start or end > duration_ms:
            raise SpeechAudioValidationError("ASR timing exceeds narration duration")
        timings.append(AlignmentUnitTiming(
            sequence=sequence,
            start_ms=start,
            end_ms=end,
            confidence=coverage,
        ))
        cursor = end_character + 1
    notes.append(f"mapped {len(timings)} source units to observed ASR word times")
    return validate_alignment(
        AlignmentResult(units=timings), unit_count=len(source_units), duration_ms=duration_ms,
    ), notes


class NarrationAlignmentService:
    def __init__(self, *, store: NarrationStore, provider: QwenAudioASRProvider, root: Path):
        self._store = store
        self._provider = provider
        self._root = root
        self._lock = asyncio.Lock()

    async def ensure_aligned(self, track: NarrationTrack) -> NarrationTrack:
        async with self._lock:
            return await self._align(track)

    async def _align(self, track: NarrationTrack) -> NarrationTrack:
        if track.timing_quality != TimingQuality.TRACK_ONLY:
            return track
        parsed = urlparse(track.audio_uri or "")
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            raise SpeechAudioValidationError("旁白缺少可读取的本地音频")
        source = Path(url2pathname(parsed.path)).resolve()
        audio_hash = sha256(source.read_bytes()).hexdigest()
        snapshot_id = uuid5(track.id, f"asr-aligned-v1:{audio_hash}:{track.script_hash}")
        existing = self._store.get_track(snapshot_id)
        if existing is not None:
            return existing
        root = self._root / str(track.project_id) / str(track.id) / "alignment"
        root.mkdir(parents=True, exist_ok=True)
        cache = root / f"{self._provider.model}-{audio_hash}.json"
        if cache.exists():
            sentences = [ASRSentence.model_validate(s) for s in json.loads(cache.read_text('utf-8'))]
        else:
            sentences = []
            materializer = ASRAudioChunkMaterializer(root / "audio")
            # 上游偶发返回空（无词/无 sentence）并非音频一定没话：重试 3 次后才判定失败
            for attempt in range(3):
                collected: list[ASRSentence] = []
                for start in range(0, track.duration_ms, MAX_ASR_CHUNK_DURATION_MS):
                    end = min(start + MAX_ASR_CHUNK_DURATION_MS, track.duration_ms)
                    chunk = await materializer.materialize(source=source, video_id=snapshot_id,
                                                           start_ms=start, end_ms=end)
                    try:
                        for sentence in await self._provider.transcribe(chunk.path):
                            collected.append(sentence.model_copy(update={
                                "start_ms": sentence.start_ms + start,
                                "end_ms": sentence.end_ms + start,
                                "words": [w.model_copy(update={"start_ms": w.start_ms + start,
                                                               "end_ms": w.end_ms + start})
                                          for w in sentence.words],
                            }))
                    except Exception:
                        # 单块失败不中断本次重试，继续收集其余块
                        logger.warning("ASR chunk failed source=%s range=%d..%d attempt=%d",
                                       source.name, start, end, attempt + 1, exc_info=True)
                if collected:
                    sentences = collected
                    break
                logger.warning("ASR returned empty source=%s duration_ms=%d attempt=%d/3, retrying",
                               source.name, track.duration_ms, attempt + 1)
                await asyncio.sleep(3 * (attempt + 1))
            if not sentences:
                logger.error("ASR empty after 3 attempts source=%s duration_ms=%d track=%s",
                             source.name, track.duration_ms, track.id)
                raise SpeechAudioValidationError("旁白未识别出有效文本")
            temporary = cache.with_suffix(".tmp")
            temporary.write_text(json.dumps([s.model_dump(mode="json") for s in sentences],
                                            ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache)
        original_units = self._store.list_units(track.id)
        alignment, notes = align_source_units(
            [unit.text for unit in original_units], sentences, track.duration_ms,
        )
        maps = [
            NarrationAlignmentMap(
                source_unit_id=str(source.id),
                source_quote=source.text,
                start_ms=timing.start_ms,
                end_ms=timing.end_ms,
                asr_sentence_ids=[
                    str(index) for index, sentence in enumerate(sentences)
                    if sentence.start_ms < timing.end_ms and sentence.end_ms > timing.start_ms
                ],
                alignment_confidence=timing.confidence,
            )
            for source, timing in zip(original_units, alignment.units, strict=True)
        ]
        updated = track.model_copy(update={
            "id": snapshot_id, "timing_quality": TimingQuality.ALIGNED,
            "revision": self._store.next_track_revision(track.project_id), "created_at": utc_now(),
            "alignment_source_id": track.id, "alignment_notes": notes,
            "alignment_maps": maps,
        })
        units = [NarrationUnit(
            id=uuid5(snapshot_id, f"unit:{timing.sequence}"), track_id=snapshot_id,
            sequence=timing.sequence, text=source.text,
            text_hash=sha256(source.text.encode()).hexdigest(),
            start_ms=timing.start_ms, end_ms=timing.end_ms, source=track.source_mode,
        ) for source, timing in zip(original_units, alignment.units, strict=True)]
        self._store.save_track_snapshot(updated, units)
        unit_ids = {
            timing.sequence: unit.id
            for unit, timing in zip(units, alignment.units, strict=True)
        }
        if alignment.words:
            self._store.save_word_timings([
                NarrationWordTiming(
                    unit_id=unit_ids[item.unit_sequence], sequence=item.sequence,
                    word=item.word, start_ms=item.start_ms, end_ms=item.end_ms,
                    confidence=item.confidence,
                )
                for item in alignment.words
            ])
        logger.info("narration aligned source=%s track=%s units=%s", track.id, updated.id, len(units))
        return updated
