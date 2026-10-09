from fastapi import APIRouter, Request

from clipatlas.providers.contracts import AnalyzeSegmentRequest, AnalyzeSegmentResult
from clipatlas.providers.registry import ProviderRegistry

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


def _registry(request: Request) -> ProviderRegistry:
    registry = request.app.state.provider_registry
    if not isinstance(registry, ProviderRegistry):
        raise TypeError("provider registry is not configured")
    return registry


@router.get("")
async def list_providers(request: Request) -> dict[str, object]:
    descriptors = _registry(request).list_descriptors()
    return {"providers": [descriptor.model_dump(mode="json") for descriptor in descriptors]}


@router.post("/{provider_name}/analyze-segment", response_model=AnalyzeSegmentResult)
async def analyze_segment(
    provider_name: str,
    payload: AnalyzeSegmentRequest,
    request: Request,
) -> AnalyzeSegmentResult:
    provider = _registry(request).get(provider_name)
    return await provider.analyze_segment(payload)
