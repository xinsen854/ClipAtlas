from uuid import UUID

from clipatlas.exports.models import JianyingDraftArtifact


class GeneratedArtifactRegistry:
    def __init__(self) -> None:
        self._jianying_by_plan: dict[UUID, JianyingDraftArtifact] = {}

    def register_jianying(self, artifact: JianyingDraftArtifact) -> None:
        self._jianying_by_plan[artifact.plan_id] = artifact

    def get_jianying(self, plan_id: UUID) -> JianyingDraftArtifact | None:
        return self._jianying_by_plan.get(plan_id)

    def discard(self, plan_id: UUID) -> None:
        self._jianying_by_plan.pop(plan_id, None)
