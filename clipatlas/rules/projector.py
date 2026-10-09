from clipatlas.rules.models import (
    ProjectRulePack,
    ProjectedText,
    RuleKind,
)


class ProjectTextProjector:
    def project(self, source_text: str, pack: ProjectRulePack) -> ProjectedText:
        speech_text = source_text
        subtitle_text = source_text
        retrieval_text = source_text
        semantic_hints: list[str] = []
        aliases: list[str] = []

        for rule in pack.rules:
            if not rule.enabled:
                continue

            if rule.kind in {RuleKind.PRONUNCIATION, RuleKind.SPEECH_REPLACE}:
                assert rule.match is not None
                assert rule.replacement is not None
                speech_text = speech_text.replace(rule.match, rule.replacement)
                continue

            if rule.kind == RuleKind.SPEECH_SUPPRESS:
                assert rule.match is not None
                speech_text = speech_text.replace(rule.match, "")
                continue

            if rule.kind == RuleKind.SUBTITLE_REPLACE:
                assert rule.match is not None
                assert rule.replacement is not None
                subtitle_text = subtitle_text.replace(rule.match, rule.replacement)
                continue

            if rule.kind == RuleKind.ENTITY_ALIAS:
                assert rule.match is not None
                assert rule.replacement is not None
                if rule.match in source_text and rule.replacement not in aliases:
                    aliases.append(rule.replacement)
                continue

            if rule.kind == RuleKind.SEMANTIC_HINT:
                assert rule.hint is not None
                semantic_hints.append(rule.hint)

        if aliases:
            retrieval_text = f"{retrieval_text} {' '.join(aliases)}"

        return ProjectedText(
            canonical_text=source_text,
            speech_text=speech_text,
            subtitle_text=subtitle_text,
            retrieval_text=retrieval_text,
            semantic_hints=semantic_hints,
        )
