"""How the worker starts a stage child: what it runs, and the environment it gets (#128)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sophia.worker import runner
from sophia.worker.stage import KNOWLEDGE, MEDIA

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _one_line() -> AsyncIterator[bytes]:
    yield b"stage output\n"


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdout = _one_line()

    async def wait(self) -> int:
        self.returncode = 0
        return 0


@pytest.mark.asyncio
async def test_stage_children_log_unbuffered_and_only_the_knowledge_one_loses_the_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[tuple[tuple[str, ...], dict[str, str]]] = []

    async def fake_exec(*args: str, **kwargs: Any) -> _FakeProcess:
        started.append((args, kwargs["env"]))
        return _FakeProcess()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

    media = await runner.run_stage_in_subprocess(MEDIA, 3022060, 82774, 1)
    knowledge = await runner.run_stage_in_subprocess(KNOWLEDGE, 3022060, 82774, 1)

    assert (media.returncode, media.output_tail) == (0, "stage output")
    assert (knowledge.returncode, knowledge.output_tail) == (0, "stage output")
    (media_args, media_env), (knowledge_args, knowledge_env) = started
    assert media_args[1:6] == ("-m", "sophia", "worker", "stage", MEDIA)
    assert knowledge_args[1:6] == ("-m", "sophia", "worker", "stage", KNOWLEDGE)
    assert media_args[6:] == ("3022060", "--course-id", "82774", "--job-id", "1")
    # The log of a stage that runs for twenty minutes must not arrive at the end of it.
    assert media_env["PYTHONUNBUFFERED"] == "1"
    assert knowledge_env["PYTHONUNBUFFERED"] == "1"
    # Whisper keeps the GPU; PyTorch has no kernels for it, so embedding never sees it.
    assert media_env["CUDA_VISIBLE_DEVICES"] == "0"
    assert knowledge_env["CUDA_VISIBLE_DEVICES"] == ""
