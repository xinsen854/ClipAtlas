"""Local DIRECT / SUPPORT / REJECT / UNKNOWN fit judgement.

Pure local rules over the catalog annotation; never calls an API. A REJECT is
final (the core object is visibly wrong and cannot be compensated by other
scores); UNKNOWN means "no annotated evidence yet" rather than rejection, so
missing annotations do not silently kill candidates.
"""

from dataclasses import dataclass, field
import re
from typing import Iterable, Literal

from clipatlas.director.models import DirectorUnit
from clipatlas.domain.models import SemanticAnnotation
from clipatlas.retrieval.text_normalization import term_variants
from clipatlas.domain.evidence import ClaimMatch

FitLevel = Literal["DIRECT", "SUPPORT", "REJECT", "UNKNOWN"]

@dataclass
class LocalFitVerdict:
    level: FitLevel
    reason: str
    matched_objects: list[str] = field(default_factory=list)
    matched_subjects: list[str] = field(default_factory=list)
    matched_actions: list[str] = field(default_factory=list)
    matched_surrogates: list[str] = field(default_factory=list)
    matched_must_have: list[str] = field(default_factory=list)
    missing_must_have: list[str] = field(default_factory=list)
    matched_preferred: list[str] = field(default_factory=list)
    avoided_hits: list[str] = field(default_factory=list)
    claim_matches: list[ClaimMatch] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return self.level in {"DIRECT", "SUPPORT"}


_SUFFIX_WORDS = ("示意图", "展示", "演示", "特写", "镜头", "画面", "图")


def _normalize(text: str) -> str:
    value = text.strip().casefold()
    for word in _SUFFIX_WORDS:
        value = value.removesuffix(word)
    return value


def _contains_strict(needle: str, haystacks: Iterable[str]) -> bool:
    """A prohibition must itself be evidenced, including its negation."""
    prohibited = re.sub(r"^(?:禁止|避免|不要出现|不要|不得出现)\s*", "", needle.strip())
    return _contains(prohibited, haystacks)


def _contains(needle: str, haystacks: Iterable[str], *, decorative: bool = False) -> bool:
    """Require a complete positive phrase; shorter evidence cannot prove it.

    Local aliases are allowed, but similarity and reverse containment cannot
    establish a subject/action relationship or a more specific requirement.
    """
    for haystack in haystacks:
        evidence = _normalize(str(haystack)) if decorative else str(haystack).strip().casefold()
        for variant in term_variants(needle):
            required = _normalize(variant) if decorative else variant.strip().casefold()
            if not required:
                continue
            pattern = re.escape(required)
            if required[0].isascii() and required[0].isalnum():
                pattern = r"(?<![a-z0-9])" + pattern
            if required[-1].isascii() and required[-1].isalnum():
                pattern += r"(?![a-z0-9])"
            for match in re.finditer(pattern, evidence):
                prefix = evidence[:match.start()]
                if re.search(r"(?:非|不是|并非|没有|未|不|无|not|no|without)\s*$", prefix):
                    continue
                return True
    return False


def _matched(
    needles: list[str], evidence: Iterable[str], *, decorative: bool = False,
) -> list[str]:
    return [needle for needle in needles if _contains(needle, evidence, decorative=decorative)]


def fit(
    unit: DirectorUnit, annotation: SemanticAnnotation | None,
    *, source_window: tuple[int, int] | None = None,
    allow_untimed: bool = True,
) -> LocalFitVerdict:
    if unit.claims and annotation is not None:
        from clipatlas.director.claim_matching import evidence_records, match_claim, summarize_matches
        records = evidence_records(annotation, source_window=source_window, allow_untimed=allow_untimed)
        matches = [match_claim(claim, unit.importance, records) for claim in unit.claims]
        for index, match in enumerate(matches):
            issues = [issue for issue in unit.contract_issues
                      if issue.startswith(match.claim_id + ":") or issue.startswith("unit ")]
            if issues:
                matches[index] = match.model_copy(update={
                    "level": "UNKNOWN", "reasons": [*match.reasons, *issues],
                })
        return LocalFitVerdict(
            level=summarize_matches(matches), reason="逐项检查主体、事实、证据媒介与源区间",
            matched_must_have=[m.source_quote for m in matches if m.level == "DIRECT"],
            missing_must_have=[m.source_quote for m in matches if m.level != "DIRECT"],
            claim_matches=matches,
        )
    if unit.contract_issues:
        return LocalFitVerdict(level="UNKNOWN", reason="; ".join(unit.contract_issues))
    if annotation is None or not (annotation.description or "").strip():
        return LocalFitVerdict(
            level="UNKNOWN",
            reason="该片段尚无语义标注，无法本地判定 DIRECT/SUPPORT/REJECT",
        )

    facts = annotation.facts
    if source_window is not None:
        start, end = source_window
        facts = [fact for fact in facts if (
            (fact.start_ms is None and fact.end_ms is None)
            or (fact.start_ms is not None and fact.end_ms is not None
            and start <= fact.start_ms < fact.end_ms <= end
            )
        )]
    fact_values = [fact.value for fact in facts]
    direct_evidence = [
        *annotation.characters, *annotation.objects, *annotation.actions,
        *annotation.scene, *annotation.ocr, *fact_values,
    ]
    support_evidence = [annotation.description, *direct_evidence]
    avoided = [
        needle
        for needle in unit.avoid
        if _contains_strict(needle, support_evidence)
    ]
    if avoided:
        return LocalFitVerdict(
            level="REJECT",
            reason=f"出现明确禁止对象/动作：{ '、'.join(avoided) }",
            avoided_hits=avoided,
        )

    # OCR and objective facts are first-class evidence. In particular, media
    # identity (央视/CCTV), model names (泰钽700) and numeric claims often
    # exist only in on-screen text or fact layers, not in characters/objects.
    subject_evidence = [*annotation.characters, *annotation.ocr, *fact_values]
    object_evidence = [*annotation.objects, *annotation.ocr, *fact_values]
    action_evidence = [*annotation.actions, *annotation.ocr, *fact_values]
    matched_subjects = _matched(unit.required_subjects, subject_evidence)
    matched_objects = _matched(unit.required_objects, object_evidence)
    matched_actions = _matched(unit.required_actions, action_evidence)
    matched_surrogates = _matched(unit.acceptable_surrogates, support_evidence, decorative=True)
    matched_must_have = _matched(unit.must_have, direct_evidence)
    missing_must_have = [
        requirement for requirement in unit.must_have
        if requirement not in matched_must_have
    ]
    matched_preferred = _matched(unit.preferred, support_evidence)

    requirements = (
        (unit.required_subjects, matched_subjects),
        (unit.required_objects, matched_objects),
        (unit.required_actions, matched_actions),
    )
    typed_complete = all(len(required) == len(matched) for required, matched in requirements)
    if unit.must_have and not missing_must_have and typed_complete:
        return LocalFitVerdict(
            level="DIRECT",
            reason="全部 must_have 均由结构化时间段证据命中",
            matched_objects=matched_objects,
            matched_subjects=matched_subjects,
            matched_actions=matched_actions,
            matched_surrogates=matched_surrogates,
            matched_must_have=matched_must_have,
            matched_preferred=matched_preferred,
        )
    if unit.must_have and (
        matched_must_have or matched_preferred or matched_subjects
        or matched_objects or matched_actions or matched_surrogates
    ):
        return LocalFitVerdict(
            level="SUPPORT",
            reason="仅命中部分 must_have 或辅助证据",
            matched_objects=matched_objects,
            matched_subjects=matched_subjects,
            matched_actions=matched_actions,
            matched_surrogates=matched_surrogates,
            matched_must_have=matched_must_have,
            missing_must_have=missing_must_have,
            matched_preferred=matched_preferred,
        )
    if unit.must_have:
        return LocalFitVerdict(
            level="UNKNOWN",
            reason="must_have 均未命中，现有标注不足以证明或否定",
            missing_must_have=missing_must_have,
        )

    if any(required for required, _ in requirements) and typed_complete:
        return LocalFitVerdict(
            level="DIRECT",
            reason="要求的主体、对象与动作均由结构化事实直接命中",
            matched_subjects=matched_subjects,
            matched_objects=matched_objects,
            matched_actions=matched_actions,
            matched_must_have=matched_must_have,
            missing_must_have=missing_must_have,
            matched_preferred=matched_preferred,
        )
    if matched_subjects or matched_objects or matched_actions or matched_surrogates:
        return LocalFitVerdict(
            level="SUPPORT",
            reason="主题相关但缺少完整直接证据",
            matched_subjects=matched_subjects,
            matched_objects=matched_objects,
            matched_actions=matched_actions,
            matched_surrogates=matched_surrogates,
            matched_must_have=matched_must_have,
            missing_must_have=missing_must_have,
            matched_preferred=matched_preferred,
        )
    return LocalFitVerdict(
        level="UNKNOWN",
        reason="标注与要求均未命中，不作否定结论（避免误杀）",
        missing_must_have=missing_must_have,
    )
