"""Local rough-cut retrieval adapter (zero API in the editing stage).

Replaces the DeepPass service in the rough-cut pipeline. DeepPass re-ran the
vision provider on candidate frames for every plan; this adapter performs the
same recall entirely from the local library:

* ``prepare_beats`` is an identity function; the retired storyboard API is
  never called.
* candidate recall is local (permanent fourteen-layer facts + ASR + OCR).
* semantic annotations are read from the local catalog instead of a second
  provider call, so no candidate is re-analysed and no API token is spent.

Recall degradation (all local, zero extra API):
1. whole-sentence query -> vector + ASR + OCR
2. if the covered source duration is below ``needed_duration_ms``, the query
   is split into short clauses and recalled through the local ASR/OCR text
   stores only (no visual/embedding call).
3. as a last resort, unused long segments of the library are returned as
   ``source``-level fallbacks so a plan can always be produced; the planner
   keeps its "must output a draft, quality problems only warn" contract.
"""

import logging
import re
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field

from clipatlas.catalog.store import CatalogStore
from clipatlas.director.story_models import StoryEvidenceReference
from clipatlas.domain.evidence import EvidenceStatement, Proposition
from clipatlas.domain.models import (
    AnnotationOrigin,
    ObjectiveFact,
    ObjectiveFactLayer,
    SemanticAnnotation,
)
from clipatlas.domain.visual_protocol import (
    VideoSequenceWindow,
    VideoTimelineEvent,
    normalize_match_level,
)
from clipatlas.retrieval.hybrid import HybridSearchHit, HybridSearchLike, RecallSource
from clipatlas.retrieval.text_normalization import (
    concepts_in_text,
    expand_search_terms,
    matched_terms,
    strong_match,
)

logger = logging.getLogger(__name__)

_ROUGH_CUT_NAMESPACE = "clipatlas:rough-cut-candidate:"
_MAX_USEFUL_SHOT_MS = 12_000
_CLAUSE_SPLIT = re.compile(r"[。！？!?；;，,、\s]+")
# ---------------------------------------------------------------------------
# 本地核心词拆分（零 API）：整句 -> 可检索关键词
# 解决“中文整句 LIKE 英文标注 0 命中”问题：
#   1) 数字/单位/英文模式（62.7%、200万、ADS、L2、NOA…）
#   2) 中文词典最长匹配（华为、乾崑、智驾、防撞…，跨题材可扩充）
#   3) 同音/常见口误变体（乾崑->乾坤、智驾->支架），仅用于 ASR/OCR 宽召回
#   4) 可选 2-gram 兜底，覆盖词典未收录的重要词（仅用于 ASR/OCR 宽召回）
# ---------------------------------------------------------------------------
_CN_DICT = (
    "华为", "乾崑", "鸿蒙", "问界", "赛力斯", "智驾", "智能驾驶", "自动驾驶", "辅助驾驶",
    "领航", "渗透率", "新能源", "纯电", "混动", "燃油", "增程", "电动", "充电", "换电",
    "防撞", "座舱", "底盘", "大梁", "车身", "电池", "电机", "雷达", "激光", "毫米波",
    "传感器", "摄像头", "城市", "高速", "数据", "大屏", "屏幕", "用户", "搭载", "市场",
    "份额", "市占率", "冠军", "里程碑", "生态", "量产", "豪华", "主流", "品牌", "车型",
    "车企", "软件", "硬件", "研发", "里程", "测试", "安全", "体验", "口碑", "技术",
    "场景", "价位", "行业", "标杆", "直播", "央视", "专访", "越野", "性能", "定位",
    "0醛0苯", "母婴", "甲醛", "微克", "暴晒", "座舱", "平顺", "静谧", "隔音",
    "功能", "参数", "配置", "系统", "算法", "电子", "螺丝钉", "赋能", "合作", "覆盖",
    "占比", "突破", "增长", "领先", "速度", "效率", "可靠", "扭矩", "功率", "续航",
    "加速", "悬挂", "轮胎", "座椅", "音响", "空调", "氛围灯", "极致", "趋势", "未来",
    "发布", "亮相", "首款", "全新", "升级", "支持", "开启", "实现", "达到", "超过",
    "接近", "提升", "降低", "接入", "适配", "智舱", "销量", "交付", "订单", "门店",
    "渠道", "价格", "成本", "利润", "标杆", "力量", "保障", "承诺", "服务", "品质",
)
_CN_DICT_SORTED = tuple(sorted(_CN_DICT, key=len, reverse=True))
_CN_STOP = frozenset({
    "的", "了", "是", "在", "与", "和", "及", "也", "都", "而", "又", "就", "不", "为",
    "以", "这", "那", "有", "之", "其", "或", "并", "中", "上", "下", "对", "从", "到",
    "把", "被", "让", "向", "给", "于", "等", "呢", "吗", "吧", "啊", "哦", "么", "得",
    "地", "着", "过", "来", "去", "再", "能", "会", "要", "想", "说", "看", "听", "走",
    "拿", "放", "什么", "一个", "没有", "我们", "你们", "他们", "自己", "这个", "那个",
    "已经", "可以", "因为", "所以", "但是", "如果", "就是", "还是", "不是", "如何",
    "为何", "以及", "并且", "或者", "例如", "比如", "通过", "进行", "作为", "对于",
    "关于", "同时", "还有", "其中", "目前", "目前", "如今", "现在", "今年", "今天",
    "昨天", "明天", "整个", "全面", "真正", "其实", "确实", "非常", "十分", "特别",
    "比较", "更加", "越来越", "一定", "必须", "应该", "能够", "需要", "成为", "变成",
    "带来", "带来", "展现", "体现", "显示", "表明", "意味着", "代表", "标志", "开始",
    "继续", "结束", "完成", "进入", "推出", "宣布", "表示", "指出", "认为", "希望",
})
_EN_STOP = frozenset({
    "the", "and", "of", "to", "in", "for", "with", "on", "at", "by", "is", "are",
    "was", "were", "a", "an", "or", "as", "it", "this", "that", "from", "be", "been",
})
_NUM_PATTERN = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|万|亿|百|千|台|辆|家|款|条|次|位|个|年|月|日|倍)?"
    r"|L2|L3|NOA|ADS|5G|AI|APP|OTA)"
)
# 同音/常见口误变体：检索 ASR/OCR 时把核心词扩成变体一起查（中文口播转写常见）
_CN_VARIANTS: dict[str, tuple[str, ...]] = {
    "乾崑": ("乾坤",),
    "智驾": ("支架", "智架"),
    "鸿蒙": ("鸿盟",),
    "问界": ("问戒",),
}


def _match_dict_cn(text: str) -> list[str]:
    """按词典最长匹配切出中文核心词（保留命中位置用于 ngram 兜底）。"""
    found: list[str] = []
    i, n = 0, len(text)
    while i < n:
        matched = None
        for w in _CN_DICT_SORTED:
            if text.startswith(w, i):
                matched = w
                break
        if matched:
            found.append(matched)
            i += len(matched)
        else:
            i += 1
    return found


def _bigram_cn(text: str) -> list[str]:
    out: list[str] = []
    for i in range(len(text) - 1):
        w = text[i:i + 2]
        if w in _CN_STOP or w[0] in _CN_STOP or w[1] in _CN_STOP:
            continue
        out.append(w)
    return out


def split_keywords(
    query: str,
    *,
    limit: int = 14,
    include_ngram: bool = True,
) -> list[str]:
    """把整句拆成可检索的核心关键词（本地、零 API）。

    - ``include_ngram=False``：只出词典词/数字/英文词，用于精确的主召回
      （标注多列 + 素材文件名）。
    - ``include_ngram=True``：额外加 2-gram 与同音变体，用于 ASR/OCR 宽召回，
      提高中文口播/字幕命中率。
    """
    priority: list[str] = []
    ordinary: list[str] = []
    numeric: list[str] = []
    fallback: list[str] = []
    seen: set[str] = set()

    def push(target: list[str], w: str) -> None:
        w = w.strip()
        if not w or w in seen:
            return
        seen.add(w)
        target.append(w)

    identity = {
        "华为", "乾崑", "鸿蒙", "问界", "赛力斯", "智驾", "智能驾驶",
        "自动驾驶", "辅助驾驶", "领航", "防撞", "座舱", "雷达", "激光雷达",
        "北京越野", "北汽", "泰钽700", "BJ40",
    }
    cjk = "".join(ch for ch in query if "\u4e00" <= ch <= "\u9fff")
    for word in concepts_in_text(query):
        push(priority if word in identity else ordinary, word)
    for word in _CN_DICT_SORTED:
        if word in cjk:
            push(priority if word in identity else ordinary, word)
    for m in re.finditer(r"[A-Za-z]{2,}(?:-[A-Za-z]+)?|[A-Za-z]+\d+", query):
        w = m.group(0)
        if w.lower() not in _EN_STOP:
            push(priority, w)
    # Bare numbers are too ambiguous (dates/timecodes/OCR coordinates) to
    # create exact matches. Retain only complete numeric facts with a unit.
    for m in re.finditer(
        r"(?:\d+醛\d+苯|\d+(?:\.\d+)?\s*(?:%|万|亿|公里|千米|km|毫米|厘米|"
        r"微克(?:每立方米)?|米|秒|分钟|小时|个月|年|家|款|台|辆))",
        query,
        flags=re.IGNORECASE,
    ):
        push(numeric, re.sub(r"\s+", "", m.group(0)))
    if include_ngram:
        for w in [*priority, *ordinary]:
            for variant in _CN_VARIANTS.get(w, ()):
                push(fallback, variant)
        if not priority and not ordinary:
            for w in _bigram_cn(cjk):
                push(fallback, w)
    return [*priority, *ordinary, *numeric, *fallback][:limit]


def local_rough_cut_segment_id(video_id: UUID, start_ms: int, end_ms: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"{_ROUGH_CUT_NAMESPACE}{video_id}:{start_ms}:{end_ms}")


def split_clauses(query: str, *, limit: int = 8, min_len: int = 2) -> list[str]:
    parts = [part.strip() for part in _CLAUSE_SPLIT.split(query)]
    kept: list[str] = []
    for part in parts:
        if not part or len(part) < min_len:
            continue
        kept.append(part)
        if len(kept) >= limit:
            break
    return kept


class LocalRoughCutHit(BaseModel):
    """A rough-cut candidate produced without a second vision API call."""

    segment_id: UUID
    video_id: UUID
    filename: str
    source_uri: str
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0)
    hybrid_score: float = Field(ge=0)
    annotation: SemanticAnnotation
    sources: list[RecallSource] = Field(default_factory=list)
    asr_texts: list[str] = Field(default_factory=list)
    ocr_texts: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    anchor_start_ms: int | None = Field(default=None, ge=0)
    anchor_end_ms: int | None = Field(default=None, gt=0)
    safe_start_ms: int | None = Field(default=None, ge=0)
    safe_end_ms: int | None = Field(default=None, gt=0)
    continuity_key: str | None = None
    visual_family: str | None = None
    pollution_level: str | None = None
    presentation_type: str | None = None
    query_relevance_reason: str | None = None
    schedule_level: str = "exact"
    protocol_candidate_type: str | None = None
    protocol_id: UUID | None = None
    continuity_status: str | None = None
    match_level: str | None = None
    subject_score: float = Field(default=0.0, ge=0.0, le=1.0)
    action_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scene_score: float = Field(default=0.0, ge=0.0, le=1.0)
    configuration_score: float = Field(default=0.0, ge=0.0, le=1.0)
    quantity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    relation_score: float = Field(default=0.0, ge=0.0, le=1.0)
    order_score: float = Field(default=0.0, ge=0.0, le=1.0)


def _protocol_annotation(
    events: list[VideoTimelineEvent], *, segment_id: UUID, description: str,
) -> SemanticAnnotation:
    """Project protocol events back into typed facts for the existing claim matcher."""
    facts: list[ObjectiveFact] = []
    for event in events:
        subject = event.entity_name or event.subject_name or event.entity_id or "unknown"
        entity_id = event.entity_track_id or event.entity_id or f"event:{event.event_id or event.id}"
        frames = list(event.frame_ids or event.evidence_frame_ids)
        source = event.evidence_kind if event.evidence_kind in {
            "visual", "source_text", "diagram", "source_audio"
        } else "visual"
        representation = "screen" if source == "source_text" else "real_scene"
        basis = event.temporal_basis if event.temporal_basis in {"interval", "point", "unknown"} else "unknown"

        def add(
            layer: ObjectiveFactLayer,
            predicate: str,
            value: str | None,
            *,
            evidence_kind: str | None = None,
        ) -> None:
            if not value:
                return
            kind = evidence_kind or source
            medium = "screen" if kind == "source_text" else representation
            # The evidence contract correctly refuses to call an action visual
            # evidence without an observed interval and multiple frames.
            if predicate == "action" and kind == "visual" and (
                basis != "interval" or len(set(frames)) < 2
            ):
                return
            facts.append(ObjectiveFact(
                layer=layer,
                value=value,
                start_ms=event.start_ms,
                end_ms=event.end_ms,
                statement=EvidenceStatement(
                    proposition=Proposition(subject=subject, predicate=predicate, value=value),
                    entity_id=entity_id,
                    kind=kind,
                    representation=medium,
                    frame_ids=frames,
                    temporal_basis=basis,
                ),
            ))

        add(ObjectiveFactLayer.SUBJECT, "identity", event.vehicle_model or subject)
        add(ObjectiveFactLayer.ACTION, "action", event.action)
        add(ObjectiveFactLayer.SCENE, "scene", event.scene)
        for value in event.objects:
            add(ObjectiveFactLayer.OBJECT, "presence", value)
        for value in event.visible_equipment:
            add(ObjectiveFactLayer.OBJECT, "presence", value)
        for value in event.configurations:
            add(ObjectiveFactLayer.OBJECT, "configuration", value)
        for value in event.relations:
            add(ObjectiveFactLayer.SPATIAL_RELATION, "relation", value)
        for value in event.ocr:
            add(ObjectiveFactLayer.TEXT_AUDIO, "presence", value, evidence_kind="source_text")
    return SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.AI,
        provider="timeline-protocol",
        description=description,
        characters=list(dict.fromkeys(
            event.entity_name or event.subject_name for event in events
            if event.entity_name or event.subject_name
        )),
        actions=list(dict.fromkeys(event.action for event in events if event.action)),
        scene=list(dict.fromkeys(event.scene for event in events if event.scene)),
        objects=list(dict.fromkeys(
            value for event in events for value in [*event.objects, *event.configurations]
        )),
        ocr=list(dict.fromkeys(value for event in events for value in event.ocr)),
        facts=facts,
    )


class LocalRoughCutSearch:
    """Wrap a hybrid search so its results satisfy the rough-cut contract.

    The wrapped search is retained only for compatibility and local evidence
    fallbacks; rough-cut candidate annotation is always read from the catalog.
    """

    def __init__(
        self,
        *,
        search: HybridSearchLike,
        catalog: CatalogStore | None = None,
    ) -> None:
        self._search = search
        self._catalog = catalog

    async def prepare_beats(
        self,
        beats: list[object],
        context: dict[str, object],
    ) -> list[object]:
        """Storyboard planning is retired: the Director API (one call per
        script) already covers S/A/B grading. Keeping this as an identity
        function so legacy callers never trigger a network request."""
        return beats

    async def search(
        self,
        query: str,
        limit: int = 12,
        video_ids: list[UUID] | None = None,
    ) -> list[LocalRoughCutHit]:
        return await self.search_with_context(
            query,
            context=None,
            limit=limit,
            video_ids=video_ids,
        )

    def project_video_ids(self, project_id: UUID) -> list[UUID] | None:
        """项目可见素材范围；空项目返回空列表，不得回退全库。"""
        if self._catalog is None:
            return None
        lookup = getattr(self._catalog, "list_video_ids_for_project", None)
        if not callable(lookup):
            return None
        return list(lookup(project_id))

    async def search_with_context(
        self,
        query: str,
        *,
        context: dict[str, object] | None = None,
        limit: int = 12,
        video_ids: list[UUID] | None = None,
    ) -> list[LocalRoughCutHit]:
        query = query.strip()
        if not query or limit <= 0:
            return []
        if video_ids is not None and not video_ids:
            return []
        context = dict(context or {})
        context.setdefault("match_keywords", split_keywords(query, include_ngram=False))
        from clipatlas.director.models import DirectorUnit
        from clipatlas.director.local_fit import fit
        intent = context.get("retrieval_intent") or {}
        director_units = []
        if isinstance(intent, dict):
            for raw in intent.get("director_units", []):
                try:
                    unit = DirectorUnit.model_validate(raw)
                except (ValueError, TypeError):
                    continue
                if unit.claims:
                    director_units.append(unit)

        story_hits = self._recall_story_evidence(intent, video_ids=video_ids)

        # Editing stage is strictly local: the primary recall reads the
        # permanent annotation facts (objects/actions/scenes/description),
        # then ASR/OCR keyword recall, then local library fallbacks.
        # No embed_query() and no HTTP provider call happens in this path.
        protocol_hits = self._recall_protocol_candidates(
            query, limit=max(limit * 3, 20), video_ids=video_ids,
        )
        merged = _merge_unique(story_hits, protocol_hits)
        merged = _merge_unique(merged, await self._recall_annotations_local(
            query, limit=limit, video_ids=video_ids,
        ))
        if director_units:
            # Recall each atomic requirement independently so early broad text
            # hits cannot crowd out the only evidence for a later S claim.
            for unit in director_units:
                for claim in unit.claims:
                    terms = list(dict.fromkeys(
                        value for alternative in claim.any_of for condition in alternative.all_of
                        for value in (condition.subject, condition.value)
                    ))
                    extra = await self._recall_annotations_local(
                        " ".join(terms), limit=max(limit, 24), video_ids=video_ids,
                        explicit_terms=terms,
                    )
                    merged = _merge_unique(merged, extra)
            for hit in merged:
                source_window = (
                    (hit.source_start_ms, hit.source_end_ms)
                    if hit.protocol_candidate_type in {"event", "window"}
                    else None
                )
                verdicts = [fit(
                    unit,
                    hit.annotation,
                    source_window=source_window,
                    allow_untimed=source_window is None,
                ) for unit in director_units]
                matches = [m for verdict in verdicts for m in verdict.claim_matches]
                if matches:
                    all_direct = bool(matches) and all(m.level == "DIRECT" for m in matches)
                    has_direct = any(m.level == "DIRECT" for m in matches)
                    has_support = any(m.level == "SUPPORT" for m in matches)
                    hit.schedule_level = (
                        "exact" if all_direct else "related" if has_direct or has_support else "source"
                    )
                    hit.score = min(
                        1.0,
                        (0.85 if has_direct else 0.45 if has_support else 0.0)
                        + 0.03 * sum(m.level == "DIRECT" for m in matches)
                        + 0.01 * sum(m.level == "SUPPORT" for m in matches),
                    )
                    hit.match_level = normalize_match_level(
                        hit.schedule_level,
                        "DIRECT" if all_direct else "SUPPORT" if has_support else None,
                    )
                    hit.query_relevance_reason = "逐项事实证据召回：" + "; ".join(
                        f"{m.source_quote}={m.level}" for m in matches)
            merged = [hit for hit in merged if not any(fit(
                unit,
                hit.annotation,
                source_window=(hit.source_start_ms, hit.source_end_ms)
                if hit.protocol_candidate_type in {"event", "window"} else None,
                allow_untimed=hit.protocol_candidate_type not in {"event", "window"},
            ).level == "REJECT" for unit in director_units)]
        merged = self._filter_non_editable(merged, context)

        needed_ms = _context_int(context, "needed_duration_ms")
        excluded = _context_excluded(context)
        if needed_ms is not None and needed_ms > 0:
            merged = _filter_excluded(merged, excluded)
            covered = _covered_ms(merged)
            if covered < needed_ms:
                extra = await self._recall_by_clauses(
                    query, context=context, limit=limit, video_ids=video_ids,
                )
                merged = _merge_unique(merged, _filter_excluded(extra, excluded))
            covered = _covered_ms(merged)
            if covered < needed_ms:
                extra = await self._recall_library_fallback(
                    context=context, limit=limit, video_ids=video_ids,
                )
                merged = _merge_unique(merged, _filter_excluded(extra, excluded))
                logger.info(
                    "roughcut fallback query=%s covered_ms=%s/%s extra=%s",
                    query[:40], _covered_ms(merged), needed_ms, len(extra),
                )
        if needed_ms is not None and needed_ms > 0:
            merged = self._expand_to_semantic_spans(merged, needed_ms)
        # Clause/source/generic fallbacks and span expansion all converge here.
        # Recheck the final candidate segment so no later fallback bypasses
        # title-card, screen or technical-chart policy.
        merged = self._filter_non_editable(merged, context)
        return _rank_and_diversify(merged, limit=limit)

    def _recall_story_evidence(
        self,
        intent: object,
        *,
        video_ids: list[UUID] | None,
    ) -> list[LocalRoughCutHit]:
        if self._catalog is None or not isinstance(intent, dict):
            return []
        allowed = set(video_ids) if video_ids is not None else None
        hits: list[LocalRoughCutHit] = []
        for raw in intent.get("story_evidence", []):
            try:
                evidence = StoryEvidenceReference.model_validate(raw)
            except (TypeError, ValueError):
                continue
            if allowed is not None and evidence.video_id not in allowed:
                continue
            video = self._catalog.get_video(evidence.video_id)
            if video is None:
                continue

            segment = None
            if evidence.segment_id is not None:
                segment = self._catalog.get_segment(evidence.segment_id)
                if segment is not None and segment.video_id != evidence.video_id:
                    segment = None
            if segment is None:
                segments = self._catalog.list_segments(
                    evidence.video_id,
                    limit=1,
                    offset=0,
                    start_ms=evidence.start_ms,
                    end_ms=evidence.end_ms,
                )
                segment = segments[0] if segments else None

            segment_id = (
                segment.id
                if segment is not None
                else local_rough_cut_segment_id(
                    evidence.video_id,
                    evidence.start_ms,
                    evidence.end_ms,
                )
            )
            annotation = self._catalog.get_effective_annotation(segment_id)
            if annotation is None:
                annotation = SemanticAnnotation(
                    segment_id=segment_id,
                    origin=AnnotationOrigin.AI,
                    provider="story-evidence",
                    description=evidence.text,
                    confidence=0.0,
                )
            hits.append(LocalRoughCutHit(
                segment_id=segment_id,
                video_id=evidence.video_id,
                filename=video.filename,
                source_uri=video.source_uri,
                source_start_ms=evidence.start_ms,
                source_end_ms=evidence.end_ms,
                score=0.0,
                hybrid_score=0.0,
                annotation=annotation,
                sources=[evidence.kind],
                asr_texts=[evidence.text] if evidence.kind == "asr" else [],
                ocr_texts=[evidence.text] if evidence.kind == "ocr" else [],
                query_relevance_reason="Story Outline 引用的真实素材证据",
                schedule_level="related",
                match_level="RELATED",
            ))
        return hits

    def _recall_protocol_candidates(
        self,
        query: str,
        *,
        limit: int,
        video_ids: list[UUID] | None,
    ) -> list[LocalRoughCutHit]:
        """Wide local recall over v2 events and windows.

        This deliberately returns related candidates.  DIRECT/REJECT remains a
        later evidence decision and continuity marked unknown is never upgraded
        here.
        """
        if self._catalog is None:
            return []
        ids = list(video_ids or [])
        if video_ids is None:
            list_ids = getattr(self._catalog, "list_video_ids", None)
            ids = list(list_ids(limit=100_000)) if callable(list_ids) else []
        terms = split_keywords(query, include_ngram=False)
        if not terms:
            return []
        event_lookup = getattr(self._catalog, "list_timeline_events", None)
        window_lookup = getattr(self._catalog, "list_sequence_windows", None)
        if not callable(event_lookup) or not callable(window_lookup):
            return []
        hits: list[LocalRoughCutHit] = []
        for video_id in ids:
            get_video = getattr(self._catalog, "get_video", None)
            video = get_video(video_id) if callable(get_video) else None
            if video is None:
                continue
            events = event_lookup(video_id)
            event_by_id = {event.id: event for event in events}
            def event_text(event: VideoTimelineEvent) -> str:
                return " ".join(filter(None, [
                    event.entity_name or event.subject_name, event.vehicle_model, event.brand,
                    event.variant or event.version, event.action, event.scene,
                    event.road_surface or event.road_type, event.environment,
                    event.state_before,
                    event.state_after, *event.objects, *event.configurations,
                    *event.visible_equipment, *event.ocr, *event.quantities,
                    *event.relations, *event.state_changes,
                ]))

            matched_events = [event for event in events if matched_terms(event_text(event), terms)]
            for event in matched_events:
                segment_id = event.evidence_segment_ids[0] if event.evidence_segment_ids else (
                    local_rough_cut_segment_id(video_id, event.start_ms, event.end_ms)
                )
                annotation = self._catalog.get_effective_annotation(segment_id)
                if annotation is None:
                    annotation = _protocol_annotation(
                        [event], segment_id=segment_id,
                        description=event.action or event.scene or "时间轴事件候选",
                    )
                matched = matched_terms(event_text(event), terms)
                hits.append(LocalRoughCutHit(
                    segment_id=segment_id,
                    video_id=video.id,
                    filename=video.filename,
                    source_uri=video.source_uri,
                    source_start_ms=event.start_ms,
                    source_end_ms=event.end_ms,
                    score=min(0.99, 0.45 + 0.08 * len(matched)),
                    hybrid_score=0.0,
                    annotation=annotation,
                    matched_terms=matched,
                    continuity_key=f"event:{event.id}",
                    query_relevance_reason=(
                        "v2时间轴事件宽召回；连续性="
                        + ("unknown" if not event.entity_id else "entity-bound")
                    ),
                    schedule_level="related",
                    protocol_candidate_type="event",
                    protocol_id=event.id,
                     continuity_status=(
                         "probable_continuity" if event.same_entity_as_previous is True
                         else "unknown_continuity"
                     ),
                     match_level="RELATED",
                    subject_score=float(bool(event.subject_name or event.entity_id) and any(
                     term.casefold() in (event.entity_name or event.subject_name or "").casefold() for term in terms
                    )),
                    action_score=float(bool(event.action) and any(
                        term.casefold() in event.action.casefold() for term in terms
                    )),
                    scene_score=float(bool(event.scene) and any(
                        term.casefold() in event.scene.casefold() for term in terms
                    )),
                    configuration_score=float(bool(event.configurations) and any(
                        term.casefold() in " ".join(event.configurations).casefold() for term in terms
                    )),
                    quantity_score=float(bool(event.quantities) and any(
                        term.casefold() in " ".join(event.quantities).casefold() for term in terms
                    )),
                    relation_score=float(bool(event.relations) and any(
                        term.casefold() in " ".join(event.relations).casefold() for term in terms
                    )),
                ))
            windows = window_lookup(video_id)
            for window in windows:
                window_events = [event_by_id[event_id] for event_id in window.event_ids if event_id in event_by_id]
                if not window_events:
                    continue
                window_text = " ".join([
                    window.ordered_summary,
                    *(event_text(event) for event in window_events),
                ])
                matched = matched_terms(window_text, terms)
                if not matched:
                    continue
                anchor = window_events[0]
                segment_id = anchor.evidence_segment_ids[0] if anchor.evidence_segment_ids else (
                    local_rough_cut_segment_id(video_id, anchor.start_ms, anchor.end_ms)
                )
                annotation = _protocol_annotation(
                    window_events, segment_id=segment_id,
                    description=window.ordered_summary or "连续时间轴窗口候选",
                )
                hits.append(LocalRoughCutHit(
                    segment_id=segment_id,
                    video_id=video.id,
                    filename=video.filename,
                    source_uri=video.source_uri,
                    source_start_ms=window.start_ms,
                    source_end_ms=window.end_ms,
                    score=min(0.995, 0.6 + 0.08 * len(matched)),
                    hybrid_score=0.0,
                    annotation=annotation,
                    matched_terms=matched,
                    continuity_key=f"window:{window.id}",
                    query_relevance_reason=(
                        "v2连续窗口宽召回；continuity_status=" + window.continuity_status
                    ),
                    schedule_level="related",
                    protocol_candidate_type="window",
                    protocol_id=window.id,
                     continuity_status=window.continuity_status,
                     match_level=(
                         "SUPPORT" if window.continuity_status in {
                             "confirmed_continuity", "probable_continuity"
                         } else "RELATED"
                     ),
                    subject_score=float(bool(matched_terms(" ".join(annotation.characters), terms))),
                    action_score=float(bool(matched_terms(" ".join(annotation.actions), terms))),
                    scene_score=float(bool(matched_terms(" ".join(annotation.scene), terms))),
                    order_score=0.0,
                ))
        # Prefer a complete continuous window over its individual event when
        # both occupy the same source range.
        hits.sort(key=lambda hit: 0 if (hit.continuity_key or "").startswith("window:") else 1)
        return _merge_unique([], hits)[:limit]

    def _expand_to_semantic_spans(
        self, hits: list[LocalRoughCutHit], target_ms: int,
    ) -> list[LocalRoughCutHit]:
        if self._catalog is None:
            return hits
        expand = getattr(self._catalog, "expand_segment_window", None)
        span_lookup = getattr(self._catalog, "get_semantic_span_for_segment", None)
        if not callable(expand):
            return hits
        expanded: list[LocalRoughCutHit] = []
        for hit in hits:
            if getattr(hit, "protocol_candidate_type", None) in {"event", "window"}:
                expanded.append(hit)
                continue
            if hit.schedule_level not in {"exact", "related", "text_heavy", "source", "generic"}:
                expanded.append(hit)
                continue
            window = expand(hit.segment_id, target_ms)
            if window is None:
                expanded.append(hit)
                continue
            span = span_lookup(hit.segment_id) if callable(span_lookup) else None
            annotation = hit.annotation
            # Keep the anchor's annotation. Span-wide labels cannot establish
            # that a subject and action co-occur in the selected source range.
            expanded.append(hit.model_copy(update={
                "anchor_start_ms": (hit.anchor_start_ms if hit.anchor_start_ms is not None
                                    else hit.source_start_ms),
                "anchor_end_ms": (hit.anchor_end_ms if hit.anchor_end_ms is not None
                                  else hit.source_end_ms),
                "source_start_ms": window[0],
                "source_end_ms": window[1],
                "safe_start_ms": getattr(span, "safe_start_ms", window[0]),
                "safe_end_ms": getattr(span, "safe_end_ms", window[1]),
                "continuity_key": getattr(span, "continuity_key", None),
                "visual_family": getattr(span, "visual_family", None),
                "pollution_level": getattr(span, "pollution_level", None),
                "presentation_type": getattr(span, "presentation_type", None),
                "annotation": annotation,
                "schedule_level": (
                    "text_heavy"
                    if getattr(span, "pollution_level", None) == "text_heavy"
                    and hit.schedule_level in {"exact", "related", "source"}
                    else hit.schedule_level
                ),
                "query_relevance_reason": (
                    f"{hit.query_relevance_reason or '本地证据命中'}；"
                    "已扩展到同一连续语义段的安全窗口"
                ),
            }))
        return expanded

    async def _recall_annotations_local(
        self,
        query: str,
        *,
        limit: int,
        video_ids: list[UUID] | None,
        explicit_terms: list[str] | None = None,
    ) -> list[LocalRoughCutHit]:
        """Primary local recall: keyword match against the permanent
        annotation facts (description/objects/actions/scenes/characters/
        emotions/ocr/facts) plus the Chinese video filename (主题标签).
        Zero API."""
        if self._catalog is None:
            return []
        keywords = (
            list(dict.fromkeys(term.strip() for term in explicit_terms if term.strip()))
            if explicit_terms is not None
            else split_keywords(query, include_ngram=False)
        )
        if not keywords:
            return []
        # The catalog SQL accepts sixteen terms. Keep every canonical query
        # concept first, then add Chinese/English variants round-robin so one
        # concept with many aliases cannot crowd later facts out of recall.
        expanded_keywords = expand_search_terms(keywords, limit=32)
        hits: list[LocalRoughCutHit] = []
        seen_segments: set[UUID] = set()
        try:
            pairs = self._catalog.search_annotations_by_keywords(
                expanded_keywords, limit=limit * 3, video_ids=video_ids,
            )
        except Exception:  # noqa: BLE001 - catalog query must never break planning
            logger.exception("local annotation recall failed")
            pairs = []
        for segment_id, annotation in pairs:
            if len(hits) >= limit:
                break
            if segment_id in seen_segments:
                continue
            seen_segments.add(segment_id)
            segment = self._catalog.get_segment(segment_id)
            if segment is None:
                continue
            video = self._catalog.get_video(segment.video_id)
            if video is None:
                continue
            start, end = segment.start_ms, segment.end_ms
            if end - start < 1500:
                continue
            annotation_text = " ".join([
                annotation.description, *annotation.characters, *annotation.actions,
                *annotation.scene, *annotation.emotions, *annotation.objects,
                *annotation.ocr, *(fact.value for fact in annotation.facts),
            ])
            matches = matched_terms(annotation_text, keywords)
            level = "exact" if strong_match(matches, keywords) else "related"
            hits.append(LocalRoughCutHit(
                segment_id=segment_id,
                video_id=segment.video_id,
                filename=video.filename,
                source_uri=video.source_uri,
                source_start_ms=start,
                source_end_ms=end,
                score=0.6 if level == "exact" else 0.32,
                hybrid_score=0.0,
                annotation=annotation,
                query_relevance_reason="本地事实表关键词匹配（对象/动作/场景/描述）",
                matched_terms=matches,
                schedule_level=level,
            ))
        # 文件名召回：视频文件名常为中文主题标签（如“华为乾崑200万里程碑”），
        # 中文关键词直接命中文件名即可召回，不依赖英文标注。
        try:
            file_rows = self._catalog.search_segments_by_filename(
                expanded_keywords, limit=limit * 2, video_ids=video_ids,
            )
        except Exception:  # noqa: BLE001
            logger.exception("local filename recall failed")
            file_rows = []
        for segment_id, video_id, start, end, filename, source_uri in file_rows:
            if len(hits) >= limit:
                break
            if segment_id in seen_segments:
                continue
            seen_segments.add(segment_id)
            if end - start < 1500:
                continue
            matches = matched_terms(filename, keywords)
            annotation = self._catalog.get_effective_annotation(segment_id)
            if annotation is None:
                annotation = SemanticAnnotation(
                    segment_id=segment_id,
                    origin=AnnotationOrigin.AI,
                    provider="catalog",
                    description=f"素材文件名含主题词（{filename}），建议人工复核画面。",
                    confidence=0.0,
                )
            annotation_text = " ".join([
                annotation.description, *annotation.characters, *annotation.actions,
                *annotation.scene, *annotation.objects, *annotation.ocr,
                *(fact.value for fact in annotation.facts),
            ])
            content_matches = matched_terms(annotation_text, keywords)
            # A model/brand word in the filename proves source identity only.
            # It becomes exact only when the segment annotation independently
            # matches the current sentence's concrete action, scene or fact.
            level = "exact" if strong_match(content_matches, keywords) else "related"
            hits.append(LocalRoughCutHit(
                segment_id=segment_id,
                video_id=video_id,
                filename=filename,
                source_uri=source_uri,
                source_start_ms=start,
                source_end_ms=end,
                score=0.55 if level == "exact" else 0.28,
                hybrid_score=0.0,
                annotation=annotation,
                query_relevance_reason="素材文件名包含主题词（本地文件名匹配）",
                matched_terms=matches,
                schedule_level=level,
            ))
        return hits

    async def continuation_candidates(
        self,
        clip: object,
        *,
        limit: int = 6,
        needed_duration_ms: int | None = None,
    ) -> list[LocalRoughCutHit]:
        """Local continuation for B-tier beats: later segments of the same
        video that start at/after the previous clip's source_out. Zero API."""
        if self._catalog is None or clip is None:
            return []
        video_id = getattr(clip, "video_id", None)
        from_ms = getattr(clip, "source_out_ms", None)
        if video_id is None or from_ms is None:
            return []
        video = self._catalog.get_video(video_id)
        if video is None:
            return []
        # Long source videos regularly contain more than 200 segments. Reading
        # only the first page makes continuation falsely disappear whenever
        # the selected clip is later in the file, which then forces a return
        # to an older video or an unnecessary fallback cut.
        segments = self._catalog.list_segments(video_id, limit=1_000_000, offset=0)
        hits: list[LocalRoughCutHit] = []
        for segment in segments:
            if len(hits) >= limit:
                break
            start, end = segment.start_ms, segment.end_ms
            if start < int(from_ms) - 200:
                continue
            if end - start < 1500:
                continue
            annotation = self._catalog.get_effective_annotation(segment.id)
            if annotation is None:
                annotation = SemanticAnnotation(
                    segment_id=segment.id,
                    origin=AnnotationOrigin.AI,
                    provider="catalog",
                    description="同视频延续素材（B 级前后延展）",
                    confidence=0.0,
                )
            hits.append(LocalRoughCutHit(
                segment_id=segment.id,
                video_id=video_id,
                filename=video.filename,
                source_uri=video.source_uri,
                source_start_ms=start,
                source_end_ms=end,
                score=0.4,
                hybrid_score=0.0,
                annotation=annotation,
                query_relevance_reason="B 级延展：同一视频安全后续范围",
                schedule_level="related",
            ))
        if needed_duration_ms is not None and needed_duration_ms > 0:
            hits = self._expand_to_semantic_spans(hits, needed_duration_ms)
        return self._filter_non_editable(hits, {"allow_tail_text": False})

    async def neutral_candidates(
        self,
        *,
        limit: int = 6,
        video_ids: list[UUID] | None = None,
        needed_duration_ms: int | None = None,
    ) -> list[LocalRoughCutHit]:
        """Local neutral fallback for B-tier beats with no previous clip."""
        generic = await self._recall_generic_fallback(
            context=None, limit=limit, video_ids=video_ids,
        )
        if generic:
            expanded = self._expand_to_semantic_spans(
                generic, needed_duration_ms,
            ) if needed_duration_ms else generic
            return self._filter_non_editable(expanded, {"allow_tail_text": False})
        # B-level has no query text to drive the normal degradation chain;
        # still provide the same content-unverified source fallback so an
        # otherwise readable library can always produce a draft.
        plain = await self._recall_plain_library_fallback(
            context=None, limit=limit, video_ids=video_ids,
        )
        expanded = self._expand_to_semantic_spans(
            plain, needed_duration_ms,
        ) if needed_duration_ms else plain
        return self._filter_non_editable(expanded, {"allow_tail_text": False})

    async def _recall_by_clauses(
        self,
        query: str,
        *,
        context: dict[str, object] | None,
        limit: int,
        video_ids: list[UUID] | None,
    ) -> list[LocalRoughCutHit]:
        """Local text-only recall: split the query into core keywords and run
        the ASR/OCR stores through ``search_evidence`` with no visual queries,
        so no embedding/API call is made. Uses the wide keyword split (2-gram
        + 同音变体) so Chinese narration/OCR like “华为乾坤支架搭载量突破200万”
        can be hit by “华为/乾崑/智驾/200万”."""
        keywords = split_keywords(query, include_ngram=True)
        if not keywords:
            return []
        evidence = getattr(self._search, "search_evidence", None)
        if not callable(evidence):
            return []
        try:
            hits = await evidence(
                visual_queries=[],
                keywords=keywords,
                evidence="mixed",
                limit=limit,
                video_ids=video_ids,
            )
        except TypeError:
            try:
                hits = await evidence(
                    visual_queries=[], keywords=keywords, evidence="mixed", limit=limit,
                )
            except TypeError:
                return []
        local = [self._to_local_hit(hit, clause_hit=True, query_terms=keywords) for hit in hits]
        if local:
            logger.info("roughcut clause recall query=%s keywords=%s hits=%s",
                        query[:30], keywords[:4], len(local))
        return local

    async def _recall_library_fallback(
        self,
        *,
        context: dict[str, object] | None,
        limit: int,
        video_ids: list[UUID] | None,
    ) -> list[LocalRoughCutHit]:
        """Last-resort fallback so a draft can always be produced.

        Priority 1: generic b-roll videos (named 通用/空镜/generic/… or detected
        as neutral footage). These are long, calm, non-dialogue shots picked as
        ``generic``-level fallbacks — visually usable neutral padding.
        Priority 2: unused library segments as before (``source``-level).
        """
        generic = await self._recall_generic_fallback(
            context=context, limit=limit, video_ids=video_ids,
        )
        if generic:
            logger.info("roughcut generic fallback hits=%s", len(generic))
            return generic
        return await self._recall_plain_library_fallback(
            context=context, limit=limit, video_ids=video_ids,
        )

    async def _recall_generic_fallback(
        self,
        *,
        context: dict[str, object] | None,
        limit: int,
        video_ids: list[UUID] | None,
    ) -> list[LocalRoughCutHit]:
        """Pick long, calm, non-title-card segments from generic videos."""
        if self._catalog is None:
            return []
        excluded = _context_excluded(context)
        minimum_ms = _context_int(context, "minimum_shot_ms") or 2_000
        list_ids = getattr(self._catalog, "list_video_ids", None)
        get_video = getattr(self._catalog, "get_video", None)
        if not callable(list_ids) or not callable(get_video):
            return []
        wanted_videos = list(video_ids) if video_ids else [
            row[0] if isinstance(row, (list, tuple)) else row
            for row in list_ids(limit=200)
        ]
        candidates: list[LocalRoughCutHit] = []
        for video_id in wanted_videos:
            video = get_video(video_id)
            if video is None:
                continue
            filename = video.filename or ""
            # Generic is an explicit video-level decision. A filename or one
            # neutral-looking annotation must never reclassify a whole video.
            role = getattr(video, "fallback_role", "normal")
            if role == "never":
                continue
            is_generic = role == "generic"
            if not is_generic:
                continue
            segments = self._catalog.list_segments(video_id, limit=60, offset=0)
            for segment in segments:
                start, end = segment.start_ms, segment.end_ms
                if end - start < minimum_ms:
                    continue
                if any(
                    v == video_id and start < excluded_end and end > excluded_start
                    for v, excluded_start, excluded_end in excluded
                ):
                    continue
                media_type = None
                get_media_type = getattr(self._catalog, "get_segment_media_type", None)
                if callable(get_media_type):
                    media_type = get_media_type(segment.id)
                if media_type is not None:
                    medium, _, text_ratio, text_block_count = media_type
                    if medium == "title_card":
                        continue
                    if text_ratio is not None and text_ratio > 0.30:
                        continue
                    if text_block_count is not None and text_block_count >= 4:
                        continue
                annotation = self._catalog.get_effective_annotation(segment.id)
                if annotation is None:
                    annotation = SemanticAnnotation(
                        segment_id=segment.id,
                        origin=AnnotationOrigin.AI,
                        provider="catalog",
                        description="通用素材兜底，中性画面，请人工复核是否贴合上下文。",
                        confidence=0.0,
                    )
                candidates.append(LocalRoughCutHit(
                    segment_id=segment.id,
                    video_id=video_id,
                    filename=filename,
                    source_uri=video.source_uri,
                    source_start_ms=start,
                    source_end_ms=end,
                    score=0.0,
                    hybrid_score=0.0,
                    annotation=annotation,
                    query_relevance_reason="通用素材兜底，中性画面",
                    schedule_level="generic",
                ))
        # Prefer longer, earlier segments so the timeline stays calm.
        candidates.sort(
            key=lambda hit: (-(hit.source_end_ms - hit.source_start_ms), hit.source_start_ms),
        )
        return candidates[:limit]

    async def _recall_plain_library_fallback(
        self,
        *,
        context: dict[str, object] | None,
        limit: int,
        video_ids: list[UUID] | None,
    ) -> list[LocalRoughCutHit]:
        """Content-unverified fallback from unused library segments (original)."""
        if self._catalog is None:
            return []
        excluded = _context_excluded(context)
        minimum_ms = _context_int(context, "minimum_shot_ms") or 2_000
        list_ids = getattr(self._catalog, "list_video_ids", None)
        if not callable(list_ids):
            return []
        wanted_videos = list(video_ids) if video_ids else [
            row[0] if isinstance(row, (list, tuple)) else row
            for row in list_ids(limit=50)
        ]
        fallbacks: list[LocalRoughCutHit] = []
        for video_id in wanted_videos:
            if len(fallbacks) >= limit:
                break
            get_video = getattr(self._catalog, "get_video", None)
            video = get_video(video_id) if callable(get_video) else None
            if video is not None and getattr(video, "fallback_role", "normal") == "never":
                continue
            segments = self._catalog.list_segments(video_id, limit=40, offset=0)
            for segment in segments:
                if len(fallbacks) >= limit:
                    break
                start, end = segment.start_ms, segment.end_ms
                if end - start < minimum_ms:
                    continue
                if any(
                    v == video_id and start < excluded_end and end > excluded_start
                    for v, excluded_start, excluded_end in excluded
                ):
                    continue
                annotation = self._catalog.get_effective_annotation(segment.id)
                if annotation is None:
                    annotation = SemanticAnnotation(
                        segment_id=segment.id,
                        origin=AnnotationOrigin.AI,
                        provider="catalog",
                        description="库内兜底配图，未确认具体内容匹配，请人工复核。",
                        confidence=0.0,
                    )
                fallbacks.append(LocalRoughCutHit(
                    segment_id=segment.id,
                    video_id=video_id,
                    filename=video.filename if video else str(video_id),
                    source_uri=video.source_uri if video else "",
                    source_start_ms=start,
                    source_end_ms=end,
                    score=0.0,
                    hybrid_score=0.0,
                    annotation=annotation,
                    query_relevance_reason="库内兜底配图，未确认具体内容匹配",
                    schedule_level="source",
                ))
        return fallbacks

    # 大屏 / PPT / 技术图 / 纯文字海报：不进正文剪辑。
    _NON_EDITABLE_MEDIUMS = frozenset(
        {"title_card", "screen_capture", "technical_chart"}
    )

    @staticmethod
    def _hit_ocr_texts(hit: LocalRoughCutHit) -> list[str]:
        annotation = getattr(hit, "annotation", None)
        texts = list(getattr(annotation, "ocr", []) or [])
        texts.extend(getattr(hit, "ocr_texts", []) or [])
        return [str(t) for t in texts if t]

    @staticmethod
    def _normalize_text(value: object) -> str:
        return "".join(str(value).lower().split())

    @classmethod
    def _ocr_matches_s(
        cls, ocr_texts: list[str], s_keywords: list[str],
    ) -> bool:
        """画面 OCR 是否命中 S 级核心词/数字（如 200万、0.05毫米）。"""
        if not ocr_texts or not s_keywords:
            return False
        blob = cls._normalize_text(" ".join(ocr_texts))
        if not blob:
            return False
        for raw in s_keywords:
            keyword = cls._normalize_text(raw)
            if not keyword:
                continue
            has_cjk = any("一" <= ch <= "鿿" for ch in keyword)
            min_len = 2 if has_cjk else 3
            if len(keyword) >= min_len and keyword in blob:
                return True
        return False

    def _filter_non_editable(
        self,
        hits: list[LocalRoughCutHit],
        context: dict[str, object] | None = None,
    ) -> list[LocalRoughCutHit]:
        """过滤不可进正文的画面，所有语义与兜底路径使用同一准入规则。

        - title_card / screen_capture / technical_chart（大屏、PPT、技术图、
          纯文字海报）默认不进正文；
        - text_ratio > 0.30 或 text_block_count >= 4 的文字堆砌画面不进正文；
        - OCR-S 放行：S 级卖点且画面 OCR 与核心词/数字一致时整段保留，避免
          为一个数字反复切碎画面（宗旨：出片 + 少切）；
        - C 级片尾：黑屏只有少量文字（<=2 个文本块、占幅 <=0.55）的 title_card
          降级为 c_tail，正常素材充足时排最后不被选中，缺素材时兜底铺满。
        未标注媒体类型的素材保留并标记未知；source/generic 不得绕过已知污染。
        """
        if self._catalog is None or not hits:
            return hits
        importance = ""
        match_keywords: list[str] = []
        if context:
            importance = str(context.get("director_importance") or "")
            raw_kw = context.get("match_keywords") or context.get("s_keywords") or []
            if isinstance(raw_kw, (list, tuple)):
                match_keywords = [str(k) for k in raw_kw if k]
        kept: list[LocalRoughCutHit] = []
        tail_only: list[LocalRoughCutHit] = []
        typed_units = []
        if context:
            from clipatlas.director.models import DirectorUnit
            intent = context.get("retrieval_intent") or {}
            if isinstance(intent, dict):
                for raw in intent.get("director_units", []):
                    try:
                        unit = DirectorUnit.model_validate(raw)
                    except (ValueError, TypeError):
                        continue
                    if unit.claims:
                        typed_units.append(unit)
        for hit in hits:
            get_media_type = getattr(self._catalog, "get_segment_media_type", None)
            media_type = get_media_type(hit.segment_id) if callable(get_media_type) else None
            if media_type is None:
                kept.append(hit)
                continue
            medium, _, text_ratio, text_block_count = media_type
            get_contamination = getattr(self._catalog, "get_segment_contamination_kinds", None)
            contamination = (
                get_contamination(hit.segment_id) if callable(get_contamination) else []
            )

            # 真实画面叠加大字仍保留，但降级；同等匹配时优先干净画面。
            if medium not in self._NON_EDITABLE_MEDIUMS:
                if (
                    (text_ratio is not None and text_ratio > 0.30)
                    or (text_block_count is not None and text_block_count >= 4)
                    or any("text" in kind or "subtitle" in kind for kind in contamination)
                ):
                    hit.schedule_level = "text_heavy"
                    hit.query_relevance_reason = "正常画面含大字或密集文字，降低使用优先级"
                kept.append(hit)
                continue

            # 不可进正文的类型：先看是否满足 S 级 OCR 整段放行（技术图不放行）。
            typed_proof = False
            if typed_units:
                from clipatlas.director.local_fit import fit
                typed_proof = any(
                    match.level == "DIRECT"
                    and any(kind in {"source_text", "diagram"} for kind in match.evidence_kinds)
                    for unit in typed_units for match in fit(unit, hit.annotation).claim_matches
                )
            if (
                importance == "S"
                and medium in ("screen_capture", "technical_chart")
                and (typed_proof if typed_units else
                     self._ocr_matches_s(self._hit_ocr_texts(hit), match_keywords))
            ):
                hit.schedule_level = "text_heavy"
                hit.query_relevance_reason = "屏幕文字与S级文案匹配，作为低优先级证明画面"
                logger.info(
                    "roughcut OCR-S keep segment=%s medium=%s", hit.segment_id, medium,
                )
                kept.append(hit)
                continue

            # 黑底文字仅在 OCR 与当前完整句匹配时允许，且压到片尾优先级。
            if (
                medium == "title_card"
                and bool(context and context.get("allow_tail_text"))
                and (_context_int(context, "needed_duration_ms") or 0) <= 3000
                and text_block_count is not None
                and 1 <= text_block_count <= 3
                and (text_ratio is None or text_ratio <= 0.55)
                and self._ocr_matches_s(self._hit_ocr_texts(hit), match_keywords)
            ):
                hit.schedule_level = "c_tail"
                hit.query_relevance_reason = "黑底文字与当前口播匹配，仅作低优先级片尾画面"
                tail_only.append(hit)
                continue

            logger.info(
                "roughcut skip non-editable segment=%s medium=%s ratio=%s blocks=%s",
                hit.segment_id, medium, text_ratio, text_block_count,
            )
        # 正常候选在前，C 级片尾候选压到最后，正常素材充足时不会被选中。
        return kept + tail_only

    def _to_local_hit(
        self,
        hit: HybridSearchHit,
        *,
        clause_hit: bool = False,
        query_terms: list[str] | None = None,
    ) -> LocalRoughCutHit:
        segment = self._find_overlapping_segment(hit)
        segment_id = segment.id if segment is not None else local_rough_cut_segment_id(
            hit.video_id, hit.source_start_ms, hit.source_end_ms,
        )
        annotation = None
        if segment is not None and self._catalog is not None:
            annotation = self._catalog.get_effective_annotation(segment.id)
        if annotation is None:
            annotation = SemanticAnnotation(
                segment_id=segment_id,
                origin=AnnotationOrigin.AI,
                provider="catalog",
                description="本地检索命中，该片段尚无语义标注，请人工复核画面内容。",
                confidence=0.0,
            )
        reason = "本地短句检索命中，未做二次画面复核" if clause_hit else (
            "本地检索命中，未做二次画面复核" if annotation.provider == "catalog" else None
        )
        evidence_text = " ".join([
            hit.filename, *hit.asr_texts, *hit.ocr_texts, annotation.description,
            *annotation.characters, *annotation.actions, *annotation.scene,
            *annotation.objects,
        ])
        matches = matched_terms(evidence_text, query_terms or [])
        level = (
            "exact"
            if strong_match(matches, query_terms) and len(set(hit.sources)) >= 1
            else "related"
        )
        return LocalRoughCutHit(
            segment_id=segment_id,
            video_id=hit.video_id,
            filename=hit.filename,
            source_uri=hit.source_uri,
            source_start_ms=hit.source_start_ms,
            source_end_ms=hit.source_end_ms,
            score=hit.score,
            hybrid_score=hit.score,
            annotation=annotation,
            sources=hit.sources,
            asr_texts=hit.asr_texts,
            ocr_texts=hit.ocr_texts,
            matched_terms=matches,
            query_relevance_reason=reason,
            schedule_level=level,
        )

    def _find_overlapping_segment(self, hit: HybridSearchHit):
        if self._catalog is None:
            return None
        segments = self._catalog.list_segments(
            hit.video_id,
            limit=1,
            offset=0,
            start_ms=hit.source_start_ms,
            end_ms=hit.source_end_ms,
        )
        return segments[0] if segments else None


def _context_int(context: dict[str, object] | None, key: str) -> int | None:
    if not context:
        return None
    try:
        return int(context[key])
    except (KeyError, TypeError, ValueError):
        return None


def _context_excluded(context: dict[str, object] | None) -> list[tuple[UUID, int, int]]:
    if not context:
        return []
    raw = context.get("excluded_ranges") or []
    excluded: list[tuple[UUID, int, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            excluded.append((UUID(item["video_id"]), int(item["start_ms"]), int(item["end_ms"])))
        except (KeyError, TypeError, ValueError):
            continue
    return excluded


def _covered_ms(hits: list[LocalRoughCutHit]) -> int:
    return sum(
        min(_MAX_USEFUL_SHOT_MS, hit.source_end_ms - hit.source_start_ms) for hit in hits
    )


def _filter_excluded(
    hits: list[LocalRoughCutHit],
    excluded: list[tuple[UUID, int, int]],
) -> list[LocalRoughCutHit]:
    if not excluded:
        return hits
    kept: list[LocalRoughCutHit] = []
    for hit in hits:
        start, end = hit.source_start_ms, hit.source_end_ms
        if any(
            video_id == hit.video_id and start < excluded_end and end > excluded_start
            for video_id, excluded_start, excluded_end in excluded
        ):
            continue
        kept.append(hit)
    return kept


def _merge_unique(
    existing: list[LocalRoughCutHit],
    additions: list[LocalRoughCutHit],
) -> list[LocalRoughCutHit]:
    seen = {
        (hit.video_id, hit.source_start_ms, hit.source_end_ms): hit for hit in existing
    }
    for hit in additions:
        key = (hit.video_id, hit.source_start_ms, hit.source_end_ms)
        if key not in seen:
            seen[key] = hit
    return list(seen.values())


def _rank_and_diversify(
    hits: list[LocalRoughCutHit], *, limit: int,
) -> list[LocalRoughCutHit]:
    """Prefer strong evidence while preventing one long video dominating recall."""
    priority = {"exact": 0, "related": 1, "text_heavy": 2, "generic": 3,
                "source": 4, "c_tail": 5, "reuse": 6}
    ordered = sorted(hits, key=lambda hit: (
        priority.get(hit.schedule_level, 2),
        -len(hit.matched_terms),
        -len(set(hit.sources)),
        -hit.score,
        str(hit.video_id), hit.source_start_ms,
    ))
    selected: list[LocalRoughCutHit] = []
    per_video: dict[UUID, int] = {}
    for hit in ordered:
        if per_video.get(hit.video_id, 0) >= 3:
            continue
        if any(
            other.video_id == hit.video_id
            and min(other.source_end_ms, hit.source_end_ms)
                - max(other.source_start_ms, hit.source_start_ms) >= 1_000
            for other in selected
        ):
            continue
        selected.append(hit)
        per_video[hit.video_id] = per_video.get(hit.video_id, 0) + 1
        if len(selected) >= limit:
            break
    return selected
