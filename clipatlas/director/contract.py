"""Validate Director claims against their quoted narration, locally."""

from clipatlas.director.claim_matching import mentions
from clipatlas.director.models import DirectorUnit
from clipatlas.domain.evidence import PROPOSITION_INSTRUCTIONS

DIRECTOR_CONTRACT_PROMPT = PROPOSITION_INSTRUCTIONS + """
For every unit, add visual_goal (proof|related|continuity) and claims.
S/A/B is editorial importance, NOT shot order or a reason to split a sentence.
Keep complete sentences together. Multiple claims inside one sentence do NOT require multiple shots.
Abstract brand/lifestyle arguments use related or continuity, not mandatory slogan OCR.
claims is an array of {claim_id, source_quote, goal: proof|related,
 any_of: [{all_of: [proposition], allowed_kinds: [visual|source_text|diagram|source_audio],
 same_entity: true, simultaneous: false}]}.
source_quote must be an exact substring of text_range supporting the requested fact.
Use independent claims for separate facts. any_of describes equivalent proof alternatives;
all_of is only for conditions that must jointly hold. Never bundle city driving and off-road
driving as simultaneous requirements. Mark relations simultaneous only when necessary.
Do not invent takeoff, opening a hatch, plugging in or loading luggage when the script only
states equipment/configuration or general commuting. Put suggested angles and actions in preferred.
Keep required_subjects/objects/actions and must_have empty when claims is present; they are legacy fields.
Equipment presence is not operation. Aerial camera viewpoint does not prove a drone is visible.
source_text can support a stated specification, not an observed action. For action proof allow
visual only. Related fallback may use the correct model without proving the missing equipment.
B continuity may have no claims. Do not require historical images or printed numbers merely
because a narration references heritage; separate the measurable claim from related brand imagery.
"""


def validate_unit_claims(unit: DirectorUnit, script: str) -> DirectorUnit:
    issues = list(unit.contract_issues)
    if unit.text_range not in script:
        issues.append("unit text_range is not an exact source quote")
    seen = set()
    for claim in unit.claims:
        errors = []
        if claim.claim_id in seen:
            errors.append("duplicate claim_id")
        seen.add(claim.claim_id)
        if claim.source_quote not in unit.text_range or claim.source_quote not in script:
            errors.append("claim source_quote is not inside the original unit")
        for alternative in claim.any_of:
            for condition in alternative.all_of:
                if claim.goal == "proof" and condition.predicate in {
                    "identity", "presence", "action", "configuration", "scene", "quantity", "relation"
                } and not mentions(claim.source_quote, condition.value):
                    errors.append(
                        f"{condition.predicate} is not grounded in quote: {condition.value}"
                    )
                if condition.predicate == "action":
                    if claim.goal == "proof" and alternative.allowed_kinds != ["visual"]:
                        errors.append("observed action must use visual evidence")
                if condition.polarity == "negative" and not any(
                    word in claim.source_quote for word in ("不", "未", "无", "非", "没有", "not", "without")
                ):
                    errors.append("negative claim is not grounded in quote")
        if errors:
            issues.extend(f"{claim.claim_id}: {e}" for e in dict.fromkeys(errors))
    if unit.importance in {"S", "A"} and unit.visual_goal != "continuity" and not unit.claims:
        issues.append("proof unit has no structured claims")
    # Keep invalid claims for audit but never give them DIRECT: matcher applies
    # the issue list. Dropping a required claim would create false full coverage.
    return unit.model_copy(update={"contract_issues": list(dict.fromkeys(issues))})
