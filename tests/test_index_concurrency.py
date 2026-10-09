import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from clipatlas.concurrency import bounded_map, drain_on_cancel
from clipatlas.providers.errors import ProviderAuthenticationError, ProviderRateLimitError
from clipatlas.providers.requests import RequestPolicy, check_retryable_response


@pytest.mark.asyncio
async def test_bounded_work_overlaps_preserves_order_and_limits_materialized_inputs():
    gates = [asyncio.Event() for _ in range(6)]
    entered = []

    async def call(i):
        entered.append(i)
        await gates[i].wait()
        return i

    task = asyncio.create_task(bounded_map(range(6), call, concurrency=3))
    for _ in range(5):
        await asyncio.sleep(0)
    assert entered == [0, 1, 2]
    gates[2].set()
    for _ in range(5):
        await asyncio.sleep(0)
    assert entered == [0, 1, 2, 3]
    for gate in gates:
        gate.set()
    assert await task == list(range(6))


@pytest.mark.asyncio
async def test_failure_stops_new_work_but_drains_accepted_calls():
    fail = asyncio.Event()
    release = asyncio.Event()
    entered, saved = [], []

    async def call(i):
        entered.append(i)
        if i == 0:
            await fail.wait()
            raise ValueError("bad chunk")
        await release.wait()
        saved.append(i)

    task = asyncio.create_task(bounded_map(range(1000), call, concurrency=3))
    for _ in range(5):
        await asyncio.sleep(0)
    fail.set()
    for _ in range(5):
        await asyncio.sleep(0)
    assert not task.done() and entered == [0, 1, 2]
    release.set()
    with pytest.raises(ValueError, match="bad chunk"):
        await task
    assert saved == [1, 2]
    assert entered == [0, 1, 2]


@pytest.mark.asyncio
async def test_cancel_waits_for_checkpoint_and_does_not_start_more_parts():
    gate = asyncio.Event()
    entered, saved = [], []

    async def call(i):
        entered.append(i)
        await gate.wait()
        saved.append(i)

    task = asyncio.create_task(bounded_map(range(1000), call, concurrency=2))
    for _ in range(5):
        await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert entered == saved == [0, 1]


@pytest.mark.asyncio
async def test_cancelled_sdk_adapter_keeps_ownership_until_thread_finishes():
    entered, release = threading.Event(), threading.Event()

    def blocking_sdk():
        entered.set()
        release.wait(3)
        return 1

    task = asyncio.create_task(drain_on_cancel(asyncio.to_thread(blocking_sdk)))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_http_retry_after_rate_gate_and_authentication_not_retried(monkeypatch):
    import clipatlas.providers.requests as module
    now, sleeps = [0.0], []

    async def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(Lock=asyncio.Lock, sleep=sleep))
    policy = RequestPolicy(rpm=60, max_retries=2)
    calls = []

    async def request():
        calls.append(now[0])
        if len(calls) == 1:
            check_retryable_response(httpx.Response(429, headers={"Retry-After": "7"}))
        return "recognized"

    assert await policy.run(request) == "recognized"
    assert calls == [0.0, 7.0]
    await policy.run(request)
    assert calls[-1] == 8.0

    async def denied():
        calls.append(now[0])
        raise ProviderAuthenticationError("HTTP 403")

    before = len(calls)
    with pytest.raises(ProviderAuthenticationError):
        await policy.run(denied)
    assert len(calls) == before + 1

    async def throttled():
        calls.append(now[0])
        check_retryable_response(httpx.Response(429))

    before = len(calls)
    with pytest.raises(ProviderRateLimitError):
        await policy.run(throttled)
    assert len(calls) == before + 3


def test_embedding_gate_is_thread_safe_and_retry_attempts_pass_through_gate(monkeypatch):
    import clipatlas.embeddings.cloud_requests as module
    import clipatlas.vendor.sentrysearch.qwen_cloud_embedder as vendor
    now = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(
        monotonic=lambda: now[0], sleep=lambda delay: now.__setitem__(0, now[0] + delay),
    ))
    monkeypatch.setattr(vendor, "time", module.time)
    limiter = module.RateLimiter(60)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: limiter.wait(), range(5)))
    assert now[0] == 4.0

    class Response(dict):
        def __init__(self, code):
            self.status_code = code
            super().__init__(code="Throttling", output={"embeddings": [{"embedding": [1.0]}]})

    calls = []

    def call(**kwargs):
        calls.append(now[0])
        return Response(429 if len(calls) == 1 else 200)

    embedder = object.__new__(module.ConcurrentQwenCloudEmbedder)
    embedder._admission = limiter
    embedder._MultiModalEmbedding = SimpleNamespace(call=call)
    embedder._model, embedder._api_key = "qwen3-vl-embedding", "fixture-key"
    assert embedder._embed_one([], {}, verbose=False, label="test") == [1.0]
    assert len(calls) == 2 and calls[1] - calls[0] >= 2


@pytest.mark.asyncio
async def test_local_gate_and_cancel_reap_subprocess(monkeypatch):
    from clipatlas.video.commands import SubprocessCommandRunner
    active, peak = [0], [0]
    gate, entered = asyncio.Event(), asyncio.Event()
    processes = []

    class Process:
        returncode = None

        async def communicate(self):
            await gate.wait()
            if self.returncode is None:
                self.returncode = 0
                active[0] -= 1
            return b"", b""

        def terminate(self):
            self.returncode = -1
            active[0] -= 1
            gate.set()

    async def spawn(*args, **kwargs):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        p = Process()
        processes.append(p)
        entered.set()
        return p

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    runner = SubprocessCommandRunner(concurrency=1)
    first = asyncio.create_task(runner.run(["ffmpeg"]))
    second = asyncio.create_task(runner.run(["ffmpeg"]))
    await entered.wait()
    await asyncio.sleep(0)
    assert len(processes) == peak[0] == 1
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert peak[0] == 1 and active[0] == 0
