import pytest

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.providers.contracts import (
    AnalyzeSegmentRequest,
    AnalyzeSegmentResult,
    ProviderCapabilities,
)
from clipatlas.providers.errors import ProviderNotFoundError
from clipatlas.providers.registry import ProviderRegistry


class StubProvider:
    def __init__(self, name: str, capabilities: ProviderCapabilities):
        self._name = name
        self._capabilities = capabilities

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def analyze_segment(self, request: AnalyzeSegmentRequest) -> AnalyzeSegmentResult:
        return AnalyzeSegmentResult(
            provider=self.name,
            model="stub",
            annotation=SemanticAnnotation(
                segment_id=request.segment_id,
                origin=AnnotationOrigin.AI,
                provider=self.name,
                model="stub",
                description="stub",
            ),
        )


def test_registry_rejects_duplicate_provider_name():
    registry = ProviderRegistry()
    provider = StubProvider("same", ProviderCapabilities(image_input=True))
    registry.register(provider)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(StubProvider("same", ProviderCapabilities(native_video_input=True)))


def test_registry_filters_by_required_capabilities():
    registry = ProviderRegistry()
    both = StubProvider(
        "both",
        ProviderCapabilities(image_input=True, structured_output=True),
    )
    image_only = StubProvider("image-only", ProviderCapabilities(image_input=True))
    native_video = StubProvider(
        "video",
        ProviderCapabilities(native_video_input=True, structured_output=True),
    )
    registry.register(both)
    registry.register(image_only)
    registry.register(native_video)

    matches = registry.find(ProviderCapabilities(image_input=True, structured_output=True))

    assert [provider.name for provider in matches] == ["both"]


def test_registry_raises_provider_not_found():
    registry = ProviderRegistry()

    with pytest.raises(ProviderNotFoundError, match="missing"):
        registry.get("missing")


def test_registry_lists_provider_descriptors():
    registry = ProviderRegistry()
    registry.register(
        StubProvider("video", ProviderCapabilities(native_video_input=True, temporal_search=True))
    )

    descriptors = registry.list_descriptors()

    assert descriptors[0].name == "video"
    assert descriptors[0].capabilities.native_video_input is True
    assert descriptors[0].capabilities.temporal_search is True
