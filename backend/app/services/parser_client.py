import asyncio
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Sequence

from pydantic import ValidationError

from app.parsers.python_ast import (
    NoPythonFilesError,
    ParserLimits,
    PythonSourceLimitError,
    UnsafePythonPathError,
)
from app.schemas.code_index import ParserRequest, ParserResult


class ParserClientError(Exception):
    pass


class ParserTimeoutError(ParserClientError):
    pass


class ParserProtocolError(ParserClientError):
    pass


class ParserClient:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds
        self._backend_root = Path(__file__).resolve().parents[2]

    async def parse(
        self,
        repository: Path,
        paths: Sequence[str],
        limits: ParserLimits,
    ) -> ParserResult:
        try:
            request_path = self._write_request(repository, paths, limits)
        except OSError as error:
            raise ParserClientError("cannot create parser request") from error
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(self._backend_root / "app" / "parsers" / "runner.py"),
                str(request_path),
                cwd=str(self._backend_root),
                env=_parser_environment(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._timeout_seconds
            )
        except asyncio.TimeoutError as error:
            if process is not None:
                process.kill()
                await process.wait()
            raise ParserTimeoutError() from error
        except OSError as error:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            raise ParserClientError("cannot run parser process") from error
        finally:
            request_path.unlink(missing_ok=True)
        if process.returncode != 0:
            _raise_parser_error(stderr)
        try:
            return ParserResult.model_validate_json(stdout)
        except ValidationError as error:
            raise ParserProtocolError("invalid parser response") from error

    @staticmethod
    def _write_request(
        repository: Path,
        paths: Sequence[str],
        limits: ParserLimits,
    ) -> Path:
        request = ParserRequest(
            repository=str(repository.resolve()), paths=list(paths), **asdict(limits)
        )
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="issuepilot-parser-",
            suffix=".json",
            delete=False,
        ) as request_file:
            request_file.write(request.model_dump_json())
            return Path(request_file.name)


def _parser_environment() -> Dict[str, str]:
    return {
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
    }


def _raise_parser_error(stderr: bytes) -> None:
    try:
        payload: Dict[str, Any] = json.loads(stderr.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParserProtocolError("parser failed without a valid error") from error
    code = payload.get("code")
    mapping = {
        "NO_PYTHON_FILES": NoPythonFilesError,
        "PYTHON_SOURCE_LIMIT_EXCEEDED": PythonSourceLimitError,
        "UNSAFE_PYTHON_PATH": UnsafePythonPathError,
    }
    error_type = mapping.get(code, ParserClientError)
    raise error_type(str(payload.get("message", "parser failed"))[:300])
