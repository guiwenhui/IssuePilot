from pathlib import Path

import pytest

from app.parsers.python_ast import (
    NoPythonFilesError,
    ParserLimits,
    PythonAstParser,
    PythonSourceLimitError,
)


def limits(**overrides: int) -> ParserLimits:
    values = {
        "max_python_files": 20,
        "max_python_file_bytes": 20_000,
        "max_python_total_bytes": 100_000,
        "max_code_entities": 200,
    }
    values.update(overrides)
    return ParserLimits(**values)


def test_extracts_symbols_imports_and_test_structure(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source = repository / "tests" / "test_service.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """import os as operating_system
from ..core import Service as CoreService

class TestService:
    @pytest.fixture
    def client(self):
        return object()

    async def test_run(self, client: object) -> bool:
        def nested(value: int = 1) -> int:
            return value
        return True
""",
        encoding="utf-8",
    )

    result = PythonAstParser(limits()).parse(repository, ["tests/test_service.py"])

    parsed = result.files[0]
    assert parsed.module_name == "tests.test_service"
    assert parsed.is_test_file is True
    assert [symbol.qualified_name for symbol in parsed.symbols] == [
        "TestService",
        "TestService.client",
        "TestService.test_run",
        "TestService.test_run.nested",
    ]
    assert parsed.symbols[1].kind == "method"
    assert parsed.symbols[1].is_fixture is True
    assert parsed.symbols[2].is_async is True
    assert parsed.symbols[2].is_test is True
    assert parsed.symbols[3].parent_local_id == parsed.symbols[2].local_id
    assert parsed.symbols[3].signature == "(value: int=1) -> int"
    assert [item.model_dump() for item in parsed.imports] == [
        {
            "kind": "import",
            "module": "os",
            "imported_name": None,
            "alias": "operating_system",
            "relative_level": 0,
            "scope": None,
            "line": 1,
        },
        {
            "kind": "from",
            "module": "core",
            "imported_name": "Service",
            "alias": "CoreService",
            "relative_level": 2,
            "scope": None,
            "line": 2,
        },
    ]


def test_preserves_encoding_and_records_partial_syntax_error(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "latin.py").write_bytes(
        b"# -*- coding: latin-1 -*-\nNAME = '\xe9'\ndef valid():\n    return NAME\n"
    )
    (repository / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    result = PythonAstParser(limits()).parse(
        repository, ["latin.py", "broken.py"]
    )

    statuses = {item.path: item.parse_status for item in result.files}
    assert statuses == {"broken.py": "syntax_error", "latin.py": "parsed"}
    broken = next(item for item in result.files if item.path == "broken.py")
    assert broken.parse_error
    assert len(broken.parse_error) <= 300
    assert result.parsed_file_count == 1
    assert result.parse_error_count == 1


def test_skips_symlink_and_rejects_repository_without_python(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    target = tmp_path / "outside.py"
    target.write_text("def secret(): pass\n", encoding="utf-8")
    (repository / "linked.py").symlink_to(target)

    with pytest.raises(NoPythonFilesError):
        PythonAstParser(limits()).parse(repository, ["linked.py", "README.md"])


def test_enforces_per_file_and_entity_limits(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "large.py").write_text("x = '1234567890'\n", encoding="utf-8")

    with pytest.raises(PythonSourceLimitError):
        PythonAstParser(limits(max_python_file_bytes=5)).parse(
            repository, ["large.py"]
        )

    (repository / "many.py").write_text(
        "\n".join(f"def f{index}(): pass" for index in range(5)),
        encoding="utf-8",
    )
    with pytest.raises(PythonSourceLimitError):
        PythonAstParser(limits(max_code_entities=4)).parse(repository, ["many.py"])
