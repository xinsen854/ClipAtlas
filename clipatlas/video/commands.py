import asyncio
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class AsyncCommandRunner(Protocol):
    async def run(self, args: list[str]) -> CommandResult: ...


class SubprocessCommandRunner:
    def __init__(self, *, concurrency: int | None = None) -> None:
        if concurrency is not None and concurrency < 1:
            raise ValueError("concurrency must be positive")
        self._slots = asyncio.Semaphore(concurrency) if concurrency is not None else None

    async def run(self, args: list[str]) -> CommandResult:
        queued = time.monotonic()
        if self._slots is not None:
            async with self._slots:
                logging.getLogger(__name__).info(
                    "local command=%s wait=%.3fs", args[0], time.monotonic() - queued,
                )
                return await self._run(args)
        return await self._run(args)

    async def _run(self, args: list[str]) -> CommandResult:
        started = time.monotonic()
        if sys.platform == "win32":
            # 打包版主程序为 windowed 子系统（PyInstaller console=False），
            # 宿主没有控制台。若不指定 CREATE_NO_WINDOW，每个 ffmpeg/ffprobe
            # 子进程都会新建一个黑色控制台窗口 —— 素材解析时表现为疯狂弹窗。
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        try:
            stdout_bytes, stderr_bytes = await process.communicate()
        except BaseException:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.communicate(), timeout=5)
                except TimeoutError:
                    if process.returncode is None:
                        process.kill()
                    await process.communicate()
            raise
        logging.getLogger(__name__).info(
            "local command=%s elapsed=%.3fs exit=%s", args[0],
            time.monotonic() - started, process.returncode,
        )
        returncode = process.returncode
        if returncode is None:
            raise RuntimeError("subprocess completed without a return code")
        return CommandResult(
            returncode=returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )
