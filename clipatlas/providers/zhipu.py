"""Zhipu GLM video-understanding provider (OpenAI-compatible).

Validated zero-cost route: GLM-4.1V-Thinking-Flash offers a free tier with
native temporal video understanding and generous new-user tokens, which suits
ClipAtlas's one-shot catalog annotation step.
"""

from clipatlas.providers.openai_compat import OpenAICompatVideoProvider

_DEFAULT_MODEL = "glm-4.1v-thinking-flash"
_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


class GLMVideoUnderstandingProvider(OpenAICompatVideoProvider):
    name = "zhipu-glm"
    _default_model = _DEFAULT_MODEL
    _native_video_input = True

    def __init__(self, api_key: str, local_frame_root, **kwargs):
        base_url = kwargs.pop("base_url", None) or _DEFAULT_BASE_URL
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            local_frame_root=local_frame_root,
            **kwargs,
        )
