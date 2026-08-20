import os
from pathlib import Path
import time
from uuid import uuid4

import pytest

from app.services.test_runner import (
    DockerTestRunner,
    _docker_arguments,
    run_command,
)


FIXTURES = Path(__file__).parent / "fixtures"


def require_live_docker() -> None:
    if os.environ.get("RUN_DOCKER_LIVE") != "1":
        pytest.skip("set RUN_DOCKER_LIVE=1 for the approved Docker runner")


@pytest.mark.docker
@pytest.mark.asyncio
async def test_live_runner_enforces_boundaries_and_reports_failure() -> None:
    require_live_docker()
    runner = DockerTestRunner("issuepilot-pytest-runner:m7", 20, 20_000)

    passed = await runner.run(FIXTURES / "runner_pass", uuid4())
    failed = await runner.run(FIXTURES / "runner_fail", uuid4())

    assert passed.exit_code == 0
    assert "1 passed" in passed.stdout
    assert failed.exit_code == 1
    assert "1 failed" in failed.stdout
    assert passed.runner_image.startswith("sha256:")


@pytest.mark.docker
@pytest.mark.asyncio
async def test_live_runner_stops_timed_out_container() -> None:
    require_live_docker()
    runner = DockerTestRunner("issuepilot-pytest-runner:m7", 1, 20_000)

    result = await runner.run(FIXTURES / "runner_timeout", uuid4())

    assert result.timed_out is True
    assert result.exit_code is None


@pytest.mark.docker
@pytest.mark.asyncio
async def test_live_runner_image_enforces_its_own_hard_timeout() -> None:
    require_live_docker()
    runner = DockerTestRunner("issuepilot-pytest-runner:m7", 20, 20_000)
    image_id = await runner._resolve_image()
    run_id = uuid4()
    started = time.monotonic()

    result = await run_command(
        _docker_arguments(
            image_id,
            (FIXTURES / "runner_timeout").resolve(),
            f"issuepilot-test-{run_id}",
            1,
        ),
        10,
        20_000,
    )

    assert result.return_code == 124
    assert time.monotonic() - started < 5
    await runner.cleanup(run_id)
