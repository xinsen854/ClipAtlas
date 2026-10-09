"""Conservative local construction of timeline events and sequence windows."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from clipatlas.domain.models import SemanticAnnotation, VideoSegment
from clipatlas.domain.vehicle_names import canonical_vehicle_name, is_known_vehicle_name
from clipatlas.domain.visual_protocol import (
    PROTOCOL_VERSION,
    EvidenceRef,
    VideoSequenceWindow,
    VideoTimelineEvent,
)


def _event_range(segment: VideoSegment, fact: object) -> tuple[int, int, str]:
    start = getattr(fact, "start_ms", None)
    end = getattr(fact, "end_ms", None)
    statement = getattr(fact, "statement", None)
    basis = getattr(statement, "temporal_basis", "unknown") if statement else "unknown"
    if isinstance(start, int) and isinstance(end, int) and segment.start_ms <= start < end <= segment.end_ms:
        return start, end, "observed_interval" if basis == "interval" else "unknown"
    return segment.start_ms, segment.end_ms, "segment_range" if basis == "unknown" else "unknown"


def _overlaps(start: int | None, end: int | None, left: int, right: int) -> bool:
    if start is None or end is None:
        return True
    if start == end:
        return left <= start <= right
    return start < right and end > left


def build_timeline_events(
    segment: VideoSegment,
    annotation: SemanticAnnotation | None,
) -> list[VideoTimelineEvent]:
    """Turn typed facts into events without inventing missing relationships."""
    if annotation is None:
        return []
    records = [
        (ordinal, fact, fact.statement, fact.statement.proposition)
        for ordinal, fact in enumerate(annotation.facts)
        if fact.statement is not None
    ]
    groups: list[dict[str, object]] = []
    # Observed actions are the strongest temporal anchors. Complementary
    # identity/scene/configuration facts are attached to these intervals.
    for ordinal, fact, statement, proposition in records:
        if proposition.predicate != "action" or statement.temporal_basis != "interval":
            continue
        start, end, _ = _event_range(segment, fact)
        groups.append({
            "entity": statement.entity_id,
            "start": start,
            "end": end,
            "ordinals": [ordinal],
            "records": [(ordinal, fact, statement, proposition)],
            "observed": True,
        })
    for ordinal, fact, statement, proposition in records:
        if any(ordinal in group["ordinals"] for group in groups):  # type: ignore[operator]
            continue
        targets = [
            group for group in groups
            if group["entity"] == statement.entity_id
            and _overlaps(fact.start_ms, fact.end_ms, int(group["start"]), int(group["end"]))
        ]
        if not targets:
            start, end, basis = _event_range(segment, fact)
            targets = [{
                "entity": statement.entity_id,
                "start": start,
                "end": end,
                "ordinals": [],
                "records": [],
                "observed": basis == "observed_interval",
            }]
            groups.extend(targets)
        for target in targets:
            target["ordinals"].append(ordinal)  # type: ignore[union-attr]
            target["records"].append((ordinal, fact, statement, proposition))  # type: ignore[union-attr]

    events: list[VideoTimelineEvent] = []
    for group in groups:
        grouped = group["records"]
        assert isinstance(grouped, list)
        propositions = [item[3] for item in grouped]
        statements = [item[2] for item in grouped]
        facts = [item[1] for item in grouped]
        identity = next((p.value for p in propositions if p.predicate == "identity"), None)
        subject = identity or next((p.subject for p in propositions if p.subject), None)
        action = next((p.value for p in propositions if p.predicate == "action"), None)
        scene = next((p.value for p in propositions if p.predicate == "scene"), None)
        action_records = [
            (fact, statement) for fact, statement, proposition in zip(
                facts, statements, propositions, strict=True
            ) if proposition.predicate == "action"
        ]
        observed_action = bool(action_records) and all(
            statement.temporal_basis == "interval" and len(set(statement.frame_ids)) >= 2
            for _, statement in action_records
        )
        ocr = list(dict.fromkeys(
            proposition.value for proposition, statement in zip(propositions, statements, strict=True)
            if statement.kind == "source_text"
        ))
        known_entity = bool(subject and is_known_vehicle_name(subject))
        stable_entity = (
            f"{segment.video_id}:{group['entity']}" if group.get("entity") else None
        )
        start, end = int(group["start"]), int(group["end"])
        scoped_entity = f"{segment.id}:{group['entity']}" if group.get("entity") else None
        event_id = uuid5(
            NAMESPACE_URL,
            f"clipatlas:event:{segment.id}:{annotation.id}:{annotation.revision}:"
            + ",".join(str(value) for value in group["ordinals"]),  # type: ignore[arg-type]
        )
        events.append(VideoTimelineEvent(
            id=event_id,
            video_id=segment.video_id,
            start_ms=start,
            end_ms=end,
            subject_name=subject,
            entity_name=subject,
            entity_id=scoped_entity,
            entity_track_id=stable_entity,
            entity_type="vehicle" if known_entity else ("object" if subject else None),
            vehicle_model=(
                canonical_vehicle_name(subject) if subject and is_known_vehicle_name(subject) else None
            ),
            action=action,
            action_phase=next((p.scope for p in propositions if p.predicate == "action" and p.scope), None),
            scene=scene,
            road_surface=scene,
            environment=scene,
            location_type=("indoor" if "室内" in (scene or "") else "outdoor" if scene else None),
            objects=list(dict.fromkeys(
                p.value for p in propositions if p.predicate == "presence"
            )),
            configurations=list(dict.fromkeys(
                p.value for p in propositions if p.predicate == "configuration"
            )),
            visible_equipment=list(dict.fromkeys(
                p.value for p in propositions if p.predicate == "presence"
            )),
            ocr=list(dict.fromkeys([*ocr, *annotation.ocr])),
            shot_type=annotation.shot_type,
            shot_scale=annotation.shot_type,
            camera_motion=annotation.camera_motion,
            camera_viewpoint=None,
            viewpoint=None,
            interior_or_exterior=(
                "indoor" if "室内" in (scene or "") else "outdoor" if scene else None
            ),
            interior_exterior=(
                "indoor" if "室内" in (scene or "") else "outdoor" if scene else None
            ),
            state_changes=list(dict.fromkeys(
                fact.value for fact in facts if getattr(fact, "layer", None).value == "event"
            )),
            quantities=list(dict.fromkeys(
                " ".join(str(value) for value in (p.value, p.unit, p.scope) if value)
                for p in propositions if p.predicate == "quantity"
            )),
            relations=list(dict.fromkeys(
                p.value for p in propositions if p.predicate == "relation"
            )),
            evidence=[EvidenceRef(
                segment_id=segment.id,
                frame_ids=list(statement.frame_ids),
                source=statement.kind,
                time_basis=statement.temporal_basis,
                confidence=fact.confidence,
            ) for fact, statement in zip(facts, statements, strict=True)],
            evidence_segment_ids=[segment.id],
            evidence_frame_ids=list(dict.fromkeys(
                frame_id for statement in statements for frame_id in statement.frame_ids
            )),
            segment_ids=[segment.id],
            frame_ids=list(dict.fromkeys(
                frame_id for statement in statements for frame_id in statement.frame_ids
            )),
            evidence_kind=(
                next(iter({statement.kind for statement in statements}))
                if len({statement.kind for statement in statements}) == 1 else "mixed"
            ),
            time_basis="observed_interval" if group["observed"] else "segment_range",
            temporal_basis="interval" if group["observed"] else "unknown",
            continuous_motion=observed_action,
            confidence=min(
                (fact.confidence for fact in facts if fact.confidence is not None), default=None,
            ),
            unknown_fields=([] if stable_entity else ["entity_id", "entity_track_id"]),
            unknown_conditions=([] if stable_entity else ["entity_id", "entity_track_id"]),
            protocol_version=PROTOCOL_VERSION,
        ))
    if not events:
        # Legacy annotations often have useful action/scene text but no typed
        # statement. Keep that recall signal while making the uncertainty
        # explicit; this record cannot prove entity continuity or DIRECT.
        action = annotation.actions[0] if annotation.actions else None
        scene = annotation.scene[0] if annotation.scene else None
        if action or scene or annotation.objects or annotation.characters:
            event_id = uuid5(
                NAMESPACE_URL,
                f"clipatlas:legacy-event:{segment.id}:{annotation.id}:{annotation.revision}",
            )
            events.append(VideoTimelineEvent(
                id=event_id,
                video_id=segment.video_id,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                subject_name=annotation.characters[0] if annotation.characters else None,
                entity_name=annotation.characters[0] if annotation.characters else None,
                entity_type="vehicle" if annotation.characters and is_known_vehicle_name(annotation.characters[0]) else None,
                action=action,
                scene=scene,
                road_surface=scene,
                environment=scene,
                objects=list(annotation.objects),
                visible_equipment=list(annotation.objects),
                ocr=list(annotation.ocr),
                evidence_segment_ids=[segment.id],
                segment_ids=[segment.id],
                frame_ids=[],
                time_basis="segment_range",
                temporal_basis="unknown",
                unknown_fields=["entity_id", "entity_track_id", "evidence_frame_ids", "observed_time"],
                unknown_conditions=["entity_id", "entity_track_id", "evidence_frame_ids", "observed_time"],
                protocol_version=PROTOCOL_VERSION,
            ))
    return events


def _event_summary(event: VideoTimelineEvent) -> str:
    """Compact Chinese-first timeline sentence for sequence-level retrieval.

    OCR is retained as detail, but OCR changes never create a sequence boundary.
    The timeline boundary is driven by visible subject/scene/source continuity.
    """
    parts: list[str] = []
    for value in (
        event.entity_name or event.subject_name,
        event.scene or event.environment,
        event.action,
    ):
        if value and value not in parts:
            parts.append(value)
    for value in event.objects[:2]:
        if value and value not in parts:
            parts.append(value)
    if event.ocr:
        ocr = " / ".join(event.ocr[:2])
        if ocr:
            parts.append(f"画面文字：{ocr}")
    return "，".join(parts) if parts else "未知事件"


def build_sequence_windows(
    events: Sequence[VideoTimelineEvent],
    *,
    maximum_window_ms: int = 90_000,
    adjacency_gap_ms: int = 1_500,
    source_cut_boundaries: Sequence[int] = (),
    pollution_ranges: Sequence[tuple[int, int, str]] = (),
) -> list[VideoSequenceWindow]:
    """Group content-driven events into long semantic sequences.

    The window is intentionally much longer than a fixed 5/10/15 second chunk.
    A stable visible subject may remain one sequence across OCR, action-phase or
    minor scene-label changes. Subject changes, explicit source cuts, severe
    pollution and large time gaps are boundaries. This lets a 40-second stage
    speech remain one retrievable process while still retaining timed sub-events.
    """
    ordered = sorted(events, key=lambda item: (item.start_ms, item.end_ms, str(item.id)))
    if not ordered:
        return []
    groups: list[list[VideoTimelineEvent]] = []
    current: list[VideoTimelineEvent] = []
    for event in ordered:
        if not current:
            current = [event]
            continue
        previous = current[-1]
        duration = event.end_ms - current[0].start_ms
        previous_track = previous.entity_track_id or previous.entity_id
        event_track = event.entity_track_id or event.entity_id
        same_entity = bool(previous_track and event_track and previous_track == event_track)
        same_subject = bool(
            previous.subject_name and event.subject_name
            and canonical_vehicle_name(previous.subject_name)
            == canonical_vehicle_name(event.subject_name)
        )
        same_scene = bool(previous.scene and event.scene and previous.scene == event.scene)
        gap = event.start_ms - previous.end_ms
        crosses_cut = any(previous.end_ms <= cut <= event.start_ms for cut in source_cut_boundaries)
        crosses_pollution = any(
            start < event.end_ms and end > previous.start_ms
            for start, end, _ in pollution_ranges
        )
        can_join = (
            event.video_id == previous.video_id
            and 0 <= gap <= adjacency_gap_ms
            and duration <= maximum_window_ms
            # Entity identity is strongest. A repeated named subject in the
            # same visible scene is enough for probable continuity; changing
            # OCR or sub-action does not split the sequence.
            and (same_entity or (same_subject and (same_scene or not previous.scene or not event.scene)))
            and not crosses_cut
            and not crosses_pollution
        )
        event.same_entity_as_previous = same_entity
        event.same_subject_as_previous = same_entity or same_subject
        event.same_scene_as_previous = same_scene
        event.continuity_confidence = (
            0.95 if can_join and same_entity else 0.75 if can_join and same_subject else 0.0
        )
        event.transition_type = (
            "source_cut" if crosses_cut else "pollution" if crosses_pollution
            else "subject_change" if not same_entity and not same_subject
            else "scene_change" if previous.scene != event.scene
            else "gap" if gap > adjacency_gap_ms else "continuation"
        )
        if can_join:
            current.append(event)
        else:
            groups.append(current)
            current = [event]
    if current:
        groups.append(current)

    windows: list[VideoSequenceWindow] = []
    for group in groups:
        first, last = group[0], group[-1]
        subjects = [event.entity_track_id or event.entity_id for event in group
                    if event.entity_track_id or event.entity_id]
        if len(group) == 1:
            status = "unknown_continuity"
        elif any(event.time_basis != "observed_interval" for event in group):
            status = "unknown_continuity"
        elif subjects and len(set(subjects)) == 1 and all(
            event.continuous_motion is True for event in group if event.action
        ) and any(event.action for event in group):
            status = "confirmed_continuity"
        else:
            status = "probable_continuity"
        summary_parts = list(dict.fromkeys(_event_summary(event) for event in group))
        window_id = uuid5(
            NAMESPACE_URL,
            f"clipatlas:window:{first.video_id}:{first.start_ms}:{last.end_ms}:"
            f"{','.join(str(event.id) for event in group)}",
        )
        windows.append(VideoSequenceWindow(
            id=window_id,
            video_id=first.video_id,
            start_ms=first.start_ms,
            end_ms=last.end_ms,
            event_ids=[event.id for event in group],
            ordered_summary="；随后".join(summary_parts),
            subject_ids=list(dict.fromkeys(subjects)),
            action_continuity=True if status == "confirmed_continuity" else None,
            scene_transitions=list(dict.fromkeys(
                f"{left.scene or 'unknown'}->{right.scene or 'unknown'}"
                for left, right in zip(group, group[1:]) if left.scene != right.scene
            )),
            source_cut_boundaries=[
                cut for cut in source_cut_boundaries if first.start_ms <= cut <= last.end_ms
            ],
            pollution_ranges=[
                (max(item[0], first.start_ms), min(item[1], last.end_ms), item[2])
                for item in pollution_ranges
                if item[0] < last.end_ms and item[1] > first.start_ms
            ],
            continuity_status=status,
            protocol_version=PROTOCOL_VERSION,
        ))
    return windows
