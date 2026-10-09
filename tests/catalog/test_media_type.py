import base64
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from clipatlas.catalog.media_type import (
    MEDIA_TYPE_PROMPT_VERSION,
    MediaTypeAnalyzer,
    MediaTypeResult,
    is_editable,
)
from clipatlas.providers.errors import ProviderRequestError


def test_is_editable_rules() -> None:
    assert not is_editable("title_card")
    assert is_editable("scene")
    assert not is_editable("screen_capture")
    assert is_editable("cg")
    assert not is_editable("technical_chart")


class _FakeClient(httpx.AsyncClient):
    def __init__(self, payload: dict) -> None:
        super().__init__()
        self._payload = payload
        self.sent: dict | None = None

    async def post(self, url: str, **kwargs) -> httpx.Response:
        self.sent = kwargs.get("json")
        return httpx.Response(
            200,
            json=self._payload,
            request=httpx.Request("POST", url),
        )


async def test_classify_builds_vision_payload_and_parses(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    fake = _FakeClient({
        "choices": [{
            "message": {
                "content": (
                    '{"subject_medium": "title_card", "text_ratio": 0.9, '
                    '"has_real_subject": false, "reason": "full black card"}'
                ),
            }
        }]
    })
    analyzer = MediaTypeAnalyzer(
        api_key="key",
        base_url="https://example.com/v1",
        client=fake,
    )
    result = await analyzer.classify(image)

    assert result.subject_medium == "title_card"
    assert result.text_ratio == 0.9
    assert result.has_real_subject is False
    assert fake.sent is not None
    assert fake.sent["model"] == "qwen3.8-flash"
    assert fake.sent["response_format"] == {"type": "json_object"}
    user_content = fake.sent["messages"][1]["content"]
    assert user_content[0]["type"] == "image_url"
    expected = "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    assert user_content[0]["image_url"]["url"] == expected


async def test_classify_rejects_invalid_json(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    fake = _FakeClient({"choices": [{"message": {"content": "not json"}}]})
    analyzer = MediaTypeAnalyzer(
        api_key="key",
        base_url="https://example.com/v1",
        client=fake,
    )
    with pytest.raises(ProviderRequestError):
        await analyzer.classify(image)


def test_media_type_result_defaults() -> None:
    result = MediaTypeResult(subject_medium="scene")
    assert result.text_ratio == 0.0
    assert result.text_block_count == 0
    assert result.has_real_subject is True
    assert MEDIA_TYPE_PROMPT_VERSION == "media-type-v3-primary-content"


def test_analyzer_requires_key_and_base_url() -> None:
    with pytest.raises(ValueError):
        MediaTypeAnalyzer(api_key="", base_url="https://example.com")
    with pytest.raises(ValueError):
        MediaTypeAnalyzer(api_key="key", base_url="   ")
