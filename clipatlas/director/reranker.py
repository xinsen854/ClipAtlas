"""Optional one-shot API reranking over already-legal local candidates.

The reranker is an editorial preference layer, not an evidence layer.  Local
retrieval/evidence/media policy decides which candidates are legal and what
their match level is.  The API may only reorder candidate ids that already
exist in the supplied snapshot.  On any API/configuration/validation failure,
the deterministic local order is returned unchanged so rough-cut generation
continues.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_MODEL = "qwen3.8-flash"
RERANK_PROMPT_VERSION = "candidate-reranker-v1"


class RerankCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    match_level: str
    local_score: float
    subject: str | None = None
    action: str | None = None
    scene: str | None = None
    environment: str | None = None
    objects: list[str] = Field(default_factory=list)
    configurations: list[str] = Field(default_factory=list)
    quantities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    evidence_summary: str = ""
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    pollution_level: str | None = None
    presentation_type: str | None = None


class _Ranking(BaseModel):
    model_config = ConfigDict(extra="ignore")
    requirement_id: str
    candidate_ids: list[str] = Field(default_factory=list)


class _RerankPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rankings: list[_Ranking] = Field(default_factory=list)


_SYSTEM_PROMPT = """
你是自动粗剪系统的候选镜头导演重排层。输入候选已经经过本地证据与媒体准入检查。
你的任务只是在同一 requirement 的合法候选里，判断哪个画面更像人类剪辑师会选的镜头。

硬规则：
1. 只能返回输入中已经存在的 candidate_id，不能创造新的 candidate_id。
2. 不能改变 DIRECT/SUPPORT/RELATED/GENERIC 等本地等级，不能把 SUPPORT 升为 DIRECT。
3. 不能放行 REJECT、blocked、PPT、黑底不匹配文字等本地已禁候选。
4. 优先完整、连续、少切的画面；一句完整口播尽量使用一个连续镜头。
5. S 级重点优先选择能直接承载主体+动作+环境/关系的镜头，并尽量让核心证据可对齐口播重点。
6. 同样正确时，优先真实运动、主体明确、环境明确、构图自然的镜头；不要为了词面相似选择僵硬PPT/静态展台。
7. 输出顺序表示导演偏好，不表示事实等级。
8. 所有解释性语义使用简体中文；品牌、车型、技术缩写保留原文。

只输出 JSON：
{"rankings":[{"requirement_id":"...","candidate_ids":["c1","c2"]}]}
""".strip()


class CandidateReranker:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = DEFAULT_MODEL,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key is required")
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not model.strip():
            raise ValueError("model is required")
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()
        self._client = client
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _legal(candidates: list[RerankCandidate]) -> list[RerankCandidate]:
        return [
            candidate
            for candidate in candidates
            if candidate.match_level != "REJECT"
            and candidate.pollution_level != "blocked"
            and candidate.source_end_ms > candidate.source_start_ms
        ]

    @staticmethod
    def _local_order(candidates: list[RerankCandidate]) -> dict[str, list[str]]:
        grouped: dict[str, list[RerankCandidate]] = defaultdict(list)
        for candidate in CandidateReranker._legal(candidates):
            grouped[candidate.requirement_id].append(candidate)
        level_rank = {
            "DIRECT": 0,
            "SUPPORT": 1,
            "RELATED": 2,
            "GENERIC": 3,
            "SOURCE": 4,
            "REUSE": 5,
        }
        return {
            requirement_id: [candidate.candidate_id for candidate in sorted(
                values,
                key=lambda candidate: (
                    level_rank.get(candidate.match_level, 6),
                    -candidate.local_score,
                    -(candidate.source_end_ms - candidate.source_start_ms),
                    candidate.candidate_id,
                ),
            )]
            for requirement_id, values in grouped.items()
        }

    async def rank(self, candidates: list[RerankCandidate]) -> dict[str, list[str]]:
        legal = self._legal(candidates)
        fallback = self._local_order(legal)
        if not legal:
            return fallback

        payload = {
            "model": self._model,
            "enable_thinking": False,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"prompt_version": RERANK_PROMPT_VERSION,
                         "candidates": [candidate.model_dump(mode="json") for candidate in legal]},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            if self._client is not None:
                response = await self._post(self._client, payload)
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await self._post(client, payload)
            decoded = _RerankPayload.model_validate(json.loads(response))
        except (httpx.HTTPError, ValueError, TypeError):
            return fallback

        allowed_by_requirement = {
            requirement_id: set(candidate_ids)
            for requirement_id, candidate_ids in fallback.items()
        }
        result: dict[str, list[str]] = {}
        for ranking in decoded.rankings:
            allowed = allowed_by_requirement.get(ranking.requirement_id)
            if not allowed:
                continue
            ordered: list[str] = []
            for candidate_id in ranking.candidate_ids:
                if candidate_id in allowed and candidate_id not in ordered:
                    ordered.append(candidate_id)
            # API may omit candidates; keep them in deterministic local order
            # rather than dropping legal fallback options.
            ordered.extend(
                candidate_id
                for candidate_id in fallback[ranking.requirement_id]
                if candidate_id not in ordered
            )
            result[ranking.requirement_id] = ordered

        for requirement_id, candidate_ids in fallback.items():
            result.setdefault(requirement_id, candidate_ids)
        return result

    async def _post(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> str:
        response = await client.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("reranker response must be an object")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("reranker response missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ValueError("reranker response choice is invalid")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ValueError("reranker response message is invalid")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("reranker response content is empty")
        return content
