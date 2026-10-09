"""DeepSeek vision provider (OpenAI-compatible, image frames only).

DeepSeek V4-Flash-Vision-Exp (since 2026-08-21) is priced the same as V4-Flash
and takes still-image frames rather than native video, which matches ClipAtlas's
frame-based catalog annotation pipeline. Frame counts stay within the model's
per-image token budget by letting the caller control ``frame_uris``.
"""

from clipatlas.providers.openai_compat import OpenAICompatVideoProvider

_DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"
_DEFAULT_BASE_URL = "https://api.deepseek.com"


class DeepSeekVisionUnderstandingProvider(OpenAICompatVideoProvider):
    name = "deepseek-vision"
    _default_model = _DEFAULT_MODEL
    _native_video_input = False

    def __init__(self, api_key: str, local_frame_root, **kwargs):
        base_url = kwargs.pop("base_url", None) or _DEFAULT_BASE_URL
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            local_frame_root=local_frame_root,
            **kwargs,
        )
