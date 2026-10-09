"""Shared ingest prompt and local validation for all visual providers."""

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from clipatlas.domain.evidence import PROPOSITION_INSTRUCTIONS
from clipatlas.domain.models import ObjectiveFact
from clipatlas.providers.contracts import AnalyzeSegmentRequest
from clipatlas.providers.errors import ProviderStructuredOutputError

INGEST_CONTRACT_PROMPT = PROPOSITION_INSTRUCTIONS + """
Return facts as [{layer, value, evidence, confidence, start_ms, end_ms, statement}].
layer uses the fourteen objective layers. statement is null if identity/relation cannot be established,
otherwise {proposition, entity_id, kind: visual|source_text|diagram|source_audio,
 representation: real_scene|screen|diagram|cg|title_card|audio, frame_ids: [],
 temporal_basis: point|interval|unknown}.
Use one entity_id consistently for facts about the same visible instance. Different vehicles
must not share entity_id. OCR specifications are source_text, never observed operation.
Frames are labelled frame_0, frame_1, etc. Reference supplied IDs only.
Use absolute source milliseconds. If frame timestamps are unknown, use null times and unknown basis.
Do not infer continuous motion from one still frame. A visual action needs multiple timestamped frames.
Interval boundaries must stay within observed frame timestamps; they are not guaranteed editing boundaries.
Keep original visible OCR. Do not infer brand/model from filenames or turn aerial footage into a visible drone.
"""

_LATIN_WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z-]{2,}(?![A-Za-z0-9])")
_ALLOWED_LATIN_SEMANTICS = frozenset({
    "ads", "aeb", "app", "bev", "ev", "huawei", "harmonyos", "lidar", "max",
    "noa", "ocr", "suv",
})
_ALLOWED_LATIN_LABELS = frozenset({
    "land rover", "range rover", "rolls royce", "mercedes benz", "great wall",
    "beijing off-road",
})


class SemanticLanguageError(ValueError):
    """The payload is structurally valid but its semantic prose is not Chinese."""


def _contains_untranslated_english(value: str) -> bool:
    words = []
    for match in _LATIN_WORD.finditer(value):
        word = match.group(0)
        folded = word.casefold()
        if folded in _ALLOWED_LATIN_SEMANTICS or (word.isupper() and len(word) <= 10):
            continue
        words.append(word)
    stripped = value.strip()
    # Preserve previously unseen brand/model spellings without maintaining an
    # exhaustive vehicle-name allowlist. This only applies to short label-like
    # values, never sentence prose.
    if stripped.casefold() in _ALLOWED_LATIN_LABELS:
        return False
    if words and len(words) <= 3 and any(character.isdigit() for character in stripped):
        return False
    return len(words) >= 2 or (bool(words) and not re.search(r"[\u4e00-\u9fff]", value))


def semantic_language_issues(
    *,
    description: str,
    characters: list[str],
    actions: list[str],
    scene: list[str],
    emotions: list[str],
    objects: list[str],
    facts: list[ObjectiveFact],
) -> list[str]:
    """Return semantic fields that still contain untranslated English prose.

    OCR is intentionally excluded: it must remain exactly as seen. Model names,
    brands and technical acronyms are also accepted in their original spelling.
    """
    fields: list[tuple[str, str]] = [("description", description)]
    for name, values in (
        ("characters", characters),
        ("actions", actions),
        ("scene", scene),
        ("emotions", emotions),
        ("objects", objects),
    ):
        fields.extend((f"{name}[{index}]", value) for index, value in enumerate(values))
    for index, fact in enumerate(facts):
        fields.append((f"facts[{index}].value", fact.value))
        if fact.statement is not None:
            proposition = fact.statement.proposition
            fields.extend((
                (f"facts[{index}].statement.proposition.subject", proposition.subject),
                (f"facts[{index}].statement.proposition.value", proposition.value),
                (f"facts[{index}].statement.proposition.scope", proposition.scope or ""),
            ))
    return [name for name, value in fields if value and _contains_untranslated_english(value)]


def validate_semantic_language(**fields: object) -> None:
    issues = semantic_language_issues(**fields)  # type: ignore[arg-type]
    if issues:
        raise SemanticLanguageError(
            "semantic fields must use Simplified Chinese; untranslated fields: "
            + ", ".join(issues[:12])
        )


def frame_context(request: AnalyzeSegmentRequest) -> str:
    return "\n".join(
        f"frame_{i}: source_time_ms={request.frame_timestamps_ms[i] if request.frame_timestamps_ms else 'unknown'}"
        for i in range(len(request.frame_uris))
    )


def saved_frame_times(uris: list[str], segment_id: object, start: int, end: int) -> list[int]:
    """Use only the extractor's saved manifest, never infer timestamps for old frames."""
    if not uris:
        return []
    paths = []
    for uri in uris:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            return []
        path = unquote(parsed.path)
        paths.append(Path(path[1:] if len(path) > 2 and path[2] == ":" else path))
    if len({p.parent for p in paths}) != 1:
        return []
    try:
        manifest = json.loads((paths[0].parent / "frame_times.json").read_text(encoding="utf-8"))
        if (manifest["segment_id"], manifest["start_ms"], manifest["end_ms"]) != (str(segment_id), start, end):
            return []
        mapping = {f["name"]: f["timestamp_ms"] for f in manifest["frames"]}
        return [mapping[p.name] for p in paths]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def validate_facts(facts: list[ObjectiveFact], request: AnalyzeSegmentRequest) -> list[ObjectiveFact]:
    frame_times = {f"frame_{i}": t for i,t in enumerate(request.frame_timestamps_ms)}
    for index, fact in enumerate(facts):
        statement = fact.statement
        if statement is None:
            continue
        if any(ref not in {f"frame_{i}" for i in range(len(request.frame_uris))}
               for ref in statement.frame_ids):
            raise ProviderStructuredOutputError("Evidence references an unknown frame")
        if statement.temporal_basis != "unknown":
            if not statement.frame_ids or any(ref not in frame_times for ref in statement.frame_ids):
                raise ProviderStructuredOutputError("Timed evidence needs timestamped input frames")
            times = [frame_times[ref] for ref in statement.frame_ids]
            if not (request.start_ms <= fact.start_ms <= fact.end_ms < request.end_ms
                    and min(times) <= fact.start_ms <= fact.end_ms <= max(times)):
                raise ProviderStructuredOutputError(
                    f"Evidence exceeds observed source times: facts[{index}] uses "
                    f"{fact.start_ms}-{fact.end_ms}ms; segment is "
                    f"{request.start_ms}-{request.end_ms}ms with an exclusive end, and its "
                    f"referenced frames cover {min(times)}-{max(times)}ms"
                )
    return facts
