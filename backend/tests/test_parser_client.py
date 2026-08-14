from pathlib import Path

import pytest

from app.parsers.python_ast import ParserLimits
from app.services.parser_client import (
    ParserClient,
    ParserClientError,
    ParserTimeoutError,
)


@pytest.mark.asyncio
async def test_parser_client_runs_isolated_runner(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "service.py").write_text(
        "class Service:\n    def run(self):\n        return True\n",
        encoding="utf-8",
    )
    client = ParserClient(timeout_seconds=5)

    result = await client.parse(
        repository,
        ["service.py"],
        ParserLimits(20, 20_000, 100_000, 200),
    )

    assert result.files[0].symbols[0].qualified_name == "Service"
    assert result.python_version


@pytest.mark.asyncio
async def test_parser_client_terminates_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    request_seen = False

    class Process:
        returncode = None

        async def communicate(self) -> tuple[bytes, bytes]:
            import asyncio

            await asyncio.sleep(1)
            return b"", b""

        def kill(self) -> None:
            nonlocal request_seen
            request_seen = True

        async def wait(self) -> None:
            self.returncode = -9

    async def fake_subprocess(*args: object, **kwargs: object) -> Process:
        return Process()

    monkeypatch.setattr(
        "app.services.parser_client.asyncio.create_subprocess_exec",
        fake_subprocess,
    )

    with pytest.raises(ParserTimeoutError):
        await ParserClient(timeout_seconds=0.01).parse(
            repository,
            ["service.py"],
            ParserLimits(20, 20_000, 100_000, 200),
        )
    assert request_seen is True


@pytest.mark.asyncio
async def test_parser_client_maps_process_start_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    async def failed_subprocess(*args: object, **kwargs: object) -> None:
        raise OSError("cannot start parser")

    monkeypatch.setattr(
        "app.services.parser_client.asyncio.create_subprocess_exec",
        failed_subprocess,
    )

    with pytest.raises(ParserClientError):
        await ParserClient(timeout_seconds=5).parse(
            repository,
            ["service.py"],
            ParserLimits(20, 20_000, 100_000, 200),
        )
