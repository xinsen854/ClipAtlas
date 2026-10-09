import logging
import re
import time
from hashlib import sha256
from collections import defaultdict
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any
from math import ceil
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from clipatlas.director.models import DirectorUnit
from clipatlas.director.story_models import StoryOutline
from clipatlas.director.requirements import parse_script_visual_requirements
from clipatlas.director.service import DirectorService
from clipatlas.roughcut.beats import BeatBuilder, estimate_units_locally
from clipatlas.roughcut.evidence import (
    exact_spoken_anchor_offset_ms,
    finalize_evidence,
    source_window,
)
from clipatlas.roughcut.quality import build_quality_report
from clipatlas.roughcut.contracts import RoughCutSearchHit, SegmentSearch
from clipatlas.roughcut.candidate_matrix import build_candidate_matrix
from clipatlas.roughcut.errors import (
    RoughCutConfigurationError,
    RoughCutPlanningError,
    RoughCutRetrievalError,
)
from clipatlas.roughcut.models import (
    CandidateScore,
    PlannerSettings,
    RoughCutClip,
    RoughCutPlan,
    ScriptBeat,
)
from clipatlas.roughcut.pacing import (
    MAX_SHOT_MS,
    MIN_SHOT_MS,
    allocate_durations,
    preferred_shot_counts,
)
from clipatlas.roughcut.scoring import (
    CandidateScorer,
    batch_occupancy_for,
)
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.rules.projector import ProjectTextProjector
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.rules.models import ProjectRulePack
from clipatlas.speech.audio import AudioNormalizer
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
    utc_now,
)
from clipatlas.speech.narration_alignment import NarrationAlignmentService
from clipatlas.speech.store import NarrationStore

logger = logging.getLogger(__name__)

_IMPORTANCE_ORDER = ("B", "A", "S")
_FIT_PRIORITY = {"DIRECT": 0, "SUPPORT": 1, "UNKNOWN": 2}
# Same-video segments closer than this are continuous footage, not duplicates.
_FAMILY_NEAR_MS = 60_000


class RoughCutPlanner:
    @staticmethod
    def _director_rule_identity(
        project_id: UUID, active_pack: ProjectRulePack | None,
    ) -> str:
        """Cache identity is project-scoped and changes with actual rule content."""
        if active_pack is None:
            return f"{project_id}:none"
        rules_json = ProjectRuleStore._rules_json(active_pack.rules)
        digest = sha256(rules_json.encode("utf-8")).hexdigest()[:16]
        return f"{project_id}:{active_pack.revision}:{digest}"

    def __init__(
        self,
        *,
        narration_store: NarrationStore,
        search: SegmentSearch,
        store: RoughCutStore,
        settings: PlannerSettings | None = None,
        beat_builder: BeatBuilder | None = None,
        scorer: CandidateScorer | None = None,
        rule_store: ProjectRuleStore | None = None,
        alignment_service: NarrationAlignmentService | None = None,
        director: DirectorService | None = None,
        family_lookup: Callable[[UUID], str | None] | None = None,
        audio_normalizer: AudioNormalizer | None = None,
        story_audio_root: Path | None = None,
    ) -> None:
        self._narration_store = narration_store
        self._search = search
        self._store = store
        self._settings = settings or PlannerSettings()
        self._beat_builder = beat_builder or BeatBuilder()
        self._scorer = scorer or CandidateScorer(self._settings)
        self._rule_store = rule_store
        self._rule_projector = ProjectTextProjector()
        self._alignment_service = alignment_service
        self._director = director
        self._family_lookup = family_lookup
        self._audio_normalizer = audio_normalizer
        self._story_audio_root = (
            story_audio_root.resolve() if story_audio_root is not None else None
        )

    def _resolve_project_video_scope(self, project_id: UUID) -> list[UUID]:
        lookup = getattr(self._search, "project_video_ids", None)
        if not callable(lookup):
            raise RoughCutConfigurationError("Project library scope is not configured")
        try:
            return list(lookup(project_id))
        except Exception as exc:  # noqa: BLE001 - 隔离失败时绝不能回退全库
            raise RoughCutConfigurationError(
                "无法确认当前项目的素材范围，已阻止跨项目检索"
            ) from exc

    async def create_plan(
        self,
        project_id: UUID,
        *,
        top_k: int | None = None,
        video_ids: list[UUID] | None = None,
        narration_track_id: UUID | None = None,
        script_text: str | None = None,
        activate: bool = True,
        plan_id: UUID | None = None,
        persist: bool = True,
        batch_usage: dict[str, list[tuple[int, int, int]]] | None = None,
        batch_index: int = 0,
        story_outline: StoryOutline | None = None,
        story_node_narration_unit_ids: dict[UUID, list[UUID]] | None = None,
    ) -> RoughCutPlan:
        if (story_outline is None) != (story_node_narration_unit_ids is None):
            raise RoughCutConfigurationError(
                "story_outline and story_node_narration_unit_ids must be provided together"
            )
        story_handoff = story_outline is not None

        track = (
            self._narration_store.get_track(narration_track_id)
            if narration_track_id is not None
            else self._narration_store.get_active_track(project_id)
        )
        if track is None:
            raise RoughCutConfigurationError(
                "Project has no active narration track for rough-cut planning"
            )

        if track.project_id != project_id:
            raise RoughCutConfigurationError("Narration track belongs to another project")
        script = (
            self._narration_store.get_project_script(project_id)
            if narration_track_id is None else None
        )
        if script is not None and script.script_hash != track.script_hash:
            raise RoughCutConfigurationError(
                "已保存文案与当前旁白不一致，请先关联真人旁白或重新生成配音"
            )

        resolved_top_k = self._settings.top_k if top_k is None else top_k
        if not 1 <= resolved_top_k <= 100:
            raise RoughCutConfigurationError("top_k must be between 1 and 100")
        resolved_settings = PlannerSettings.model_validate(
            {**self._settings.model_dump(), "top_k": resolved_top_k}
        )
        # Explicit IDs narrow the project scope; they never override ownership.
        project_scope = self._resolve_project_video_scope(project_id)
        allowed_video_ids = set(project_scope)
        video_ids = project_scope if video_ids is None else list(dict.fromkeys(
            video_id for video_id in video_ids if video_id in allowed_video_ids
        ))
        allowed_video_ids = set(video_ids)
        # 批次级去重上下文：同一批次内已生成的成片占用片段表。
        # video_id -> [(start_ms, end_ms, last_used_batch_index)]，占用以“滚动
        # 释放”计：距离上次使用超过 batch_reuse_gap 条即视为已释放。
        batch_usage = batch_usage or {}
        batch_index = batch_index or 0

        source_track_id = track.id
        source_track = track
        units = self._narration_store.list_units(track.id)
        word_timings = self._narration_store.list_word_timings(track.id)

        if story_handoff:
            assert story_outline is not None
            assert story_node_narration_unit_ids is not None
            # Story handoff owns program-time resolution. It must not pass
            # through BeatBuilder first because an all-visual outline has no
            # NarrationUnit by design.
            beats = self._build_story_beats(
                track,
                units,
                story_outline,
                story_node_narration_unit_ids,
            )
            if self._story_audio_needs_materialization(track, units, beats):
                track, units, beats = await self._materialize_story_audio(
                    track,
                    units,
                    beats,
                )
            beats = self._strip_story_execution_internals(beats)
        else:
            if (track.source_mode == NarrationSourceMode.IMPORTED
                    and track.timing_quality == TimingQuality.TRACK_ONLY):
                track, units = estimate_units_locally(track, units)
            beats = self._beat_builder.build(track, units)

        active_pack = (
            self._rule_store.get_active(project_id)
            if self._rule_store is not None
            else None
        )
        # Storyboard planning (prepare_beats) is retired: the Director API is
        # called exactly once per script below and grades the whole narration
        # into S/A/B content units; no other provider call happens here.

        explicit_script = (
            script_text is not None
            or script is not None
            or (story_outline is None and bool(track.script))
        )
        resolved_script_text = (script_text if script_text is not None else (
            script.text if script is not None else track.script
        )) or ""
        if not resolved_script_text.strip():
            resolved_script_text = "\n".join(
                unit.text for unit in self._narration_store.list_units(track.id)
            )
        if explicit_script and sha256(resolved_script_text.encode()).hexdigest() != track.script_hash:
            raise RoughCutConfigurationError("Authoritative script text does not match the narration track")

        beats = self._attach_visual_requirements(
            beats,
            parse_script_visual_requirements(resolved_script_text),
        )

        director_notes: list[str] = []
        if self._director is not None and self._director.enabled:
            started = time.monotonic()
            script_text = resolved_script_text
            project_rule_revision = self._director_rule_identity(project_id, active_pack)
            try:
                analysis = await self._director.analyze_cached(
                    script_text, rules_revision=project_rule_revision,
                    rules_text=ProjectRuleStore._rules_json(active_pack.rules) if active_pack else "",
                )
                director_notes.extend(analysis.contract_issues)
                director_notes.extend(issue for unit in analysis.units for issue in unit.contract_issues)
                mapped = self._director.map_units(beats, analysis)
                beats = self._attach_visual_requirements(beats, analysis.requirements)
            except Exception as exc:
                logger.warning("Director unavailable; continue with local retrieval: %s", exc)
                director_notes.append("Director 分析不可用，使用本地召回；未确认直接证据")
                mapped = []
            beats = self._merge_director_beats(self._attach_director_units(beats, mapped))
            logger.info(
                "roughcut director elapsed=%.3fs units=%s mapped=%s beats=%s",
                time.monotonic() - started, len(mapped),
                sum(1 for unit in mapped if unit.beat_range is not None), len(beats),
            )

        # Narration beats remain the authoritative audio/subtitle boundaries.
        # Visual beats may cover several adjacent sentences when Director says
        # they are one content unit, so retrieval and shot selection happen
        # once for the complete thought instead of once per sentence.
        visual_beats = self._build_visual_beats(beats)

        clips: list[RoughCutClip] = []
        scheduling_warnings = [*track.alignment_notes, *dict.fromkeys(director_notes)]
        reuse_counts: dict[UUID, int] = {}
        previous_clip: RoughCutClip | None = None

        for beat_index, beat in enumerate(visual_beats):
            logger.info("roughcut beat=%s/%s start_ms=%s end_ms=%s text=%s",
                        beat.sequence + 1, len(visual_beats), beat.timeline_start_ms,
                        beat.timeline_end_ms, beat.text)
            beat_director_units, beat_director_importance = self._beat_director_units(beat)
            anchor_target_offset_ms: int | None = None
            for director_unit in sorted(
                beat_director_units,
                key=lambda unit: _IMPORTANCE_ORDER.index(unit.importance),
                reverse=True,
            ):
                if director_unit.importance not in {"S", "A"} or not director_unit.anchor_phrase:
                    continue
                anchor_target_offset_ms = exact_spoken_anchor_offset_ms(
                    director_unit.anchor_phrase,
                    beat_start_ms=beat.timeline_start_ms,
                    beat_end_ms=beat.timeline_end_ms,
                    word_timings=word_timings,
                )
                if anchor_target_offset_ms is not None:
                    break
            hits = await self._search_s_and_a(
                beat, active_pack, units, clips, video_ids, resolved_top_k,
                allow_tail_text=beat_index == len(visual_beats) - 1,
            )
            continuation = getattr(self._search, "continuation_candidates", None)
            if previous_clip is not None and callable(continuation):
                try:
                    continued = await continuation(
                        previous_clip, limit=resolved_top_k,
                        needed_duration_ms=beat.target_duration_ms,
                    )
                except TypeError:
                    continued = await continuation(previous_clip, limit=resolved_top_k)
                hits = self._merge_adjacent_candidates(hits, continued)
            has_current_match = any(
                getattr(hit, "schedule_level", "exact") in {"exact", "related"}
                for hit in hits
            )
            if not has_current_match:
                adjacent: list[RoughCutSearchHit] = []
                if beat_index + 1 < len(visual_beats):
                    adjacent.extend(await self._search_s_and_a(
                        visual_beats[beat_index + 1], active_pack, units, clips,
                        video_ids, resolved_top_k, allow_tail_text=False,
                    ))
                hits = self._merge_adjacent_candidates(hits, adjacent)

            # Director/media filters can reject all semantic candidates after
            # retrieval. Re-enter the neutral fallback chain so valid source
            # footage is still available and explicitly labelled as fallback.
            if not hits or not any(
                getattr(hit, "source_end_ms", 0) > getattr(hit, "source_start_ms", 0)
                for hit in hits
            ):
                neutral = getattr(self._search, "neutral_candidates", None)
                if callable(neutral):
                    try:
                        hits = await neutral(
                            limit=max(resolved_top_k, 100), video_ids=video_ids,
                            needed_duration_ms=beat.target_duration_ms,
                        )
                    except TypeError:
                        hits = await neutral(limit=max(resolved_top_k, 100), video_ids=video_ids)

            usable_hits = [
                hit for hit in hits if hit.source_end_ms > hit.source_start_ms
                and hit.video_id in allowed_video_ids
            ]
            scoped_video_ids = set(video_ids or [])
            used_video_ids = {clip.video_id for clip in clips}
            prefer_continuation = bool(
                previous_clip is not None
                and scoped_video_ids
                and len(visual_beats) - beat_index > len(scoped_video_ids - used_video_ids)
            )
            if not usable_hits and beat_director_importance != "B":
                # 素材库没有可读可用画面（无视频 / 时间范围非法）属数据完整性
                # 错误，此时阻止出片；匹配质量差不会走到这里（本地检索自带
                # generic/source 降级兜底，保证有素材时一定出片）。
                raise RoughCutRetrievalError(
                    f"文案第 {beat.sequence + 1} 段没有通过画面复核的可用素材：{beat.text}。"
                    "请补充素材或扩大检索范围；未使用不匹配画面填充。"
                )

            try:
                beat_clips, previous_clip = self._fill_beat(
                    beat, usable_hits, reuse_counts, previous_clip,
                    prior_clips=clips, batch_usage=batch_usage, batch_index=batch_index,
                    prefer_continuation=prefer_continuation,
                    anchor_target_offset_ms=anchor_target_offset_ms,
                )
            except RoughCutRetrievalError:
                # Semantic/director filtering can leave no capacity even when
                # raw retrieval returned ranges. Use explicit neutral/source
                # fallback for this sentence before declaring corruption.
                neutral = getattr(self._search, "neutral_candidates", None)
                if not callable(neutral):
                    raise
                # The neutral pool is local-only and may contain many ranges
                # from the same source. Fetch enough candidates to preserve
                # video cooldown without changing semantic Top-K or shot count.
                try:
                    fallback_hits = await neutral(
                        limit=max(resolved_top_k, 100), video_ids=video_ids,
                        needed_duration_ms=beat.target_duration_ms,
                    )
                except TypeError:
                    fallback_hits = await neutral(
                        limit=max(resolved_top_k, 100), video_ids=video_ids,
                    )
                continuation = getattr(self._search, "continuation_candidates", None)
                if previous_clip is not None and callable(continuation):
                    try:
                        continued = await continuation(
                            previous_clip, limit=max(resolved_top_k, 100),
                            needed_duration_ms=beat.target_duration_ms,
                        )
                    except TypeError:
                        continued = await continuation(
                            previous_clip, limit=max(resolved_top_k, 100),
                        )
                    fallback_hits = self._merge_adjacent_candidates(
                        fallback_hits, continued,
                    )
                fallback_hits = [
                    hit for hit in fallback_hits
                    if hit.source_end_ms > hit.source_start_ms
                    and hit.video_id in allowed_video_ids
                ]
                beat_clips, previous_clip = self._fill_beat(
                    beat, fallback_hits, reuse_counts, previous_clip,
                    prior_clips=clips, batch_usage=batch_usage, batch_index=batch_index,
                    prefer_continuation=prefer_continuation,
                    anchor_target_offset_ms=anchor_target_offset_ms,
                )
            clips.extend(beat_clips)
            levels = {clip.schedule_level for clip in beat_clips}
            if levels - {"exact"}:
                labels = {"short": "使用较短的完整原镜头", "related": "使用同主体辅助配图",
                          "text_heavy": "匹配画面含大字，已降低使用优先级",
                          "generic": "通用素材兜底，中性画面",
                          "source": "库内兜底配图，未确认具体内容匹配",
                          "c_tail": "黑底文字与口播匹配，仅作低优先级片尾画面",
                          "reuse": "唯一画面时长不足，受控复用"}
                scheduling_warnings.append(f"第 {beat.sequence+1} 段自动调度：" +
                    "；".join(labels[level] for level in sorted(levels) if level in labels))

        clips = self._coalesce_short_clips(clips, beats)
        scheduling_warnings.extend(self._validate_video_cooldown(clips, beats))
        self._validate_timeline(clips, track.duration_ms)

        from clipatlas.roughcut.subtitles import build_subtitles

        # 字幕绑定旁白锁定时的规则版本（rule_pack_revision），不读取当前
        # active 规则：旧旁白重新导出时字幕不会随规则修改而变化。
        locked_rule_revision = getattr(source_track, "rule_pack_revision", None)
        pack_for_subtitles = None
        if self._rule_store is not None:
            if locked_rule_revision is not None:
                pack_for_subtitles = self._rule_store.get_by_revision(
                    project_id, locked_rule_revision,
                )
                if pack_for_subtitles is None:
                    raise RoughCutConfigurationError(
                        f"旁白锁定的规则版本 {locked_rule_revision} 已丢失，"
                        "不能用当前规则替代生成字幕"
                    )
            else:
                pack_for_subtitles = self._rule_store.get_active(project_id)
        # Subtitles are always generated; a missing rule pack simply means the
        # subtitle projection is an identity operation (source text as-is).
        subtitles = build_subtitles(beats, pack_for_subtitles)
        story_provenance = (
            self._build_story_provenance(story_outline, beats, clips)
            if story_outline is not None else None
        )

        plan = RoughCutPlan(
            id=plan_id or uuid4(),
            project_id=project_id,
            narration_track_id=track.id,
            narration_revision=track.revision,
            revision=self._store.next_plan_revision(project_id),
            total_duration_ms=track.duration_ms,
            settings=resolved_settings,
            beats=beats,
            clips=clips,
            subtitles=subtitles,
            warnings=scheduling_warnings,
            quality_report=build_quality_report(clips, beats, track.duration_ms, batch_usage),
            story_provenance=story_provenance,
            protocol_version="roughcut-v2-candidate-recall",
            retrieval_protocol_version="visual-retrieval-v2",
        )
        if persist:
            self._store.save_plan(plan)
        if persist and activate and not self._store.activate_plan(project_id, plan.id):
            raise RoughCutPlanningError("Failed to activate persisted rough-cut plan")
        if persist and activate and narration_track_id is None and track.id != source_track_id:
            current = self._narration_store.get_active_track(project_id)
            if current is not None and current.id == source_track_id:
                self._narration_store.activate_track(project_id, track.id)
        return plan

    @staticmethod
    def _build_story_beats(
        track: NarrationTrack,
        units: list[NarrationUnit],
        outline: StoryOutline,
        node_unit_ids: dict[UUID, list[UUID]],
    ) -> list[ScriptBeat]:
        """Resolve confirmed story nodes directly onto program time."""
        if outline.project_id != track.project_id:
            raise RoughCutConfigurationError("Story outline belongs to another project")
        if outline.status != "confirmed":
            raise RoughCutConfigurationError("Story outline must be confirmed")

        outline_node_ids = {node.id for node in outline.nodes}
        if set(node_unit_ids) != outline_node_ids:
            raise RoughCutConfigurationError(
                "Story node narration mapping must cover the confirmed outline exactly"
            )

        unit_by_id = {unit.id: unit for unit in units}
        used_unit_ids: set[UUID] = set()
        beats: list[ScriptBeat] = []
        cursor_ms = 0

        for node in sorted(outline.nodes, key=lambda item: item.order):
            mapped_ids = node_unit_ids[node.id]
            base_intent: dict[str, object] = {
                "story_node_id": str(node.id),
                "story_order": node.order,
                "story_role": node.role,
                "story_evidence": [
                    item.model_dump(mode="json") for item in node.evidence
                ],
            }
            if not mapped_ids:
                end_ms = cursor_ms + node.estimated_duration_ms
                beats.append(
                    ScriptBeat(
                        project_id=track.project_id,
                        narration_track_id=track.id,
                        sequence=len(beats),
                        kind="visual_only",
                        text="",
                        timeline_start_ms=cursor_ms,
                        timeline_end_ms=end_ms,
                        target_duration_ms=node.estimated_duration_ms,
                        query_text=node.summary,
                        retrieval_intent={
                            **base_intent,
                            "timeline_start_ms": cursor_ms,
                        },
                    )
                )
                cursor_ms = end_ms
                continue

            mapped_units: list[NarrationUnit] = []
            for unit_id in mapped_ids:
                unit = unit_by_id.get(unit_id)
                if unit is None or unit.track_id != track.id:
                    raise RoughCutConfigurationError(
                        "Story node references a missing narration unit"
                    )
                if unit_id in used_unit_ids:
                    raise RoughCutConfigurationError(
                        "Narration unit cannot belong to multiple story nodes"
                    )
                if unit.start_ms is None or unit.end_ms is None:
                    raise RoughCutConfigurationError(
                        "Story narration unit is missing authoritative timing"
                    )
                mapped_units.append(unit)
                used_unit_ids.add(unit_id)

            for unit in sorted(mapped_units, key=lambda item: (item.start_ms or 0, item.sequence)):
                assert unit.start_ms is not None
                assert unit.end_ms is not None
                duration_ms = unit.end_ms - unit.start_ms
                end_ms = cursor_ms + duration_ms
                beats.append(
                    ScriptBeat(
                        project_id=track.project_id,
                        narration_track_id=track.id,
                        sequence=len(beats),
                        text=unit.text.strip(),
                        timeline_start_ms=cursor_ms,
                        timeline_end_ms=end_ms,
                        target_duration_ms=duration_ms,
                        query_text=unit.text.strip(),
                        retrieval_intent={
                            **base_intent,
                            "timeline_start_ms": cursor_ms,
                            "_story_source_unit_id": str(unit.id),
                        },
                    )
                )
                cursor_ms = end_ms

        return beats

    @staticmethod
    def _story_audio_needs_materialization(
        track: NarrationTrack,
        units: list[NarrationUnit],
        beats: list[ScriptBeat],
    ) -> bool:
        if not beats:
            return False
        if track.audio_uri is None and any(unit.audio_uri for unit in units):
            return True
        if not any(beat.kind == "visual_only" for beat in beats):
            return False
        if track.duration_ms != beats[-1].timeline_end_ms:
            return True
        unit_by_id = {str(unit.id): unit for unit in units}
        for beat in beats:
            if beat.kind != "narration":
                continue
            source_unit_id = str(
                beat.retrieval_intent.get("_story_source_unit_id") or ""
            )
            unit = unit_by_id.get(source_unit_id)
            if unit is None:
                return True
            if (
                unit.start_ms != beat.timeline_start_ms
                or unit.end_ms != beat.timeline_end_ms
            ):
                return True
        return False

    @staticmethod
    def _local_audio_path(uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme not in {"", "file"}:
            raise RoughCutConfigurationError(
                "Story audio materialization requires a local file audio URI"
            )
        if not parsed.scheme:
            return Path(uri)
        raw_path = unquote(parsed.path)
        if parsed.netloc:
            raw_path = f"//{parsed.netloc}{raw_path}"
        # pathlib on Windows expects D:/... rather than /D:/... from file URI.
        if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]
        return Path(raw_path)

    async def _materialize_story_audio(
        self,
        source_track: NarrationTrack,
        source_units: list[NarrationUnit],
        beats: list[ScriptBeat],
    ) -> tuple[NarrationTrack, list[NarrationUnit], list[ScriptBeat]]:
        if self._story_audio_root is None:
            raise RoughCutConfigurationError(
                "Story audio output root is not configured"
            )
        if not beats:
            raise RoughCutConfigurationError("Story execution produced no program windows")

        audio = self._audio_normalizer or AudioNormalizer()
        total_duration_ms = beats[-1].timeline_end_ms
        new_track_id = uuid4()
        track_root = self._story_audio_root / str(source_track.project_id) / str(new_track_id)
        parts_root = track_root / "parts"
        final_audio_path = track_root / "story.wav"
        unit_by_id = {str(unit.id): unit for unit in source_units}
        source_audio_path = (
            self._local_audio_path(source_track.audio_uri)
            if source_track.audio_uri else None
        )

        parts: list[Path] = []
        final_units: list[NarrationUnit] = []
        for index, beat in enumerate(beats):
            part_path = parts_root / f"{index:04d}.wav"
            if beat.kind == "visual_only":
                await audio.silence(
                    part_path,
                    duration_ms=beat.target_duration_ms,
                )
            else:
                source_unit_id = str(
                    beat.retrieval_intent.get("_story_source_unit_id") or ""
                )
                source_unit = unit_by_id.get(source_unit_id)
                if source_unit is None:
                    raise RoughCutConfigurationError(
                        "Story narration beat lost its prepared source unit"
                    )
                if source_unit.start_ms is None or source_unit.end_ms is None:
                    raise RoughCutConfigurationError(
                        "Story narration source unit has no authoritative timing"
                    )
                if source_audio_path is not None:
                    await audio.extract(
                        source_audio_path,
                        part_path,
                        start_ms=source_unit.start_ms,
                        end_ms=source_unit.end_ms,
                    )
                elif source_unit.audio_uri:
                    await audio.extract(
                        self._local_audio_path(source_unit.audio_uri),
                        part_path,
                        start_ms=0,
                        end_ms=source_unit.end_ms - source_unit.start_ms,
                    )
                else:
                    raise RoughCutConfigurationError(
                        "Prepared narration audio is unavailable for Story execution"
                    )
                final_units.append(
                    source_unit.model_copy(update={
                        "id": uuid4(),
                        "track_id": new_track_id,
                        "sequence": len(final_units),
                        "start_ms": beat.timeline_start_ms,
                        "end_ms": beat.timeline_end_ms,
                        "audio_uri": part_path.resolve().as_uri(),
                        "created_at": utc_now(),
                    })
                )
            parts.append(part_path)

        await audio.concat(parts, final_audio_path)
        actual_duration_ms = await audio.probe_duration_ms(final_audio_path)
        if actual_duration_ms != total_duration_ms:
            raise RoughCutPlanningError(
                "Story narration audio duration does not match program duration"
            )

        final_track = source_track.model_copy(update={
            "id": new_track_id,
            "audio_uri": final_audio_path.resolve().as_uri(),
            "duration_ms": total_duration_ms,
            "timing_quality": TimingQuality.UNIT_EXACT,
            "revision": self._narration_store.next_track_revision(source_track.project_id),
            "created_at": utc_now(),
        })
        self._narration_store.save_track(final_track)
        for unit in final_units:
            self._narration_store.save_unit(unit)

        retimed_beats = [
            beat.model_copy(update={"narration_track_id": final_track.id})
            for beat in beats
        ]
        return final_track, final_units, retimed_beats

    @staticmethod
    def _strip_story_execution_internals(
        beats: list[ScriptBeat],
    ) -> list[ScriptBeat]:
        stripped: list[ScriptBeat] = []
        for beat in beats:
            intent = {
                key: value
                for key, value in beat.retrieval_intent.items()
                if not key.startswith("_story_")
            }
            stripped.append(beat.model_copy(update={"retrieval_intent": intent}))
        return stripped

    @staticmethod
    def _build_story_provenance(
        outline: StoryOutline,
        beats: list[ScriptBeat],
        clips: list[RoughCutClip],
    ) -> dict[str, object]:
        executed_nodes: list[dict[str, object]] = []
        for node in sorted(outline.nodes, key=lambda item: item.order):
            node_id = str(node.id)
            node_beats = [
                beat for beat in beats
                if str(beat.retrieval_intent.get("story_node_id") or "") == node_id
            ]
            if not node_beats:
                raise RoughCutPlanningError(
                    f"Story node {node.id} was lost during rough-cut execution"
                )
            beat_ids = {beat.id for beat in node_beats}
            node_clips = [clip for clip in clips if clip.beat_id in beat_ids]
            executed_nodes.append({
                "story_node_id": node_id,
                "story_order": node.order,
                "program_start_ms": min(beat.timeline_start_ms for beat in node_beats),
                "program_end_ms": max(beat.timeline_end_ms for beat in node_beats),
                "beat_ids": [str(beat.id) for beat in node_beats],
                "clips": [
                    {
                        "beat_id": str(clip.beat_id),
                        "segment_id": str(clip.segment_id),
                        "video_id": str(clip.video_id),
                        "source_in_ms": clip.source_in_ms,
                        "source_out_ms": clip.source_out_ms,
                        "timeline_in_ms": clip.timeline_in_ms,
                        "timeline_out_ms": clip.timeline_out_ms,
                    }
                    for clip in node_clips
                ],
                "evidence": [
                    {
                        "evidence_id": evidence.evidence_id,
                        "start_ms": evidence.start_ms,
                        "end_ms": evidence.end_ms,
                    }
                    for evidence in node.evidence
                ],
            })
        return {
            "outline_id": str(outline.id),
            "outline_revision": outline.revision,
            "executed_nodes": executed_nodes,
        }

    @staticmethod
    def _attach_visual_requirements(
        beats: list[ScriptBeat], requirements: list[Any],
    ) -> list[ScriptBeat]:
        """Attach source-grounded requirements without changing shot boundaries."""
        if not requirements:
            return beats
        attached: list[ScriptBeat] = []
        for beat in beats:
            matches = [
                requirement.model_dump(mode="json")
                for requirement in requirements
                if requirement.source_quote.strip() in beat.text
            ]
            if matches:
                intent = dict(beat.retrieval_intent)
                intent["visual_requirements"] = matches
                attached.append(beat.model_copy(update={"retrieval_intent": intent}))
            else:
                attached.append(beat)
        return attached

    @staticmethod
    def _attach_director_units(
        beats: list[ScriptBeat], units: list[DirectorUnit],
    ) -> list[ScriptBeat]:
        beat_units: dict[int, list[DirectorUnit]] = defaultdict(list)
        for unit in units:
            if unit.beat_range is None:
                continue
            start, end = unit.beat_range
            for index in range(start, end + 1):
                if 0 <= index < len(beats):
                    beat_units[index].append(unit)
        updated: list[ScriptBeat] = []
        for index, beat in enumerate(beats):
            attached = beat_units.get(index, [])
            if not attached:
                updated.append(beat)
                continue
            importance = max(
                (unit.importance for unit in attached),
                key=_IMPORTANCE_ORDER.index,
            )
            intent = dict(beat.retrieval_intent)
            intent["director_units"] = [unit.model_dump(mode="json") for unit in attached]
            intent["director_importance"] = importance
            updated.append(beat.model_copy(update={"retrieval_intent": intent}))
        return updated

    @staticmethod
    def _beat_director_key(beat: ScriptBeat) -> tuple[str, str] | None:
        """Return (importance, topic) when the beat carries a director unit."""
        intent = beat.retrieval_intent or {}
        importance = intent.get("director_importance")
        units = intent.get("director_units") or []
        if not importance or not units:
            return None
        topic = str(units[0].get("topic") or "")
        if not topic:
            return None
        return str(importance), topic

    @staticmethod
    def _s_match_keywords(beat: ScriptBeat) -> list[str]:
        """S 级整段 OCR 匹配词：核心对象/动作/主题 + 口播中的数字单位。"""
        intent = beat.retrieval_intent or {}
        if intent.get("director_importance") != "S":
            return []
        keywords: list[str] = []
        for unit in intent.get("director_units") or []:
            if not isinstance(unit, dict) or unit.get("importance") != "S":
                continue
            for key in ("must_have", "preferred", "topic", "subtopics",
                        "required_objects", "required_actions", "required_subjects"):
                value = unit.get(key)
                if isinstance(value, str):
                    keywords.append(value)
                elif isinstance(value, (list, tuple)):
                    keywords.extend(str(v) for v in value)
        # 口播数字 + 常见单位（200万 / 0.05毫米 / 86% / 2000兆帕）。
        keywords.extend(
            re.findall(
                r"\d+(?:\.\d+)?\s*(?:%|％|万|[wW]|亿|千|兆帕|毫米|厘米|米|公里|"
                r"km|KM|马力|度|个|位|台|款|年)?", beat.text,
            )
        )
        seen: set[str] = set()
        ordered: list[str] = []
        for kw in keywords:
            kw = str(kw).strip()
            if kw and kw not in seen:
                seen.add(kw)
                ordered.append(kw)
        return ordered

    @classmethod
    def _merge_director_beats(cls, beats: list[ScriptBeat]) -> list[ScriptBeat]:
        """Keep the sentence windows produced by ``BeatBuilder`` intact.

        Director grades decide which footage anchors a sentence, not where a
        grammatical sentence is cut. B sentences can reuse adjacent S footage
        without erasing the sentence boundary.
        """
        return [beat.model_copy(update={"sequence": index}) for index, beat in enumerate(beats)]

    @staticmethod
    def _primary_director_unit(beat: ScriptBeat) -> dict[str, Any] | None:
        intent = beat.retrieval_intent or {}
        importance = str(intent.get("director_importance") or "")
        candidates = [
            unit for unit in intent.get("director_units") or []
            if isinstance(unit, dict)
            and unit.get("importance") == importance
            and isinstance(unit.get("beat_range"), (list, tuple))
            and len(unit["beat_range"]) == 2
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda unit: (
                int(unit["beat_range"][1]) - int(unit["beat_range"][0]),
                int(unit["beat_range"][0]),
                str(unit.get("topic") or ""),
            ),
        )

    @classmethod
    def _build_visual_beats(
        cls, beats: list[ScriptBeat], *, maximum_window_ms: int = 20_000,
    ) -> list[ScriptBeat]:
        """Group sentence beats for visual planning without changing narration."""
        if not beats:
            return []

        def key(beat: ScriptBeat) -> tuple[object, ...] | None:
            unit = cls._primary_director_unit(beat)
            if unit is None:
                return None
            beat_range = unit["beat_range"]
            return (
                beat.retrieval_intent.get("story_node_id"),
                unit.get("importance"), unit.get("topic"), unit.get("text_range"),
                int(beat_range[0]), int(beat_range[1]),
            )

        grouped: list[ScriptBeat] = []
        index = 0
        while index < len(beats):
            first = beats[index]
            unit_key = key(first)
            end = index + 1
            while unit_key is not None and end < len(beats) and key(beats[end]) == unit_key:
                if beats[end].timeline_end_ms - first.timeline_start_ms > maximum_window_ms:
                    break
                end += 1
            members = beats[index:end]
            if len(members) == 1:
                grouped.append(first)
            else:
                intent = dict(first.retrieval_intent)
                intent.update({
                    "visual_beat_ids": [str(member.id) for member in members],
                    "visual_beat_sequences": [member.sequence for member in members],
                    "visual_unit_size": len(members),
                })
                text = "\n".join(member.text for member in members)
                grouped.append(first.model_copy(update={
                    "text": text,
                    "query_text": text,
                    "timeline_end_ms": members[-1].timeline_end_ms,
                    "target_duration_ms": members[-1].timeline_end_ms - first.timeline_start_ms,
                    "retrieval_intent": intent,
                }))
            index = end
        return grouped

    @staticmethod
    def _beat_director_units(beat: ScriptBeat) -> tuple[list[DirectorUnit], str | None]:
        raw = beat.retrieval_intent.get("director_units") or []
        importance = beat.retrieval_intent.get("director_importance")
        try:
            units = [DirectorUnit(**item) for item in raw]
        except (TypeError, ValueError):
            return [], None
        return units, importance

    @staticmethod
    def _merge_adjacent_candidates(
        current: list[RoughCutSearchHit], adjacent: list[RoughCutSearchHit],
    ) -> list[RoughCutSearchHit]:
        """Add previous/next sentence footage as continuity, never as exact."""
        merged = list(current)
        seen = {
            (hit.video_id, hit.source_start_ms, hit.source_end_ms)
            for hit in current
        }
        for hit in adjacent:
            key = (hit.video_id, hit.source_start_ms, hit.source_end_ms)
            if key in seen:
                continue
            seen.add(key)
            if hasattr(hit, "model_copy"):
                hit = hit.model_copy(update={
                    "schedule_level": "related",
                    "query_relevance_reason": "相邻完整句连续过渡画面",
                })
            merged.append(hit)
        return merged

    @staticmethod
    def _reject_director_mismatches(
        hits: list[RoughCutSearchHit],
        s_units: list[DirectorUnit],
        a_units: list[DirectorUnit],
    ) -> list[RoughCutSearchHit]:
        """Hard filter: a visibly wrong core object can never be compensated.

        Fallback shots (``source``/``generic``) are exempt: they are
        content-unverified or neutral padding by design, and the "must produce
        a draft" rule wins over rejecting them.
        """
        units = s_units or a_units
        if not units:
            return hits
        kept: list[RoughCutSearchHit] = []
        for hit in hits:
            if getattr(hit, "schedule_level", "exact") in ("source", "generic"):
                kept.append(hit)
                continue
            annotation = getattr(hit, "annotation", None)
            if annotation is None:
                kept.append(hit)
                continue
            verdicts = [DirectorService.fit(unit, annotation) for unit in units]
            if any(verdict.level == "REJECT" for verdict in verdicts):
                logger.info(
                    "roughcut director reject units=%s hit=%s",
                    [unit.topic for unit in units], hit.segment_id,
                )
                continue
            kept.append(hit)
        return kept

    @staticmethod
    def _fit_priority(
        hit: RoughCutSearchHit,
        s_units: list[DirectorUnit],
    ) -> int:
        if not s_units:
            return 0
        annotation = getattr(hit, "annotation", None)
        if annotation is None:
            return _FIT_PRIORITY["UNKNOWN"]
        verdicts = [DirectorService.fit(unit, annotation) for unit in s_units]
        if any(verdict.level == "REJECT" for verdict in verdicts):
            return 99
        claim_matches = [match for verdict in verdicts for match in verdict.claim_matches]
        if any(match.level == "DIRECT" for match in claim_matches):
            return _FIT_PRIORITY["DIRECT"]
        if any(match.level == "SUPPORT" for match in claim_matches):
            return _FIT_PRIORITY["SUPPORT"]
        levels = [verdict.level for verdict in verdicts]
        if levels and all(level == "DIRECT" for level in levels):
            return _FIT_PRIORITY["DIRECT"]
        if any(level in {"DIRECT", "SUPPORT"} for level in levels):
            return _FIT_PRIORITY["SUPPORT"]
        return _FIT_PRIORITY["UNKNOWN"]

    @staticmethod
    def _director_fit_details(
        s_units: list[DirectorUnit], annotation: Any,
    ) -> tuple[str | None, list[str], list[str]]:
        if not s_units:
            return None, [], []
        verdict = DirectorService.fit(s_units[0], annotation)
        matched = list(dict.fromkeys([
            *verdict.matched_must_have,
            *verdict.matched_subjects,
            *verdict.matched_objects,
            *verdict.matched_actions,
            *verdict.matched_surrogates,
        ]))
        return verdict.level, matched, verdict.missing_must_have

    async def _search_s_and_a(
        self,
        beat: ScriptBeat,
        active_pack: Any,
        units: list[Any],
        clips: list[RoughCutClip],
        video_ids: list[UUID] | None,
        limit: int,
        *, allow_tail_text: bool = False,
    ) -> list[RoughCutSearchHit]:
        """S/A 级检索：本地事实召回 + ASR/OCR + 本地兜底，零网络请求。"""
        retrieval_query = beat.query_text
        retrieval_context: dict[str, object] | None = None
        if active_pack is not None:
            projected = self._rule_projector.project(beat.query_text, active_pack)
            retrieval_query = projected.retrieval_text
            if (
                retrieval_query != beat.query_text
                or projected.semantic_hints
            ):
                retrieval_context = {
                    "base_retrieval_query": retrieval_query,
                    "semantic_hints": projected.semantic_hints,
                }

        contextual_search = getattr(self._search, "search_with_context", None)
        if callable(contextual_search):
            retrieval_context = {
                **(retrieval_context or {}), "rough_cut": True,
                "narration_context": "\n".join(unit.text for unit in units)[:6000],
                "needed_duration_ms": beat.target_duration_ms,
                "minimum_shot_ms": min(MIN_SHOT_MS, beat.target_duration_ms),
                **({"retrieval_intent": beat.retrieval_intent} if beat.retrieval_intent else {}),
                "director_importance": beat.retrieval_intent.get("director_importance"),
                "s_keywords": self._s_match_keywords(beat),
                "allow_tail_text": allow_tail_text,
                "excluded_ranges": [{"video_id": str(c.video_id), "start_ms": c.source_in_ms,
                                     "end_ms": c.source_out_ms} for c in clips],
            }
        if retrieval_context is not None and callable(contextual_search):
            hits = await contextual_search(
                beat.query_text,
                context=retrieval_context,
                limit=limit,
                video_ids=video_ids,
            )
            beat.retrieval_intent["candidate_matrix"] = [
                row.model_dump(mode="json") for row in build_candidate_matrix(beat, list(hits))
            ]
            return hits
        hits = await self._search.search(
            retrieval_query,
            limit=limit,
            video_ids=video_ids,
        )
        beat.retrieval_intent["candidate_matrix"] = [
            row.model_dump(mode="json") for row in build_candidate_matrix(beat, list(hits))
        ]
        return hits

    async def _search_b_level(
        self,
        beat: ScriptBeat,
        previous_clip: RoughCutClip | None,
        limit: int,
        video_ids: list[UUID] | None,
    ) -> list[RoughCutSearchHit]:
        """B 级不独立检索：借前一个 S/A 的安全后续范围，其次同主体中性素材。"""
        hits: list[RoughCutSearchHit] = []
        continuation = getattr(self._search, "continuation_candidates", None)
        if previous_clip is not None and callable(continuation):
            hits = await continuation(previous_clip, limit=limit)
        if not hits:
            neutral = getattr(self._search, "neutral_candidates", None)
            if callable(neutral):
                hits = await neutral(limit=limit, video_ids=video_ids)
        logger.info(
            "roughcut B-level beat=%s no_search=True hits=%s prev=%s",
            beat.sequence + 1, len(hits),
            previous_clip.video_id if previous_clip is not None else None,
        )
        return hits

    def _b_level_extension(
        self,
        beat: ScriptBeat,
        previous_clip: RoughCutClip | None,
    ) -> tuple[list[RoughCutClip], RoughCutClip | None] | None:
        """B 级最后兜底：库内无可用画面时受控复用前镜（等长窗口），
        不产生碎片、不越界；前镜也不存在则返回 None（数据完整性错误）。"""
        if previous_clip is None:
            return None
        window_ms = beat.timeline_end_ms - beat.timeline_start_ms
        prev_len = previous_clip.source_out_ms - previous_clip.source_in_ms
        if prev_len >= window_ms:
            source_in = previous_clip.source_in_ms
            source_out = source_in + window_ms
        else:
            source_out = previous_clip.source_out_ms
            source_in = source_out - window_ms
            if source_in < previous_clip.source_in_ms:
                return None
        clip = RoughCutClip(
            beat_id=beat.id,
            segment_id=previous_clip.segment_id,
            video_id=previous_clip.video_id,
            source_uri=previous_clip.source_uri,
            source_in_ms=source_in,
            source_out_ms=source_out,
            protocol_candidate_type=previous_clip.protocol_candidate_type,
            protocol_id=previous_clip.protocol_id,
            continuity_status=previous_clip.continuity_status,
            timeline_in_ms=beat.timeline_start_ms,
            timeline_out_ms=beat.timeline_end_ms,
            score=0.0,
            schedule_level="reuse",
            selection_reason="B 级延展兜底：库内无可用画面，受控复用前镜（请补通用素材）",
            score_breakdown=CandidateScore(
                segment_id=previous_clip.segment_id,
                semantic_score=0.0, action_score=0.0, scene_score=0.0,
                emotion_score=0.0, duration_fit_score=0.0, quality_score=0.0,
                numeric_score=0.0, continuity_bonus=0.0, reuse_penalty=0.0,
                total_score=0.0,
            ),
        )
        return [clip], previous_clip

    def _fill_beat(
        self,
        beat: ScriptBeat,
        hits: list[RoughCutSearchHit],
        reuse_counts: dict[UUID, int],
        previous_clip: RoughCutClip | None,
        prior_clips: list[RoughCutClip] | None = None,
        batch_usage: dict[str, list[tuple[int, int, int]]] | None = None,
        batch_index: int = 0,
        prefer_continuation: bool = False,
        anchor_target_offset_ms: int | None = None,
    ) -> tuple[list[RoughCutClip], RoughCutClip | None]:
        if not hits:
            director_units, director_importance = self._beat_director_units(beat)
            if director_importance == "B":
                extended = self._b_level_extension(beat, previous_clip)
                if extended is not None:
                    return extended
                raise RoughCutRetrievalError(
                    f"文案第 {beat.sequence + 1} 段（B 级）无可用画面且无前镜可延展：{beat.text}。"
                )
        total_ms = beat.target_duration_ms
        valid_hits = [hit for hit in hits if hit.source_end_ms > hit.source_start_ms]
        if not valid_hits:
            raise RoughCutRetrievalError(
                f"文案第 {beat.sequence + 1} 段没有合法源时间范围：{beat.text}。"
            )
        hits = valid_hits
        allow_reuse = any(getattr(h, "schedule_level", "exact") == "reuse" for h in hits)
        # A weak match is not a reason to create 1-second fragments. Keep a
        # complete sentence visually stable; use one longer fallback shot when
        # semantic snippets cannot satisfy the normal minimum duration.
        minimum_ms = min(MIN_SHOT_MS, total_ms)
        if allow_reuse:
            longest = max(min(MAX_SHOT_MS, h.source_end_ms-h.source_start_ms) for h in hits)
            # Keep normal sentence minimum even for reuse; only a genuinely
            # short source range may produce a shorter shot.
            minimum_ms = min(minimum_ms, total_ms // max(1, ceil(total_ms/longest)))
        timeline_cursor_ms = beat.timeline_start_ms
        clips: list[RoughCutClip] = []
        used_families = self._used_families(prior_clips)
        base_pool = [
            hit
            for hit in hits
            if hit.source_end_ms - hit.source_start_ms >= minimum_ms
            and (
                getattr(hit, "schedule_level", "exact") == "reuse"
                or not any(
                    hit.video_id == c.video_id
                    and hit.source_start_ms < c.source_out_ms
                    and hit.source_end_ms > c.source_in_ms
                    for c in (prior_clips or [])
                )
            )
        ]
        family_filtered = [
            hit
            for hit in base_pool
            if not self._family_conflict(hit, prior_clips, used_families)
        ]
        # The family rule prefers not to repeat the same visual family, but the
        # "must produce a draft" rule wins when the family filter leaves no
        # usable footage at all.
        pool = family_filtered if family_filtered else base_pool

        director_units, director_importance = self._beat_director_units(beat)
        s_units = [unit for unit in director_units if unit.importance == "S"]
        a_units = [unit for unit in director_units if unit.importance == "A"]
        # Every grammatical sentence prefers one continuous shot. S controls
        # match strictness, not whether other grades are allowed to stay whole.
        max_shot_ms = total_ms
        if director_units:
            pool = self._reject_director_mismatches(pool, s_units, a_units)
        if prefer_continuation and previous_clip is not None:
            nearby = [
                hit for hit in pool
                if hit.video_id == previous_clip.video_id
                and min(
                    abs(hit.source_start_ms - previous_clip.source_out_ms),
                    abs(previous_clip.source_in_ms - hit.source_end_ms),
                ) <= self._settings.continuity_window_ms
            ]
            fresh_s_direct = any(
                getattr(hit, "schedule_level", "exact") == "exact"
                and hit.video_id != previous_clip.video_id
                and director_importance == "S"
                and self._fit_priority(hit, s_units) == _FIT_PRIORITY["DIRECT"]
                for hit in pool
            )
            if (
                sum(min(total_ms, hit.source_end_ms - hit.source_start_ms) for hit in nearby)
                >= total_ms
                and not fresh_s_direct
            ):
                pool = nearby

        selected: list[RoughCutSearchHit] = []
        durations: list[int] | None = None
        best: tuple[tuple[int, int], list[RoughCutSearchHit], list[int]] | None = None
        shot_counts = preferred_shot_counts(
            total_ms, len(pool), minimum_ms=minimum_ms, maximum_ms=max_shot_ms,
        )
        if 1 in shot_counts:
            shot_counts = [1, *(count for count in shot_counts if count != 1)]
        for preference, count in enumerate(shot_counts):
            target = total_ms // count
            ranked = [(hit, self._scorer.score(
                beat, hit, needed_duration_ms=target,
                prior_use_count=reuse_counts.get(hit.segment_id, 0), previous_clip=previous_clip,
            )) for hit in pool]
            # S-tier beats must prefer DIRECT evidence: a wrong core object is
            # already gone (REJECT), and DIRECT outranks SUPPORT/UNKNOWN here.
            priority_units = s_units or a_units
            fit_priority = {id(hit): self._fit_priority(hit, priority_units) for hit in pool}
            prior_video_ids = {prior.video_id for prior in prior_clips or []}
            fresh_s_direct_exists = any(
                hit.video_id not in prior_video_ids
                and getattr(hit, "schedule_level", "exact") == "exact"
                and director_importance == "S"
                and fit_priority.get(id(hit)) == _FIT_PRIORITY["DIRECT"]
                for hit in pool
            )
            # 批次级去重：滚动窗口内被本批次其它成片占用的片段，降一级并扣分。
            # S 级 DIRECT 只轻罚（稀缺画面尽量换，换不到仍可复用）；非 DIRECT
            # 全额避让，优先换未占用画面。
            _settings = getattr(self, "_settings", None) or PlannerSettings()
            _reuse_gap = _settings.batch_reuse_gap
            _reuse_penalty = _settings.batch_reuse_penalty_per_use
            _reuse_direct_scale = _settings.batch_reuse_direct_penalty_scale
            occupancy = {
                id(hit): batch_occupancy_for(
                    hit, batch_usage,
                    current_index=batch_index,
                    gap=_reuse_gap,
                )
                for hit in pool
            }
            batch_video_uses = {
                id(hit): len(batch_usage.get(str(hit.video_id), []))
                if batch_usage else 0
                for hit in pool
            }
            current_video_ms = defaultdict(int)
            for prior in prior_clips or []:
                current_video_ms[prior.video_id] += prior.timeline_out_ms - prior.timeline_in_ms
            last_video_id = previous_clip.video_id if previous_clip is not None else None

            def _adjusted_fit(hit: RoughCutSearchHit) -> tuple[int, float]:
                occ = occupancy.get(id(hit), 0)
                base_fit = fit_priority.get(id(hit), 0)
                direct_scale = (
                    _reuse_direct_scale
                    if base_fit == _FIT_PRIORITY["DIRECT"] else 1.0
                )
                diversity_penalty = (
                    occ * _reuse_penalty * direct_scale
                    + batch_video_uses.get(id(hit), 0) * _settings.batch_video_penalty_per_use
                    + current_video_ms[hit.video_id] / max(1, total_ms)
                )
                return (base_fit + (1 if occ else 0), diversity_penalty)

            # First prefer relevant shots that each cover the target. If capacities differ,
            # try the longer available shots before increasing the number of cuts.
            for capacity_first in (False, True):
                ordered = sorted(ranked, key=lambda item: (
                    0 if getattr(item[0], "protocol_candidate_type", None) == "window" else 1,
                    _adjusted_fit(item[0])[0],
                    {"exact": 0, "short": 0, "related": 1, "text_heavy": 2,
                     "generic": 3, "source": 4, "c_tail": 5, "reuse": 6}.get(
                        getattr(item[0], "schedule_level", "exact"), 6) if not capacity_first else 0,
                    -(min(max_shot_ms, item[0].source_end_ms - item[0].source_start_ms)
                      if capacity_first else min(target, item[0].source_end_ms - item[0].source_start_ms)),
                    _adjusted_fit(item[0])[1] - item[1].total_score, str(item[0].segment_id),
                ))
                selected = []
                for enforce_family in (True, False):
                    selected = []
                    for hit, _ in ordered:
                        current_previous = selected[-1] if selected else previous_clip
                        projected_video_ms = current_video_ms[hit.video_id] + target
                        # Enforce the per-draft source share while alternatives
                        # exist; the second pass may relax it to preserve the
                        # must-produce contract for scarce footage.
                        if enforce_family and prior_clips and (
                            projected_video_ms
                            > max(total_ms, beat.timeline_end_ms)
                            * _settings.max_video_timeline_share
                        ):
                            continue
                        if prior_clips and hit.video_id in prior_video_ids:
                            # Cooldown is a hard scheduling rule, including the
                            # relaxed family pass. A non-exact hit may continue
                            # the current video only when its source range is
                            # nearby; once the edit has left that video, only
                            # verified exact evidence may jump back remotely.
                            level = getattr(hit, "schedule_level", "exact")
                            is_unique_s_exact = (
                                level == "exact"
                                and director_importance == "S"
                                and fit_priority.get(id(hit)) == _FIT_PRIORITY["DIRECT"]
                                and not fresh_s_direct_exists
                            )
                            if not is_unique_s_exact:
                                current_video_id = (
                                    current_previous.video_id
                                    if current_previous is not None else last_video_id
                                )
                                if hit.video_id != current_video_id:
                                    continue
                                if current_previous is not None:
                                    previous_out = getattr(current_previous, "source_out_ms", None)
                                    if previous_out is None:
                                        previous_out = current_previous.source_end_ms
                                    previous_in = getattr(current_previous, "source_in_ms", None)
                                    if previous_in is None:
                                        previous_in = current_previous.source_start_ms
                                    if min(
                                        abs(hit.source_start_ms - previous_out),
                                        abs(previous_in - hit.source_end_ms),
                                    ) > _settings.continuity_window_ms:
                                        continue
                        if enforce_family and any(
                            hit.video_id == other.video_id for other in selected
                        ):
                            continue
                        if getattr(hit, "schedule_level", "exact") != "reuse" and any(
                            hit.video_id == other.video_id
                            and hit.source_start_ms < other.source_end_ms
                            and hit.source_end_ms > other.source_start_ms
                            for other in selected
                        ):
                            continue
                        if enforce_family and self._family_conflict(
                            hit, selected, self._used_families(selected)
                        ):
                            continue
                        selected.append(hit)
                        if len(selected) == count:
                            break
                    if len(selected) == count:
                        break
                if len(selected) == count:
                    durations = allocate_durations(total_ms, [
                        hit.source_end_ms - hit.source_start_ms for hit in selected
                    ], minimum_ms=minimum_ms, maximum_ms=max_shot_ms)
                    if durations is not None:
                        penalty = {"exact": 0, "short": 0, "related": 1,
                                   "text_heavy": 2, "generic": 3, "source": 4,
                                   "c_tail": 6, "reuse": 8}
                        priorities = [penalty.get(getattr(h, "schedule_level", "exact"), 0) for h in selected]
                        # Keep as much verified coverage as the source permits; only the
                        # missing portion should become supporting footage or reuse.
                        for better in sorted(range(count), key=lambda i: priorities[i]):
                            room = min(max_shot_ms, selected[better].source_end_ms-selected[better].source_start_ms) - durations[better]
                            for worse in sorted(range(count), key=lambda i: -priorities[i]):
                                if priorities[worse] <= priorities[better]:
                                    continue
                                move = min(room, max(0, durations[worse]-minimum_ms))
                                durations[better] += move
                                durations[worse] -= move
                                room -= move
                        fallback_cost = sum(duration * penalty.get(getattr(hit, "schedule_level", "exact"), 0)
                                            for hit, duration in zip(selected, durations, strict=True))
                        key = (fallback_cost, preference)
                        if best is None or key < best[0]:
                            best = (key, list(selected), durations)
                        if fallback_cost == 0:
                            break
            if best is not None and best[0][0] == 0:
                break
        if best is None:
            # 最终兜底：只要存在一个足够长的有效源范围，就用受控复用覆盖
            # 整段旁白。匹配质量只产生警告，不阻断草稿；数据完整性才阻断。
            salvage_pool = [
                hit for hit in (pool or base_pool or hits)
                if hit.source_end_ms - hit.source_start_ms >= min(300, total_ms)
            ]
            if not salvage_pool:
                raise RoughCutRetrievalError(
                    f"文案第 {beat.sequence + 1} 段没有可读的有效源画面：{beat.text}。"
                    "请检查源文件和素材时间数据。"
                )
            salvage = sorted(
                salvage_pool,
                key=lambda hit: (
                    -(hit.source_end_ms - hit.source_start_ms), str(hit.segment_id)
                ),
            )
            fallback_clips: list[RoughCutClip] = []
            cursor = timeline_cursor_ms
            remaining = total_ms
            while remaining > 0:
                forced_reuse = False
                previous_fallback = fallback_clips[-1] if fallback_clips else previous_clip
                used_videos = {clip.video_id for clip in (prior_clips or [])}
                used_videos.update(clip.video_id for clip in fallback_clips)

                def _nearby_continuation(candidate: RoughCutSearchHit) -> bool:
                    if previous_fallback is None or candidate.video_id != previous_fallback.video_id:
                        return False
                    return min(
                        abs(candidate.source_start_ms - previous_fallback.source_out_ms),
                        abs(previous_fallback.source_in_ms - candidate.source_end_ms),
                    ) <= self._settings.continuity_window_ms

                candidates = [
                    candidate for candidate in salvage
                    if not any(
                        candidate.video_id == used.video_id
                        and candidate.source_start_ms < used.source_out_ms
                        and candidate.source_end_ms > used.source_in_ms
                        for used in fallback_clips
                    )
                    and (
                        candidate.video_id not in used_videos
                        or (
                            getattr(candidate, "schedule_level", "exact") == "exact"
                            and director_importance == "S"
                            and self._fit_priority(candidate, s_units) == _FIT_PRIORITY["DIRECT"]
                        )
                        or _nearby_continuation(candidate)
                    )
                ]
                if previous_fallback is not None:
                    continuous = [
                        candidate for candidate in candidates
                        if _nearby_continuation(candidate)
                    ]
                    # Continuation is valuable, but a remote jump back to a
                    # previously used video is worse than a fresh source.
                    if continuous:
                        candidates = continuous
                if not candidates:
                    if previous_fallback is not None:
                        duration = min(
                            remaining,
                            previous_fallback.source_out_ms - previous_fallback.source_in_ms,
                        )
                        if duration > 0:
                            reused_clip = previous_fallback.model_copy(update={
                                "beat_id": beat.id,
                                "source_out_ms": previous_fallback.source_in_ms + duration,
                                "timeline_in_ms": cursor,
                                "timeline_out_ms": cursor + duration,
                                "schedule_level": "reuse",
                                "selection_reason": (
                                    f"{previous_fallback.selection_reason}; controlled reuse continuation"
                                ),
                            })
                            fallback_clips.append(reused_clip)
                            cursor += duration
                            remaining -= duration
                            previous_fallback = reused_clip
                            continue
                    # No disjoint CandidateWindow remains. Preserve the
                    # must-produce contract with an explicitly labelled reuse;
                    # never disguise overlapping source as fresh footage.
                    same_current_video = [
                        candidate for candidate in salvage
                        if previous_fallback is not None
                        and candidate.video_id == previous_fallback.video_id
                    ]
                    candidates = same_current_video or salvage
                    forced_reuse = True
                hit = max(
                    candidates,
                    key=lambda candidate: (
                        candidate.video_id != getattr(previous_fallback, "video_id", None),
                        -(candidate.source_end_ms - candidate.source_start_ms),
                        str(candidate.segment_id),
                    ),
                )
                source_capacity = min(
                    max_shot_ms, hit.source_end_ms - hit.source_start_ms
                )
                duration = min(source_capacity, remaining)
                if 0 < remaining - duration < MIN_SHOT_MS:
                    reduction = MIN_SHOT_MS - (remaining - duration)
                    if duration > reduction:
                        duration -= reduction
                if duration < min(MIN_SHOT_MS, total_ms):
                    # 收尾处理：剩余不足一个最小镜头时，优先并入上一镜
                    # （同一源素材还有余量时）；无法并入才允许短尾成镜，
                    # 保证“素材可读必出片”。源范围本身非法的情况已由
                    # salvage_pool 的 >= MIN_SHOT_MS 筛选排除。
                    if fallback_clips and 0 < remaining < MIN_SHOT_MS:
                        last = fallback_clips[-1]
                        if (
                            last.segment_id == hit.segment_id
                            and last.source_out_ms + remaining <= hit.source_end_ms
                        ):
                            last.source_out_ms += remaining
                            last.timeline_out_ms += remaining
                            cursor += remaining
                            remaining = 0
                            previous_clip = last
                            break
                    # Any positive, readable range is valid source footage.
                    # It may be a poor short shot, but controlled reuse is a
                    # quality downgrade rather than database corruption.
                reused = forced_reuse or any(
                    prior.video_id == hit.video_id
                    and hit.source_start_ms < prior.source_out_ms
                    and hit.source_end_ms > prior.source_in_ms
                    for prior in fallback_clips
                )
                director_fit, matched_requirements, missing_requirements = (
                    self._director_fit_details(s_units, hit.annotation)
                )
                local_anchor_target_ms: int | None = None
                shot_start_offset_ms = cursor - beat.timeline_start_ms
                if (
                    anchor_target_offset_ms is not None
                    and shot_start_offset_ms <= anchor_target_offset_ms < shot_start_offset_ms + duration
                ):
                    local_anchor_target_ms = anchor_target_offset_ms - shot_start_offset_ms
                source_in, source_out = source_window(
                    hit,
                    duration,
                    s_units + a_units,
                    anchor_target_offset_ms=local_anchor_target_ms,
                )
                fallback_clips.append(finalize_evidence(RoughCutClip(
                    beat_id=beat.id,
                    segment_id=hit.segment_id,
                    video_id=hit.video_id,
                    source_uri=hit.source_uri,
                    source_in_ms=source_in,
                    source_out_ms=source_out,
                    anchor_in_ms=getattr(hit, "anchor_start_ms", None),
                    anchor_out_ms=getattr(hit, "anchor_end_ms", None),
                    safe_in_ms=getattr(hit, "safe_start_ms", None),
                    safe_out_ms=getattr(hit, "safe_end_ms", None),
                    continuity_key=getattr(hit, "continuity_key", None),
                    visual_family=getattr(hit, "visual_family", None),
                    presentation_type=getattr(hit, "presentation_type", None),
                    pollution_level=getattr(hit, "pollution_level", None),
                    protocol_candidate_type=getattr(hit, "protocol_candidate_type", None),
                    protocol_id=getattr(hit, "protocol_id", None),
                    continuity_status=getattr(hit, "continuity_status", None),
                    match_level=getattr(hit, "match_level", None),
                    director_fit=director_fit,
                    director_matched_requirements=matched_requirements,
                    director_missing_requirements=missing_requirements,
                    timeline_in_ms=cursor,
                    timeline_out_ms=cursor + duration,
                    score=0.0,
                    schedule_level="reuse" if reused else getattr(
                        hit, "schedule_level", "exact"
                    ),
                    score_breakdown=CandidateScore(
                        segment_id=hit.segment_id,
                        semantic_score=0.0, action_score=0.0, scene_score=0.0,
                        emotion_score=0.0, duration_fit_score=0.0, quality_score=0.0,
                        continuity_bonus=0.0, reuse_penalty=0.0, total_score=0.0,
                    ),
                    selection_reason=(
                        "受控复用兜底：素材不足但仍完整覆盖旁白"
                        if reused else "降级兜底：使用当前最佳有效素材"
                    ),
                ), hit, s_units + a_units))
                if len(fallback_clips) > 1:
                    fallback_clips[-1].selection_reason = (
                        "SHOT_SPLIT_REASON:CONTINUOUS_WINDOW_TOO_SHORT; "
                        + fallback_clips[-1].selection_reason
                    )
                reuse_counts[hit.segment_id] = reuse_counts.get(hit.segment_id, 0) + 1
                cursor += duration
                remaining -= duration
                previous_clip = fallback_clips[-1]
            return fallback_clips, previous_clip
        _, selected, durations = best

        split_reason = self._multi_shot_reason(
            selected, pool, total_ms=total_ms, s_units=s_units,
        )
        for selected_index, (hit, selected_duration_ms) in enumerate(
            zip(selected, durations, strict=True)
        ):
            breakdown = self._scorer.score(
                beat, hit, needed_duration_ms=selected_duration_ms,
                prior_use_count=reuse_counts.get(hit.segment_id, 0), previous_clip=previous_clip,
            )
            local_anchor_target_ms: int | None = None
            shot_start_offset_ms = timeline_cursor_ms - beat.timeline_start_ms
            if (
                anchor_target_offset_ms is not None
                and shot_start_offset_ms <= anchor_target_offset_ms
                < shot_start_offset_ms + selected_duration_ms
            ):
                local_anchor_target_ms = anchor_target_offset_ms - shot_start_offset_ms
            source_in_ms, source_out_ms = source_window(
                hit,
                selected_duration_ms,
                s_units + a_units,
                anchor_target_offset_ms=local_anchor_target_ms,
            )
            timeline_out_ms = timeline_cursor_ms + selected_duration_ms

            if not (
                hit.source_start_ms
                <= source_in_ms
                < source_out_ms
                <= hit.source_end_ms
            ):
                raise RoughCutPlanningError(
                    f"Selected source range exceeds segment {hit.segment_id} bounds"
                )

            director_fit, matched_requirements, missing_requirements = (
                self._director_fit_details(s_units, hit.annotation)
            )
            base_reason = (getattr(hit, "query_relevance_reason", None)
                           or hit.annotation.description or self._selection_reason(breakdown))
            if selected_index > 0 and split_reason:
                base_reason = f"SHOT_SPLIT_REASON:{split_reason}; {base_reason}"
            clip = RoughCutClip(
                beat_id=beat.id,
                segment_id=hit.segment_id,
                video_id=hit.video_id,
                source_uri=hit.source_uri,
                source_in_ms=source_in_ms,
                source_out_ms=source_out_ms,
                anchor_in_ms=getattr(hit, "anchor_start_ms", None),
                anchor_out_ms=getattr(hit, "anchor_end_ms", None),
                safe_in_ms=getattr(hit, "safe_start_ms", None),
                safe_out_ms=getattr(hit, "safe_end_ms", None),
                continuity_key=getattr(hit, "continuity_key", None),
                visual_family=getattr(hit, "visual_family", None),
                presentation_type=getattr(hit, "presentation_type", None),
                pollution_level=getattr(hit, "pollution_level", None),
                protocol_candidate_type=getattr(hit, "protocol_candidate_type", None),
                protocol_id=getattr(hit, "protocol_id", None),
                continuity_status=getattr(hit, "continuity_status", None),
                match_level=getattr(hit, "match_level", None),
                director_fit=director_fit,
                director_matched_requirements=matched_requirements,
                director_missing_requirements=missing_requirements,
                timeline_in_ms=timeline_cursor_ms,
                timeline_out_ms=timeline_out_ms,
                score=breakdown.total_score,
                schedule_level=getattr(hit, "schedule_level", "exact"),
                score_breakdown=breakdown,
                selection_reason=base_reason,
            )
            clip = finalize_evidence(clip, hit, s_units + a_units)
            clips.append(clip)
            previous_clip = clip
            reuse_counts[hit.segment_id] = reuse_counts.get(hit.segment_id, 0) + 1
            timeline_cursor_ms = timeline_out_ms

        return clips, previous_clip

    def _used_families(self, clips: list[Any] | None) -> set[str]:
        family_lookup = getattr(self, "_family_lookup", None)
        if clips is None or family_lookup is None:
            return set()
        used: set[str] = set()
        for clip in clips:
            family = family_lookup(clip.segment_id)
            if family is not None:
                used.add(family)
        return used

    def _family_conflict(
        self,
        hit: RoughCutSearchHit,
        prior_clips: list[Any] | None,
        used_families: set[str],
    ) -> bool:
        """True when the hit reuses a visual family already on the timeline.

        Same-video segments that are temporally close are continuous footage,
        not duplicates, and are exempt from the family constraint. Library
        fallback and controlled-reuse shots are also exempt: the "must produce
        a draft" rule outranks family diversity for these honest fallbacks.
        """
        if getattr(hit, "schedule_level", "exact") in {"source", "reuse", "c_tail"}:
            return False
        family_lookup = getattr(self, "_family_lookup", None)
        if family_lookup is None or not used_families:
            return False
        family = family_lookup(hit.segment_id)
        if family is None or family not in used_families:
            return False
        if prior_clips is None:
            return True
        for clip in prior_clips:
            clip_source_start_ms = getattr(
                clip, "source_in_ms", getattr(clip, "source_start_ms", None)
            )
            if (
                clip.video_id == hit.video_id
                and clip_source_start_ms is not None
                and abs(hit.source_start_ms - clip_source_start_ms) < _FAMILY_NEAR_MS
            ):
                return False
        return True

    @staticmethod
    def _multi_shot_reason(
        selected: list[RoughCutSearchHit],
        pool: list[RoughCutSearchHit],
        *,
        total_ms: int,
        s_units: list[DirectorUnit],
    ) -> str | None:
        if len(selected) <= 1:
            return None
        longest_capacity = max(
            (min(total_ms, hit.source_end_ms - hit.source_start_ms) for hit in pool),
            default=0,
        )
        if longest_capacity < total_ms:
            return "CONTINUOUS_WINDOW_TOO_SHORT"
        if any(getattr(hit, "pollution_level", None) in {"blocked", "text_heavy"}
               for hit in selected):
            return "POLLUTION_GAP"
        if s_units and len(selected) > 1:
            return "MULTIPLE_INDEPENDENT_S_PROOFS"
        if len({hit.video_id for hit in selected}) > 1:
            return "SUBJECT_OR_SCENE_CONTINUITY_LIMIT"
        return "SENTENCE_CAPACITY_SPLIT"

    @staticmethod
    def _selection_reason(score: CandidateScore) -> str:
        return (
            f"semantic={score.semantic_score:.3f}; "
            f"action={score.action_score:.3f}; "
            f"scene={score.scene_score:.3f}; "
            f"emotion={score.emotion_score:.3f}; "
            f"duration={score.duration_fit_score:.3f}; "
            f"quality={score.quality_score:.3f}; "
            f"continuity={score.continuity_bonus:.3f}; "
            f"reuse={score.reuse_penalty:.3f}; "
            f"total={score.total_score:.3f}"
        )

    def _coalesce_short_clips(
        self, clips: list[RoughCutClip], beats: list[ScriptBeat],
    ) -> list[RoughCutClip]:
        """Let an adjacent safe source window cover a sub-3s narration tail."""
        catalog = getattr(self._search, "_catalog", None)
        expand = getattr(catalog, "expand_segment_window", None)
        if not callable(expand) or len(clips) < 2:
            return clips
        importance = {
            beat.id: beat.retrieval_intent.get("director_importance") for beat in beats
        }
        result = list(clips)
        index = 0
        while index < len(result):
            short = result[index]
            short_ms = short.timeline_out_ms - short.timeline_in_ms
            if short_ms >= MIN_SHOT_MS or importance.get(short.beat_id) == "S":
                index += 1
                continue

            anchors = []
            if index > 0:
                anchors.append((index - 1, result[index - 1]))
            if index + 1 < len(result):
                anchors.append((index + 1, result[index + 1]))
            merged = False
            for anchor_index, anchor in anchors:
                if anchor.video_id != short.video_id or anchor.beat_id != short.beat_id:
                    continue
                # Distinct evidence records cannot be replaced by one clip's
                # metadata during coalescing. Preserve each checked window.
                if (anchor.anchor_in_ms is not None or short.anchor_in_ms is not None
                        or anchor.director_fit is not None or short.director_fit is not None):
                    continue
                target_ms = short_ms + anchor.timeline_out_ms - anchor.timeline_in_ms
                window = expand(anchor.segment_id, target_ms)
                if window is None or window[1] - window[0] < target_ms:
                    continue
                lower = max(window[0], anchor.source_out_ms - target_ms)
                upper = min(anchor.source_in_ms, window[1] - target_ms)
                if lower > upper:
                    continue
                source_in = upper
                timeline_in = min(short.timeline_in_ms, anchor.timeline_in_ms)
                timeline_out = max(short.timeline_out_ms, anchor.timeline_out_ms)
                combined = anchor.model_copy(update={
                    "source_in_ms": source_in,
                    "source_out_ms": source_in + target_ms,
                    "timeline_in_ms": timeline_in,
                    "timeline_out_ms": timeline_out,
                    "selection_reason": (
                        f"{anchor.selection_reason}; adjacent short narration covered by safe window"
                    ),
                })
                left, right = sorted((index, anchor_index))
                result[left:right + 1] = [combined]
                index = max(0, left - 1)
                merged = True
                break
            if not merged:
                index += 1
        return result

    def _validate_video_cooldown(
        self, clips: list[RoughCutClip], beats: list[ScriptBeat],
    ) -> list[str]:
        """Report remote returns without blocking an otherwise renderable draft."""
        warnings: list[str] = []
        beat_by_id = {beat.id: beat for beat in beats}
        seen: set[UUID] = set()
        previous: RoughCutClip | None = None
        for clip in clips:
            if previous is not None and clip.video_id != previous.video_id and clip.video_id in seen:
                beat = beat_by_id.get(clip.beat_id)
                intent = beat.retrieval_intent if beat is not None else {}
                units = intent.get("director_units") or []
                is_s_direct = any(
                    isinstance(unit, dict) and unit.get("importance") == "S"
                    for unit in units
                ) and clip.schedule_level == "exact" and clip.director_fit == "DIRECT"
                distance = min(
                    abs(clip.source_in_ms - previous.source_out_ms),
                    abs(previous.source_in_ms - clip.source_out_ms),
                )
                if not (is_s_direct and distance > self._settings.continuity_window_ms):
                    warnings.append(
                        f"视频冷却提示：第 {clip.beat_id} 个视觉窗口返回已使用视频；"
                        "已保留并标记为质量警告"
                    )
            if previous is not None:
                seen.add(previous.video_id)
            previous = clip
        return warnings

    @staticmethod
    def _validate_timeline(clips: list[RoughCutClip], total_duration_ms: int) -> None:
        if not clips:
            raise RoughCutPlanningError("Rough-cut plan contains no clips")
        if clips[0].timeline_in_ms != 0:
            raise RoughCutPlanningError("Rough-cut timeline must start at zero")
        if clips[-1].timeline_out_ms != total_duration_ms:
            raise RoughCutPlanningError(
                "Rough-cut timeline must end at narration duration"
            )
        for previous, following in pairwise(clips):
            if previous.timeline_out_ms != following.timeline_in_ms:
                raise RoughCutPlanningError("Rough-cut timeline contains a gap or overlap")
