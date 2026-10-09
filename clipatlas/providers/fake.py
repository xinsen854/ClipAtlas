from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.providers.contracts import (
    AnalyzeSegmentRequest,
    AnalyzeSegmentResult,
    ProviderCapabilities,
)


class FakeVideoUnderstandingProvider:
    @property
    def name(self) -> str:
        return "fake"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(image_input=True, structured_output=True)

    async def analyze_segment(self, request: AnalyzeSegmentRequest) -> AnalyzeSegmentResult:
        annotation = SemanticAnnotation(
            segment_id=request.segment_id,
            origin=AnnotationOrigin.AI,
            provider=self.name,
            model="fake-v1",
            description="Synthetic semantic description for test segment",
            characters=["synthetic-subject"],
            actions=["synthetic-action"],
            scene=["synthetic-scene"],
            raw_payload={
                "video_id": str(request.video_id),
                "start_ms": request.start_ms,
                "end_ms": request.end_ms,
                "source_uri": request.source_uri,
            },
        )
        return AnalyzeSegmentResult(provider=self.name, model="fake-v1", annotation=annotation)
