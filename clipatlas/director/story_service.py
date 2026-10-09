from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from clipatlas.director.story_errors import (
    AutoDirectorUnavailableError,
    StoryEvidenceUnavailableError,
    StoryOutlineConflictError,
    StoryOutlineNotFoundError,
    StorySkillError,
)
from clipatlas.director.story_evidence import StoryEvidenceBuilder
from clipatlas.director.story_models import (
    StoryEvidenceReference,
    StoryOutline,
    StoryOutlineEditNode,
    StoryOutlineNode,
    StoryReadiness,
    StorySkill,
)
from clipatlas.director.story_store import StoryOutlineStore

_ALLOWED_SKILL_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}


class StoryAnalyzerLike(Protocol):
    async def analyze(self, skill: StorySkill, packet): ...


class StoryDirectorService:
    def __init__(
        self,
        *,
        evidence_builder: StoryEvidenceBuilder,
        analyzer: StoryAnalyzerLike | None,
        store: StoryOutlineStore,
    ) -> None:
        self._evidence_builder = evidence_builder
        self._analyzer = analyzer
        self._store = store

    @staticmethod
    def _skill(name: str, content: str) -> StorySkill:
        suffix = Path(name).suffix.lower()
        if suffix not in _ALLOWED_SKILL_SUFFIXES:
            raise StorySkillError("Story Skill 仅支持 .md/.txt/.json/.yaml/.yml")
        normalized = content.strip()
        if not normalized:
            raise StorySkillError("Story Skill 内容不能为空")
        return StorySkill(name=Path(name).name, content=normalized)

    def _project_outline(self, project_id: UUID, outline_id: UUID) -> StoryOutline:
        outline = self._store.get(outline_id)
        if outline is None or outline.project_id != project_id:
            # Fail closed without revealing whether an outline exists in another project.
            raise StoryOutlineNotFoundError(f"故事简纲不存在：{outline_id}")
        return outline

    def readiness(self, project_id: UUID) -> StoryReadiness:
        try:
            packet = self._evidence_builder.build(project_id)
        except StoryEvidenceUnavailableError as exc:
            return StoryReadiness(project_id=project_id, ready=False, message=str(exc))

        counts = {"visual": 0, "asr": 0, "ocr": 0}
        for item in packet.items:
            counts[item.kind] += 1
        return StoryReadiness(
            project_id=project_id,
            ready=True,
            video_count=packet.video_count,
            evidence_count=len(packet.items),
            visual_count=counts["visual"],
            asr_count=counts["asr"],
            ocr_count=counts["ocr"],
            warnings=packet.warnings,
        )

    async def analyze(
        self,
        project_id: UUID,
        *,
        skill_name: str,
        skill_content: str,
    ) -> StoryOutline:
        skill = self._skill(skill_name, skill_content)
        if self._analyzer is None:
            raise AutoDirectorUnavailableError("自动编导尚未配置模型 API")
        packet = self._evidence_builder.build(project_id)
        result = await self._analyzer.analyze(skill, packet)
        evidence_by_id = {item.evidence_id: item for item in packet.items}

        nodes: list[StoryOutlineNode] = []
        for order, draft in enumerate(result.nodes):
            refs: list[StoryEvidenceReference] = []
            seen: set[str] = set()
            for raw_evidence_id in draft.evidence_ids:
                evidence_id = raw_evidence_id.removeprefix("EVID:")
                if evidence_id in seen:
                    continue
                seen.add(evidence_id)
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    raise StoryOutlineConflictError(
                        f"Auto Director 返回了当前项目不存在的证据：{evidence_id}"
                    )
                refs.append(
                    StoryEvidenceReference(
                        evidence_id=evidence.evidence_id,
                        kind=evidence.kind,
                        video_id=evidence.video_id,
                        segment_id=evidence.segment_id,
                        start_ms=evidence.start_ms,
                        end_ms=evidence.end_ms,
                        text=evidence.text,
                        source_name=evidence.source_name,
                    )
                )
            if not refs:
                raise StoryOutlineConflictError("故事简纲节点缺少可解析的真实素材证据")
            nodes.append(
                StoryOutlineNode(
                    order=order,
                    title=draft.title,
                    summary=draft.summary,
                    role=draft.role,
                    estimated_duration_ms=draft.estimated_duration_ms,
                    evidence=refs,
                )
            )

        outline = StoryOutline(
            project_id=project_id,
            revision=self._store.next_revision(project_id),
            skill_name=skill.name,
            skill_hash=skill.content_hash,
            summary=result.summary,
            hook_rationale=result.hook_rationale,
            nodes=nodes,
            warnings=[*packet.warnings, *result.warnings],
        )
        self._store.save(outline)
        return outline

    def list_project(self, project_id: UUID) -> list[StoryOutline]:
        return self._store.list_project(project_id)

    def get_confirmed(self, project_id: UUID, outline_id: UUID) -> StoryOutline:
        outline = self._project_outline(project_id, outline_id)
        if outline.status != "confirmed":
            raise StoryOutlineConflictError("只能执行已确认的故事简纲")
        return outline

    def edit(
        self,
        project_id: UUID,
        outline_id: UUID,
        *,
        summary: str,
        hook_rationale: str,
        nodes: list[StoryOutlineEditNode],
    ) -> StoryOutline:
        source = self._project_outline(project_id, outline_id)
        if source.status == "confirmed":
            raise StoryOutlineConflictError("已确认故事简纲不能原地修改，请重新分析或从草稿修订")
        if not nodes:
            raise StoryOutlineConflictError("故事简纲至少保留一个节点")

        source_nodes = {node.id: node for node in source.nodes}
        seen: set[UUID] = set()
        updated_nodes: list[StoryOutlineNode] = []
        for order, edit in enumerate(nodes):
            if edit.id in seen:
                raise StoryOutlineConflictError("故事简纲节点不能重复")
            seen.add(edit.id)
            original = source_nodes.get(edit.id)
            if original is None:
                raise StoryOutlineConflictError("不能在编辑故事简纲时创建没有素材证据的新节点")
            updated_nodes.append(
                StoryOutlineNode(
                    id=original.id,
                    order=order,
                    title=edit.title,
                    summary=edit.summary,
                    role=edit.role,
                    estimated_duration_ms=edit.estimated_duration_ms,
                    evidence=original.evidence,
                )
            )

        revised = StoryOutline(
            id=uuid4(),
            project_id=source.project_id,
            revision=self._store.next_revision(source.project_id),
            skill_name=source.skill_name,
            skill_hash=source.skill_hash,
            summary=summary.strip() or source.summary,
            hook_rationale=hook_rationale.strip(),
            nodes=updated_nodes,
            warnings=source.warnings,
        )
        self._store.save(revised)
        return revised

    def confirm(self, project_id: UUID, outline_id: UUID) -> StoryOutline:
        self._project_outline(project_id, outline_id)
        outline = self._store.confirm(outline_id)
        if outline is None:  # Defensive: ownership check above already resolved the row.
            raise StoryOutlineNotFoundError(f"故事简纲不存在：{outline_id}")
        return outline
