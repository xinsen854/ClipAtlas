"""Local proposition matching with evidence provenance and partial coverage."""

import re
from dataclasses import dataclass
from hashlib import sha256
from itertools import product

from clipatlas.domain.evidence import ClaimMatch, EvidenceStatement, Proposition, VisualClaim
from clipatlas.domain.models import SemanticAnnotation
from clipatlas.domain.vehicle_names import canonical_vehicle_name

# Exact concept aliases, never edit distance for model identity or versions.
ALIASES = {
    "车辆": ("车辆", "汽车", "越野车", "suv", "vehicle", "car"),
    "行驶": ("行驶", "driving", "vehicle driving", "driving forward"),
    "静止展示": ("静止展示", "parked", "stationary", "vehicle parked", "displayed"),
    "起飞": ("起飞", "升空", "takeoff", "taking off", "takes off"),
    "无人机": ("无人机", "drone", "uav"),
    "华为": ("华为", "huawei"),
    "北京越野": ("北京越野", "beijing off-road", "beijing offroad"),
    "城市道路": ("城市道路", "城市街道", "city road", "city street", "urban road"),
    "山路": ("山路", "mountain road"),
    "露营": ("露营", "户外露营", "camping"),
    "三把锁": ("三把锁", "three differential locks"),
    "八横两纵高强钢大梁": ("八横两纵高强钢大梁", "八横两纵高强钢大梁车架"),
    "增程": ("增程", "range extender", "extended range"),
}
MODEL_NAMES = ("BJ40增程悦野飞行版", "BJ40增程", "BJ40", "BJ30", "泰钽700", "坦克700")
PRESENCE_NAMES = ("连云港山海逐浪越野基地", "车载无人机", "无人机", "充电桩", "露营帐篷")
CONFIGURATIONS = ("ADS 5.0 MAX", "ADS 5 MAX", "八横两纵高强钢大梁", "三把锁", "增程", "车载无人机")
QUANTITY_CONTEXT = {
    "活动": "线下活动", "用户": "用户数量", "服务": "服务网络",
    "制造史": "制造历史", "历史": "制造历史", "落差": "垂直落差",
}


def canonical(text: str) -> str:
    folded = re.sub(r"\s+", " ", text.strip().casefold())
    vehicle = canonical_vehicle_name(text)
    if vehicle != text.strip():
        return vehicle.casefold()
    for concept, aliases in ALIASES.items():
        if folded in aliases:
            return concept
    return folded


def mentions(text: str, phrase: str) -> bool:
    variants = ALIASES.get(canonical(phrase), (phrase,))
    for value in variants:
        pattern = re.escape(value.casefold())
        if value[0].isascii() and value[0].isalnum():
            pattern = r"(?<![a-z0-9])" + pattern
        if value[-1].isascii() and value[-1].isalnum():
            pattern += r"(?![a-z0-9])"
        for match in re.finditer(pattern, text.casefold()):
            if not re.search(r"(?:非|不|未|没有|不是|not|without|no)\s*$", text[:match.start()]):
                return True
    return False


def subject_matches(observed: str, requested: str) -> bool:
    observed, requested = canonical(observed), canonical(requested)
    if observed == requested:
        return True
    # A confirmed specific model entails the generic class, never vice versa.
    if requested == "车辆" and observed in {canonical(v) for v in MODEL_NAMES}:
        return True
    if requested == "bj40" and observed in {"bj40增程", "bj40增程悦野飞行版"}:
        return True
    return False


def subjects_related(observed: str, requested: str) -> bool:
    observed, requested = canonical(observed), canonical(requested)
    if "车辆" in {observed, requested}:
        return subject_matches(observed, requested)
    if subject_matches(observed, requested) or subject_matches(requested, observed):
        return True
    return bool(observed and requested and (observed.startswith(requested) or requested.startswith(observed)))


@dataclass(frozen=True)
class ResolvedEvidence:
    id: str
    statement: EvidenceStatement
    start: int | None
    end: int | None
    provenance: str


def evidence_records(
    annotation: SemanticAnnotation, *, source_window: tuple[int, int] | None = None,
    allow_untimed: bool = True,
) -> list[ResolvedEvidence]:
    records = []

    def add(statement, start, end, key, provenance):
        if source_window is not None:
            if start is None or end is None:
                if not allow_untimed:
                    return
            elif statement.temporal_basis == "point":
                if not source_window[0] <= start < source_window[1]:
                    return
            elif not source_window[0] <= start < end <= source_window[1]:
                return
        identifier = f"{annotation.segment_id}:{key}"
        records.append(ResolvedEvidence(identifier, statement, start, end, provenance))

    for index, fact in enumerate(annotation.facts):
        if fact.statement is not None:
            if fact.statement.temporal_basis == "unknown":
                if fact.statement.proposition.predicate in {"action", "relation"}:
                    continue
                add(fact.statement, None, None, f"fact:{index}", "typed")
            else:
                add(fact.statement, fact.start_ms, fact.end_ms, f"fact:{index}", "typed")

    # Old text stays searchable, but only conservative atomic observations are
    # upgraded. No model is inferred from filenames or descriptive similarity.
    layers = [("identity", value, "visual", None, None)
              for value in [*annotation.characters, *annotation.objects]]
    layers += [("identity", value, "source_text", None, None) for value in annotation.ocr]
    layers += [("scene", value, "visual", None, None) for value in annotation.scene]
    for fact in annotation.facts:
        if fact.statement is None:
            pred = {"subject": "identity", "object": "identity", "scene": "scene",
                    "text_audio": "text"}.get(str(fact.layer))
            if pred:
                # text_audio may be spoken audio; do not promote it to on-screen text.
                layers.append((pred, fact.value, "source_audio" if pred == "text" else "visual",
                               fact.start_ms, fact.end_ms))
    for index, (layer, text, kind, start, end) in enumerate(layers):
        temporal = "unknown" if start is None or end is None else (
            "point" if start == end else "interval")
        representation = "audio" if kind == "source_audio" else (
            "screen" if kind == "source_text" else "real_scene")
        values = []
        if layer == "identity":
            names = [name for name in (*MODEL_NAMES, "北京越野", "华为", "无人机") if mentions(text, name)]
            # Do not shorten a positively identified variant into a contradictory identity.
            names = [name for name in names if not any(name != other and name in other for other in names)]
            values += [Proposition(subject=name, predicate="identity", value=name) for name in names]
            if canonical(text) == "车辆":
                values.append(Proposition(subject="车辆", predicate="identity", value="车辆"))
            for name in PRESENCE_NAMES:
                if mentions(text, name):
                    values.append(Proposition(subject=name, predicate="presence", value=name))
        if layer == "scene":
            values.append(Proposition(subject="场景", predicate="scene", value=canonical(text)))
        if kind == "source_text":
            # Text can establish a displayed specification, not operation.
            for name in CONFIGURATIONS:
                if mentions(text, name):
                    values.append(Proposition(subject="未绑定主体", predicate="configuration", value=name))
            for match in re.finditer(
                r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(万|亿|年|场|城|米|公里|个|台|辆|人)(?![a-z0-9])",
                text.casefold(),
            ):
                nearby = text[max(0, match.start() - 24):match.end() + 24]
                scope = next((scope for marker, scope in QUANTITY_CONTEXT.items()
                              if marker in nearby), None)
                if scope:
                    values.append(Proposition(
                        subject=scope, predicate="quantity", value=match.group(1),
                        unit=match.group(2), scope=scope,
                    ))
        for pos, proposition in enumerate(values):
            statement = EvidenceStatement(proposition=proposition, entity_id=f"legacy:{index}",
                kind=kind, representation=representation, temporal_basis=temporal)
            add(statement, start, end, f"legacy:{index}:{pos}", "legacy_atomic")
    return records


def condition_key(condition: Proposition) -> str:
    return " / ".join(str(v) for v in (
        condition.subject, condition.predicate, condition.value, condition.unit, condition.scope
    ) if v)


def _same_fact(observed: Proposition, requested: Proposition) -> bool:
    return (observed.predicate == requested.predicate
            and (subject_matches(observed.subject, requested.subject)
                 or observed.subject == "未绑定主体")
            and (canonical(observed.value) == canonical(requested.value)
                 or (requested.predicate == "identity"
                     and subject_matches(observed.value, requested.value)))
            and canonical(observed.unit or "") == canonical(requested.unit or "")
            and canonical(observed.scope or "") == canonical(requested.scope or ""))


def match_claim(claim: VisualClaim, importance: str, records: list[ResolvedEvidence]) -> ClaimMatch:
    best = None
    for alternative in claim.any_of:
        pools = []
        matching = []
        conflicts = []
        for condition in alternative.all_of:
            candidates = [r for r in records if r.statement.kind in alternative.allowed_kinds
                          and _same_fact(r.statement.proposition, condition)]
            conflicts += [r for r in candidates if r.statement.proposition.polarity != condition.polarity]
            found = [r for r in candidates if r.statement.proposition.polarity == condition.polarity]
            pools.append(found[:20])
            if found:
                matching.append(condition_key(condition))
        chosen = []
        if all(pools):
            # Join using object instance IDs; never combine different vehicles.
            entity_ids = {r.statement.entity_id for r in pools[0]}
            for entity in sorted(entity_ids) if alternative.same_entity else [None]:
                filtered = [[r for r in pool if entity is None or r.statement.entity_id == entity]
                            for pool in pools]
                if not all(filtered):
                    continue
                # Bound the join, then continue as SUPPORT if no proven combination exists.
                for attempt, combo in enumerate(product(*filtered)):
                    if attempt >= 4096:
                        break
                    if alternative.simultaneous:
                        if any(r.start is None or r.end is None for r in combo):
                            continue
                        if max(r.start for r in combo) > min(r.end for r in combo):
                            continue
                        boundary = max(r.start for r in combo)
                        if any(r.start < r.end == boundary for r in combo):
                            continue
                    if any(
                        r.statement.proposition.subject == "未绑定主体"
                        and not any(
                            other.statement.proposition.predicate == "identity"
                            and subject_matches(
                                other.statement.proposition.subject,
                                alternative.all_of[pos].subject,
                            )
                            for other in combo
                        )
                        for pos, r in enumerate(combo)
                    ):
                        continue
                    chosen = list(combo)
                    break
                if chosen:
                    break
        related = [r for r in records if r.statement.proposition.polarity == "positive" and any(
            subjects_related(r.statement.proposition.subject, c.subject)
            and r.statement.proposition.subject != "未绑定主体"
            and (c.predicate != "scene" or canonical(r.statement.proposition.value) == canonical(c.value))
            for c in alternative.all_of)]
        # A contradictory record makes complete proof ambiguous, not silently exact.
        level = "REJECT" if conflicts else ("DIRECT" if chosen and claim.goal == "proof" else (
            "SUPPORT" if chosen or matching or related else "UNKNOWN"))
        used = chosen or list(dict.fromkeys(r.id for pool in pools for r in pool))
        selected = chosen if chosen else [r for r in records if r.id in used]
        if not selected and related:
            selected = related[:4]
        missing = [condition_key(c) for c,pool in zip(alternative.all_of, pools) if not pool]
        reasons = []
        if matching and not chosen and not missing:
            reasons.append("conditions exist but do not bind to the required entity/time")
        if conflicts:
            reasons.append("explicit contradictory evidence")
        if any(r.provenance == "legacy_atomic" for r in selected):
            reasons.append("legacy atomic evidence; no inferred action or relationship")
        result = ClaimMatch(claim_id=claim.claim_id, source_quote=claim.source_quote,
            importance=importance, goal=claim.goal, level=level,
            evidence_ids=list(dict.fromkeys(r.id for r in selected)),
            evidence_kinds=list(dict.fromkeys(r.statement.kind for r in selected)),
            source_ranges=list(dict.fromkeys((r.start,r.end) for r in selected
                                             if r.start is not None and r.end is not None)),
            matched_conditions=matching, missing_conditions=missing, reasons=reasons)
        rank = {"DIRECT": 3, "SUPPORT": 2, "UNKNOWN": 1, "REJECT": 0}
        if best is None or (rank[result.level],len(matching)) > (rank[best.level],len(best.matched_conditions)):
            best = result
    return best


def summarize_matches(matches: list[ClaimMatch]) -> str:
    if any(m.level == "REJECT" for m in matches):
        return "REJECT"
    if matches and all(m.level == "DIRECT" for m in matches):
        return "DIRECT"
    if any(m.level in {"DIRECT", "SUPPORT"} for m in matches):
        return "SUPPORT"
    return "UNKNOWN"


def claim_id(quote: str, proposition: str) -> str:
    return sha256((quote + "\0" + proposition).encode()).hexdigest()[:20]
