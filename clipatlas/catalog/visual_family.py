"""Visual-family detection over the existing catalog (zero API, zero vision).

The user's rule: during first-time annotation, shots that show the same
subject should be labelled as one visual family (e.g. "底盘 画面1", "底盘
画面2"); during timeline construction the same family may appear at most once
-- never two segments of the same family in one cut, and never the same family
twice.

For the already-indexed library (which has no annotation text) we approximate
the family from two local signals:

1. OCR text similarity: two segments showing the same on-screen text (e.g. the
   same launch-presentation screen) share a family. Character-set Jaccard >=
   ``OCR_JACCARD_THRESHOLD``.
2. Chunk-embedding cosine: two segments whose video-window embeddings are
   nearly identical share a family (semantic duplicates, e.g. two clips both
   showing the frame/chassis). Cosine >= ``VEC_COSINE_THRESHOLD``.

Guard rail: segments from the same video that are temporally close are
continuous footage, not duplicates, and are exempt (``NEAR_MS``).

New material annotated with an explicit ``visual_family`` field by the
annotation prompt will simply be written into ``catalog_visual_families`` and
this local approximation only fills the segments that have none.
"""

import json
import re
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

_CN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9\-]*|\d+(?:\.\d+)?")
_JSON_NOISE = re.compile(r"json|rotate_rect|text|^\s*[\[{,]|^[\-*]\s*$")

OCR_JACCARD_THRESHOLD = 0.5
VEC_COSINE_THRESHOLD = 0.98
NEAR_MS = 60_000  # same-video segments closer than this are continuous, not duplicates
# A family larger than this means the clustering over-merged (transitive
# closure snowball); oversized families are dissolved so their segments do not
# block each other. The user's scenario is a few true cross-video duplicates,
# not giant pools of loosely related footage.
MAX_FAMILY_SIZE = 12
# The video-window embeddings used here (qwen3-vl-embedding) do not separate
# visually similar-but-different shots of the same product (interior/exterior/
# screens all score ~0.96+), so embedding clustering is opt-in and defaults
# off. OCR on-screen text is the reliable local duplicate signal; the precise
# visual_family field comes from the one-time annotation API.
USE_EMBEDDING_FAMILIES = False


def ocr_signature(raw: str) -> str:
    raw = _JSON_NOISE.sub(" ", raw or "")
    tokens = _CN_RE.findall(raw)
    return " ".join(tokens[:60])


def _charset(signature: str) -> set[str]:
    return set(signature.replace(" ", ""))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


class _UnionFind:
    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, index: int) -> int:
        parent = self._parent
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def _load_chunk_vectors(connection: sqlite3.Connection) -> dict[tuple[str, int, int], Any]:
    result: dict[tuple[str, int, int], Any] = {}
    for row in connection.execute(
        "SELECT video_id, start_ms, end_ms, vector_json FROM catalog_video_chunk_embeddings"
    ):
        try:
            vector = json.loads(row["vector_json"])
        except (TypeError, ValueError):
            continue
        if not vector:
            continue
        result[(row["video_id"], row["start_ms"], row["end_ms"])] = vector
    return result


def build_visual_families(
    connection: sqlite3.Connection,
    *,
    ocr_jaccard_threshold: float = OCR_JACCARD_THRESHOLD,
    vec_cosine_threshold: float = VEC_COSINE_THRESHOLD,
    near_ms: int = NEAR_MS,
    use_embeddings: bool = USE_EMBEDDING_FAMILIES,
) -> dict[str, str]:
    """Return {segment_id: family_id} for every catalog segment.

    Family ids are opaque labels (``vf_0001``, ...) so the timeline constraint
    is purely equality-based, exactly like the user's "画面1 / 画面2" numbering.
    Embedding clustering is disabled by default (see module docstring).
    """
    segments = connection.execute(
        "SELECT id, video_id, start_ms, end_ms FROM catalog_segments"
    ).fetchall()
    if not segments:
        return {}

    ocr_rows = connection.execute(
        "SELECT video_id, start_ms, end_ms, text FROM catalog_ocr_samples "
        "WHERE status = 'completed' AND text IS NOT NULL"
    ).fetchall()
    ocr_by_video: dict[str, list[tuple[int, int, str]]] = {}
    for row in ocr_rows:
        ocr_by_video.setdefault(row["video_id"], []).append(
            (row["start_ms"], row["end_ms"], row["text"])
        )

    chunk_vectors = _load_chunk_vectors(connection)
    vectors_by_video: dict[str, list[tuple[int, int, Any]]] = {}
    for (video_id, start_ms, end_ms), vector in chunk_vectors.items():
        vectors_by_video.setdefault(video_id, []).append((start_ms, end_ms, vector))

    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - numpy is a hard dependency
        raise RuntimeError("numpy is required for visual-family clustering") from exc

    seg_index: list[dict[str, Any]] = []
    ocr_sigs: list[set[str]] = []
    vec_norm: list[Any] = []
    for index, segment in enumerate(segments):
        video_id = segment["video_id"]
        start_ms = int(segment["start_ms"])
        end_ms = int(segment["end_ms"])
        ocr_parts: list[str] = []
        for sample_start, sample_end, text in ocr_by_video.get(video_id, []):
            overlap = min(end_ms, sample_end) - max(start_ms, sample_start)
            if overlap > 0 and overlap >= 0.5 * min(end_ms - start_ms, sample_end - sample_start):
                ocr_parts.append(text)
        ocr_sigs.append(_charset(ocr_signature(" ".join(ocr_parts))))

        vectors = [
            vector
            for (chunk_start, chunk_end, vector) in vectors_by_video.get(video_id, [])
            if min(end_ms, chunk_end) - max(start_ms, chunk_start)
            >= 0.5 * min(chunk_end - chunk_start, end_ms - start_ms)
        ]
        if vectors:
            mean = np.mean(np.asarray(vectors, dtype=np.float32), axis=0)
            norm = np.linalg.norm(mean)
            vec_norm.append(mean / norm if norm > 0 else None)
        else:
            vec_norm.append(None)
        seg_index.append(
            {
                "segment_id": segment["id"],
                "video_id": video_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "index": index,
            }
        )

    union_find = _UnionFind(len(segments))

    def same_video_any(a: dict[str, Any], b: dict[str, Any]) -> bool:
        # Shots from the same video are continuous footage, never "duplicates"
        # — even far apart, they are different timecodes the user can reuse.
        return a["video_id"] == b["video_id"]

    # 1. OCR families
    for i in range(len(seg_index)):
        if len(ocr_sigs[i]) < 4:
            continue
        for j in range(i + 1, len(seg_index)):
            if same_video_any(seg_index[i], seg_index[j]):
                continue
            if len(ocr_sigs[j]) < 4:
                continue
            if _jaccard(ocr_sigs[i], ocr_sigs[j]) >= ocr_jaccard_threshold:
                union_find.union(i, j)

    # 2. Embedding families (opt-in: the current video embeddings do not
    #    separate similar-but-different shots of the same product well)
    if use_embeddings:
        for i in range(len(seg_index)):
            if vec_norm[i] is None:
                continue
            for j in range(i + 1, len(seg_index)):
                if vec_norm[j] is None:
                    continue
                if same_video_any(seg_index[i], seg_index[j]):
                    continue
                if float(np.dot(vec_norm[i], vec_norm[j])) >= vec_cosine_threshold:
                    union_find.union(i, j)
    family_by_root: dict[int, str] = {}
    result: dict[str, str] = {}
    members_by_root: dict[int, list[str]] = {}
    for index, segment in enumerate(seg_index):
        root = union_find.find(index)
        members_by_root.setdefault(root, []).append(segment["segment_id"])
    family_counter = 0
    for root, members in members_by_root.items():
        if len(members) > MAX_FAMILY_SIZE:
            # Over-merged: dissolve; every member becomes its own singleton so
            # the family constraint does not cascade across the library.
            for member in members:
                family_counter += 1
                result[member] = f"vf_{family_counter:04d}"
            continue
        family_counter += 1
        family_id = f"vf_{family_counter:04d}"
        family_by_root[root] = family_id
        for member in members:
            result[member] = family_id
    return result


def ensure_family_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS catalog_visual_families ("
        " segment_id TEXT PRIMARY KEY,"
        " family_id TEXT NOT NULL,"
        " basis TEXT NOT NULL,"
        " created_at TEXT NOT NULL"
        ")"
    )


def persist_families(
    connection: sqlite3.Connection,
    families: dict[str, str],
    *,
    basis: str = "local_cluster",
    force: bool = False,
) -> int:
    ensure_family_table(connection)
    from clipatlas.domain.models import utc_now

    timestamp = utc_now().isoformat()
    if force:
        connection.execute("DELETE FROM catalog_visual_families")
    existing = {
        row[0]
        for row in connection.execute("SELECT segment_id FROM catalog_visual_families").fetchall()
    }
    rows = [
        (segment_id, family_id, basis, timestamp)
        for segment_id, family_id in families.items()
        if segment_id not in existing
    ]
    connection.executemany(
        "INSERT INTO catalog_visual_families (segment_id, family_id, basis, created_at) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def load_families(
    connection: sqlite3.Connection,
) -> dict[str, str]:
    ensure_family_table(connection)
    return {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT segment_id, family_id FROM catalog_visual_families"
        ).fetchall()
    }


def family_of(connection: sqlite3.Connection) -> Callable[[str], str | None]:
    families = load_families(connection)

    def lookup(segment_id: str) -> str | None:
        return families.get(str(segment_id))

    return lookup
