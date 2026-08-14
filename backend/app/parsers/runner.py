import json
import sys
from pathlib import Path
from typing import Dict, Type

# Isolated mode intentionally ignores PYTHONPATH. Add only IssuePilot's fixed
# backend root so this trusted runner can import the application package.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic import ValidationError

from app.parsers.python_ast import (
    NoPythonFilesError,
    ParserLimits,
    PythonAstParser,
    PythonSourceLimitError,
    UnsafePythonPathError,
)
from app.schemas.code_index import ParserRequest


ERROR_CODES: Dict[Type[Exception], str] = {
    NoPythonFilesError: "NO_PYTHON_FILES",
    PythonSourceLimitError: "PYTHON_SOURCE_LIMIT_EXCEEDED",
    UnsafePythonPathError: "UNSAFE_PYTHON_PATH",
    ValidationError: "INVALID_PARSER_REQUEST",
}


def run(request_path: Path) -> int:
    try:
        request = ParserRequest.model_validate_json(
            request_path.read_text(encoding="utf-8")
        )
        result = PythonAstParser(_limits(request)).parse(
            Path(request.repository), request.paths
        )
    except tuple(ERROR_CODES) as error:
        _write_error(ERROR_CODES[type(error)], str(error))
        return 2
    except Exception as error:
        _write_error("CODE_INDEX_FAILED", str(error))
        return 3
    sys.stdout.write(result.model_dump_json())
    return 0


def _limits(request: ParserRequest) -> ParserLimits:
    return ParserLimits(
        request.max_python_files,
        request.max_python_file_bytes,
        request.max_python_total_bytes,
        request.max_code_entities,
    )


def _write_error(code: str, message: str) -> None:
    sys.stderr.write(json.dumps({"code": code, "message": message[:300]}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        _write_error("INVALID_PARSER_REQUEST", "request path is required")
        raise SystemExit(2)
    raise SystemExit(run(Path(sys.argv[1])))
