import json

import pytest

from clipatlas.asr.qwen import QwenAudioASRProvider
from clipatlas.providers.errors import ProviderRequestError


def parse_line(payload: dict) -> list:
    return QwenAudioASRProvider._parse_event(json.dumps(payload, ensure_ascii=False))


def test_no_speech_returns_empty():
    # 纯音乐 / 无口播：合法 JSON 但没有 sentence → 空结果，不算错误
    assert parse_line({"output": {}}) == []
    assert parse_line({"output": {"sentence": None}}) == []
    assert parse_line({"output": {"sentence": {}}}) == []
    assert parse_line({}) == []


def test_sentence_without_end_returns_empty():
    assert parse_line({"output": {"sentence": {"text": "你好"}}}) == []


def test_normal_sentence_parsed():
    result = parse_line(
        {
            "output": {
                "sentence": {
                    "begin_time": 1000,
                    "end_time": 2000,
                    "text": "你好",
                    "words": [],
                    "sentence_end": True,
                }
            }
        }
    )
    assert len(result) == 1
    assert result[0].start_ms == 1000
    assert result[0].text == "你好"


def test_upstream_error_code_raises():
    with pytest.raises(ProviderRequestError) as exc_info:
        parse_line({"code": "Throttling", "message": "rate limit"})
    assert "Throttling" in str(exc_info.value)
    assert "rate limit" in str(exc_info.value)


def test_no_words_error_means_no_speech():
    # DashScope 对纯音乐/无声视频显式返回 ASR_RESPONSE_HAVE_NO_WORDS → 视为无语音，不算错误
    assert parse_line({"code": "CLIENT_ERROR", "message": "ASR_RESPONSE_HAVE_NO_WORDS"}) == []
    assert parse_line({"code": "CLIENT_ERROR", "message": "asr_response_have_no_words"}) == []


def test_invalid_json_raises_with_context():
    with pytest.raises(ProviderRequestError) as exc_info:
        QwenAudioASRProvider._parse_event("not-json{{{")
    assert "invalid response payload" in str(exc_info.value)


def test_non_dict_raises():
    with pytest.raises(ProviderRequestError):
        QwenAudioASRProvider._parse_event("[1,2,3]")


def test_sse_text_without_content_type_header():
    # 服务端返回 SSE 但没声明 text/event-stream → 整包按 SSE 行解析
    text = (
        'data: {"output":{"sentence":{"begin_time":100,"end_time":200,'
        '"text":"第一句","words":[],"sentence_end":true}}}\n\n'
        'data: {"output":{"sentence":{"begin_time":300,"end_time":400,'
        '"text":"第二句","words":[],"sentence_end":true}}}\n\n'
        "data: [DONE]\n"
    )
    result = QwenAudioASRProvider._parse_sse_text(text)
    assert [s.text for s in result] == ["第一句", "第二句"]


def test_sse_text_with_only_music_returns_empty():
    text = 'data: {"output":{}}\n\ndata: [DONE]\n'
    assert QwenAudioASRProvider._parse_sse_text(text) == []
