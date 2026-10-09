from dataclasses import dataclass
from typing import Literal, cast

import httpx

from clipatlas.settings.bailian import derive_bailian_endpoints

ServiceKind = Literal["video", "embedding", "speech"]
BailianModelStatus = Literal["available", "unavailable", "undetected"]
# (detection_id, model_id, display_label) - 检测面板逐项显示，模型相同只查一次。
BAILIAN_DETECTION_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("video_embedding", "qwen3-vl-embedding", "视频向量"),
    ("video_understanding", "qwen3.8-flash", "视频理解"),
    ("ocr", "qwen3.5-ocr", "OCR"),
    ("asr", "qwen-audio-3.0-asr-flash", "ASR"),
    ("media_type", "qwen3.8-flash", "画面类型标注"),
    ("director", "qwen3.8-flash", "文案解析"),
)

# 兼容旧引用：唯一模型 id 列表
BAILIAN_REQUIRED_MODELS: tuple[str, ...] = tuple(
    dict.fromkeys(model_id for _, model_id, _ in BAILIAN_DETECTION_ITEMS)
)

_DASHSCOPE_SPEECH_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
)


@dataclass(frozen=True)
class ServiceProbeRequest:
    service: ServiceKind
    provider: str
    api_key: str
    base_url: str
    model: str
    dimensions: int | None = None


@dataclass(frozen=True)
class ServiceProbeResult:
    ok: bool
    code: str
    message: str


@dataclass(frozen=True)
class ModelListResult:
    supported: bool
    models: list[str]


@dataclass(frozen=True)
class BailianModelDetectionResult:
    ok: bool
    code: str
    message: str
    models: dict[str, BailianModelStatus]


class ServiceProbe:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            payload = cast(object, response.json())
        except ValueError:
            return response.text.strip() or f"HTTP {response.status_code}"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return f"HTTP {response.status_code}"

    @staticmethod
    def _failure(response: httpx.Response) -> ServiceProbeResult:
        detail = ServiceProbe._detail(response)
        lowered = detail.lower()
        if response.status_code == 401:
            return ServiceProbeResult(False, "auth_failed", "API Key 无效或已过期。")
        if response.status_code == 403:
            return ServiceProbeResult(False, "forbidden", "当前 API Key 没有访问权限。")
        if response.status_code == 404:
            return ServiceProbeResult(False, "not_found", "接口地址不存在或 Base URL 不正确。")
        if response.status_code == 429:
            return ServiceProbeResult(False, "rate_limited", "服务请求过于频繁，请稍后重试。")
        if "model" in lowered and any(
            marker in lowered
            for marker in ("not found", "does not exist", "unsupported", "invalid")
        ):
            return ServiceProbeResult(False, "model_unavailable", "当前模型不可用或模型名称不正确。")
        return ServiceProbeResult(False, "upstream_error", f"上游服务返回错误：{detail}")

    @staticmethod
    def _undetected_bailian_models() -> dict[str, BailianModelStatus]:
        return {
            detection_id: "undetected"
            for detection_id, _, _ in BAILIAN_DETECTION_ITEMS
        }

    async def _post(
        self,
        url: str,
        request: ServiceProbeRequest,
        payload: dict[str, object],
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            return await client.post(url, headers=self._headers(request.api_key), json=payload)

    async def test_connection(self, request: ServiceProbeRequest) -> ServiceProbeResult:
        base_url = request.base_url.rstrip("/")
        if (
            request.service == "speech"
            and request.provider == "dashscope"
            and "dashscope.aliyuncs.com" in base_url
            and "/compatible-mode/" in base_url
        ):
            base_url = _DASHSCOPE_SPEECH_ENDPOINT
        try:
            if request.service == "video":
                response = await self._post(
                    f"{base_url}/chat/completions",
                    request,
                    {
                        "model": request.model,
                        "messages": [{"role": "user", "content": "ping"}],
                    },
                )
            elif request.service == "embedding":
                payload: dict[str, object] = {
                    "model": request.model,
                    "input": ["ping"],
                }
                if request.dimensions is not None:
                    payload["dimensions"] = request.dimensions
                response = await self._post(f"{base_url}/embeddings", request, payload)
            else:
                response = await self._post(
                    base_url,
                    request,
                    {"model": request.model, "input": {"text": "ping"}},
                )
        except httpx.TimeoutException:
            return ServiceProbeResult(False, "timeout", "连接超时，请检查网络或 Base URL。")
        except httpx.HTTPError:
            return ServiceProbeResult(False, "network_error", "无法连接上游服务，请检查网络或 Base URL。")

        if response.is_success:
            return ServiceProbeResult(True, "ok", "连接成功。")

        detail = self._detail(response).lower()
        if request.service == "speech" and response.status_code in {400, 422}:
            model_error = "model" in detail and any(
                marker in detail
                for marker in ("not found", "does not exist", "unsupported", "invalid")
            )
            if not model_error:
                return ServiceProbeResult(
                    True,
                    "ok",
                    "服务已连接；当前测试请求未指定音色。",
                )
        return self._failure(response)

    async def list_models(self, request: ServiceProbeRequest) -> ModelListResult:
        if request.service == "speech":
            return ModelListResult(supported=False, models=[])

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    f"{request.base_url.rstrip('/')}/models",
                    headers=self._headers(request.api_key),
                )
        except httpx.HTTPError:
            return ModelListResult(supported=False, models=[])

        if response.is_error:
            return ModelListResult(supported=False, models=[])
        try:
            payload = cast(object, response.json())
        except ValueError:
            return ModelListResult(supported=False, models=[])
        if not isinstance(payload, dict):
            return ModelListResult(supported=False, models=[])
        data = payload.get("data")
        if not isinstance(data, list):
            return ModelListResult(supported=False, models=[])

        models = sorted(
            {
                model_id
                for item in data
                if isinstance(item, dict)
                and isinstance((model_id := item.get("id")), str)
                and model_id.strip()
            }
        )
        return ModelListResult(supported=True, models=models)

    async def detect_bailian_models(
        self,
        *,
        api_key: str,
        base_url: str,
    ) -> BailianModelDetectionResult:
        undetected = self._undetected_bailian_models()
        try:
            endpoints = derive_bailian_endpoints(base_url)
        except ValueError:
            return BailianModelDetectionResult(
                ok=False,
                code="invalid_base_url",
                message="百炼 Base URL 必须是 aliyuncs.com 的 Workspace 或 DashScope 地址。",
                models=undetected,
            )

        models: dict[str, BailianModelStatus] = {}
        model_to_items: dict[str, list[str]] = {}
        for detection_id, model_id, _label in BAILIAN_DETECTION_ITEMS:
            model_to_items.setdefault(model_id, []).append(detection_id)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                for model_id, item_ids in model_to_items.items():
                    response = await client.get(
                        f"{endpoints.dashscope_api_root}/models",
                        headers=self._headers(api_key),
                        params={"model": model_id, "page_no": 1, "page_size": 1},
                    )
                    if response.is_error:
                        failure = self._failure(response)
                        return BailianModelDetectionResult(
                            ok=False,
                            code=failure.code,
                            message=failure.message,
                            models=undetected,
                        )

                    try:
                        payload = cast(object, response.json())
                    except ValueError:
                        payload = None
                    output = payload.get("output") if isinstance(payload, dict) else None
                    data = output.get("models") if isinstance(output, dict) else None
                    if not isinstance(data, list):
                        return BailianModelDetectionResult(
                            ok=False,
                            code="invalid_response",
                            message="百炼模型目录返回了无法识别的数据。",
                            models=undetected,
                        )

                    available_ids = {
                        available_id
                        for item in data
                        if isinstance(item, dict)
                        and isinstance((available_id := item.get("model")), str)
                        and available_id.strip()
                    }
                    status: BailianModelStatus = (
                        "available" if model_id in available_ids else "unavailable"
                    )
                    for detection_id in item_ids:
                        models[detection_id] = status
        except httpx.TimeoutException:
            return BailianModelDetectionResult(
                ok=False,
                code="timeout",
                message="读取百炼模型目录超时。",
                models=undetected,
            )
        except httpx.HTTPError:
            return BailianModelDetectionResult(
                ok=False,
                code="network_error",
                message="无法连接百炼模型目录。",
                models=undetected,
            )

        return BailianModelDetectionResult(
            ok=True,
            code="ok",
            message="模型目录读取成功。",
            models=models,
        )
