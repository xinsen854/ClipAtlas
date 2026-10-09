from clipatlas.domain.models import SemanticAnnotation

_PREDICATE_LABELS = {
    "identity": "身份",
    "presence": "出现",
    "action": "动作",
    "configuration": "配置",
    "scene": "场景",
    "quantity": "数量",
    "relation": "关系",
}


def _list_line(label: str, values: list[str]) -> str | None:
    cleaned = [value.strip() for value in values if value.strip()]
    if not cleaned:
        return None
    return f"{label}: {', '.join(cleaned)}"


def _value_line(label: str, value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return f"{label}: {cleaned}"


def build_retrieval_text(annotation: SemanticAnnotation) -> str:
    lines: list[str] = []
    description = annotation.description.strip()
    if description:
        lines.append(description)

    candidates = (
        _list_line("人物", annotation.characters),
        _list_line("动作", annotation.actions),
        _list_line("场景", annotation.scene),
        _list_line("情绪", annotation.emotions),
        _list_line("物体", annotation.objects),
        _list_line("原始OCR", annotation.ocr),
        _value_line("景别", annotation.shot_type),
        _value_line("运镜", annotation.camera_motion),
        _list_line("事实", [fact.value for fact in annotation.facts]),
        _list_line("结构化命题", [
            " ".join(str(v) for v in (
                fact.statement.proposition.subject,
                _PREDICATE_LABELS[fact.statement.proposition.predicate],
                fact.statement.proposition.value, fact.statement.proposition.unit,
                fact.statement.proposition.scope,
            ) if v) for fact in annotation.facts if fact.statement is not None
        ]),
    )
    lines.extend(line for line in candidates if line is not None)
    return "\n".join(lines)
