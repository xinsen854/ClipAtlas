"""Director service: analyse once, cache forever, map onto beats, fit locally."""

import asyncio
import inspect

from collections.abc import Sequence

from clipatlas.director.analyzer import DirectorAnalyzer
from clipatlas.director.local_fit import LocalFitVerdict, fit
from clipatlas.director.mapper import map_units_to_beats
from clipatlas.director.models import DirectorAnalysis, DirectorUnit
from clipatlas.director.store import DirectorCacheStore
from clipatlas.domain.models import SemanticAnnotation
from clipatlas.domain.visual_protocol import PROTOCOL_VERSION
from clipatlas.director.requirements import parse_script_visual_requirements
from clipatlas.roughcut.models import ScriptBeat


class DirectorService:
    """Aggregates the cache-first one-shot analysis with local mapping/fitting.

    The service is inert when ``enabled=False``: the planner then keeps its
    previous behaviour exactly.
    """

    def __init__(
        self,
        analyzer: DirectorAnalyzer,
        store: DirectorCacheStore,
        *,
        enabled: bool = True,
    ) -> None:
        self._analyzer = analyzer
        self._store = store
        self._enabled = enabled
        # 单飞锁：同一 (script_hash, prompt_version, rules_revision) 只允许
        # 一个请求真正调用 API，其余并发请求等待后直接读缓存。
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def analyze(self, script_text: str) -> DirectorAnalysis:
        """Cache-first full-script grading; one API call per script at most."""
        return await self.analyze_cached(script_text)

    async def analyze_cached(
        self, script_text: str, rules_revision: str | None = None,
        *, rules_text: str = "",
    ) -> DirectorAnalysis:
        try:
            empty = self._analyzer._empty_analysis(script_text, rules_revision)
        except TypeError:
            empty = self._analyzer._empty_analysis(script_text)
        if not script_text.strip():
            return empty
        key = (empty.script_hash, empty.prompt_version, empty.rules_revision)
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
        async with lock:
            cached = self._store.get_by_key(*key)
            if cached is not None:
                if not cached.requirements:
                    cached = cached.model_copy(update={
                        "requirements": parse_script_visual_requirements(cached.script_text),
                    })
                # Keep the persisted analysis value stable across cache hits;
                # request/cache counters belong in the execution audit layer.
                return cached.model_copy(update={
                    "status": "ready" if cached.protocol_version == PROTOCOL_VERSION else "legacy",
                })
            parameters = inspect.signature(self._analyzer.analyze).parameters
            kwargs = {}
            if "rules_revision" in parameters:
                kwargs["rules_revision"] = rules_revision
            if "rules_text" in parameters:
                kwargs["rules_text"] = rules_text
            try:
                analysis = await self._analyzer.analyze(script_text, **kwargs)
            except Exception:
                previous = self._store.get_previous_version(empty.script_hash, empty.rules_revision)
                if previous is None:
                    raise
                return previous.model_copy(update={
                    "requirements": previous.requirements or parse_script_visual_requirements(
                        previous.script_text
                    ),
                    "status": "legacy",
                    "contract_issues": [
                        *previous.contract_issues,
                        "新版 Director 分析失败，使用旧版缓存；结构化证据协议尚待升级",
                    ],
                })
            self._store.put(analysis)
            return analysis

    def map_units(self, beats: Sequence[ScriptBeat], analysis: DirectorAnalysis) -> list[DirectorUnit]:
        return map_units_to_beats(beats, analysis.units)

    @staticmethod
    def fit(unit: DirectorUnit, annotation: SemanticAnnotation | None) -> LocalFitVerdict:
        return fit(unit, annotation)


async def analyze_director_units(
    analyzer: DirectorAnalyzer,
    store: DirectorCacheStore,
    script_text: str,
) -> DirectorAnalysis:
    """Backwards-compatible free function kept for callers of the first batch."""
    service = DirectorService(analyzer=analyzer, store=store)
    return await service.analyze_cached(script_text)
