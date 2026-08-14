import ast
import hashlib
import stat
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional, Sequence, Tuple, Union

from app.schemas.code_index import (
    ParsedFile,
    ParsedImport,
    ParsedSymbol,
    ParserResult,
)


PARSER_VERSION = "py-ast-v1"
MAX_ERROR_LENGTH = 300


class PythonParserError(Exception):
    pass


class NoPythonFilesError(PythonParserError):
    pass


class PythonSourceLimitError(PythonParserError):
    pass


class UnsafePythonPathError(PythonParserError):
    pass


@dataclass(frozen=True)
class ParserLimits:
    max_python_files: int
    max_python_file_bytes: int
    max_python_total_bytes: int
    max_code_entities: int


class StructureVisitor(ast.NodeVisitor):
    def __init__(self, source: str) -> None:
        self._source = source
        self._stack: List[Tuple[int, str, str]] = []
        self.symbols: List[ParsedSymbol] = []
        self.imports: List[ParsedImport] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_symbol(node, "class", False)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        kind = "method" if self._parent_is_class() else "function"
        self._visit_symbol(node, kind, False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        kind = "method" if self._parent_is_class() else "function"
        self._visit_symbol(node, kind, True)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ParsedImport(
                    kind="import",
                    module=alias.name,
                    alias=alias.asname,
                    scope=self._scope(),
                    line=node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.imports.append(
                ParsedImport(
                    kind="from",
                    module=node.module,
                    imported_name=alias.name,
                    alias=alias.asname,
                    relative_level=node.level,
                    scope=self._scope(),
                    line=node.lineno,
                )
            )

    def _visit_symbol(
        self,
        node: Union[ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef],
        kind: str,
        is_async: bool,
    ) -> None:
        local_id = len(self.symbols) + 1
        qualified_name = ".".join(
            [item[1] for item in self._stack] + [node.name]
        )
        decorators = [_safe_unparse(item) for item in node.decorator_list]
        self.symbols.append(
            ParsedSymbol(
                local_id=local_id,
                parent_local_id=self._stack[-1][0] if self._stack else None,
                kind=kind,
                name=node.name,
                qualified_name=qualified_name,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                signature=_signature(node),
                decorators=decorators,
                is_async=is_async,
                is_test=_is_test_symbol(kind, node.name),
                is_fixture=_is_fixture(decorators),
            )
        )
        self._stack.append((local_id, node.name, kind))
        self.generic_visit(node)
        self._stack.pop()

    def _parent_is_class(self) -> bool:
        return bool(self._stack and self._stack[-1][2] == "class")

    def _scope(self) -> Optional[str]:
        if not self._stack:
            return None
        return ".".join(item[1] for item in self._stack)


class PythonAstParser:
    def __init__(self, limits: ParserLimits) -> None:
        self._limits = limits

    def parse(self, repository: Path, paths: Sequence[str]) -> ParserResult:
        root = repository.resolve()
        candidates = self._safe_candidates(root, paths)
        parsed_files: List[ParsedFile] = []
        total_bytes = 0
        entity_count = 0
        for relative_path, source_path in candidates:
            size_bytes = source_path.stat().st_size
            total_bytes += size_bytes
            self._check_byte_limits(size_bytes, total_bytes)
            parsed = _parse_file(relative_path, source_path, size_bytes)
            parsed_files.append(parsed)
            entity_count += len(parsed.symbols) + len(parsed.imports)
            if entity_count > self._limits.max_code_entities:
                raise PythonSourceLimitError("code entity limit exceeded")
        successful = sum(item.parse_status == "parsed" for item in parsed_files)
        if successful == 0:
            raise NoPythonFilesError("no parseable Python files")
        return _result(parsed_files, successful)

    def _safe_candidates(
        self, root: Path, paths: Sequence[str]
    ) -> List[Tuple[str, Path]]:
        python_paths = sorted(set(path for path in paths if path.endswith(".py")))
        if len(python_paths) > self._limits.max_python_files:
            raise PythonSourceLimitError("Python file limit exceeded")
        candidates = []
        for relative_path in python_paths:
            source_path = _safe_regular_file(root, relative_path)
            if source_path is not None:
                candidates.append((relative_path, source_path))
        if not candidates:
            raise NoPythonFilesError("no tracked regular Python files")
        return candidates

    def _check_byte_limits(self, file_bytes: int, total_bytes: int) -> None:
        if file_bytes > self._limits.max_python_file_bytes:
            raise PythonSourceLimitError("Python file is too large")
        if total_bytes > self._limits.max_python_total_bytes:
            raise PythonSourceLimitError("Python source total is too large")


def _safe_regular_file(root: Path, relative_path: str) -> Optional[Path]:
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        raise UnsafePythonPathError("unsafe Python source path")
    candidate = root.joinpath(*pure_path.parts)
    try:
        file_stat = candidate.lstat()
        if stat.S_ISLNK(file_stat.st_mode):
            return None
        candidate.resolve().relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise UnsafePythonPathError("Python source escaped repository") from error
    if not stat.S_ISREG(file_stat.st_mode):
        return None
    return candidate


def _parse_file(relative_path: str, path: Path, size_bytes: int) -> ParsedFile:
    raw_source = path.read_bytes()
    digest = hashlib.sha256(raw_source).hexdigest()
    try:
        with tokenize.open(str(path)) as source_file:
            source = source_file.read()
    except (LookupError, OSError, SyntaxError, UnicodeError) as error:
        return _error_file(relative_path, digest, size_bytes, "read_error", error)
    try:
        tree = ast.parse(source, filename=relative_path, type_comments=True)
    except (SyntaxError, ValueError, MemoryError, RecursionError) as error:
        return _error_file(relative_path, digest, size_bytes, "syntax_error", error)
    visitor = StructureVisitor(source)
    visitor.visit(tree)
    return ParsedFile(
        path=relative_path,
        module_name=_module_name(relative_path),
        source_sha256=digest,
        line_count=len(source.splitlines()),
        size_bytes=size_bytes,
        is_test_file=_is_test_file(relative_path),
        parse_status="parsed",
        symbols=visitor.symbols,
        imports=visitor.imports,
    )


def _error_file(
    relative_path: str,
    digest: str,
    size_bytes: int,
    status: str,
    error: Exception,
) -> ParsedFile:
    return ParsedFile(
        path=relative_path,
        module_name=_module_name(relative_path),
        source_sha256=digest,
        line_count=0,
        size_bytes=size_bytes,
        is_test_file=_is_test_file(relative_path),
        parse_status=status,
        parse_error=str(error)[:MAX_ERROR_LENGTH],
    )


def _result(files: List[ParsedFile], parsed_file_count: int) -> ParserResult:
    symbols = [symbol for file in files for symbol in file.symbols]
    imports = [item for file in files for item in file.imports]
    return ParserResult(
        parser_version=PARSER_VERSION,
        python_version=".".join(str(part) for part in sys.version_info[:3]),
        files=files,
        parsed_file_count=parsed_file_count,
        symbol_count=len(symbols),
        import_count=len(imports),
        test_count=sum(symbol.is_test or symbol.is_fixture for symbol in symbols),
        parse_error_count=sum(file.parse_status != "parsed" for file in files),
    )


def _signature(
    node: Union[ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef]
) -> Optional[str]:
    if isinstance(node, ast.ClassDef):
        return None
    signature = f"({_safe_unparse(node.args)})"
    if node.returns is not None:
        signature += f" -> {_safe_unparse(node.returns)}"
    return signature


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (ValueError, RecursionError):
        return "<unavailable>"


def _module_name(relative_path: str) -> Optional[str]:
    parts = list(PurePosixPath(relative_path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _is_test_file(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    return (
        "tests" in path.parts
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
    )


def _is_test_symbol(kind: str, name: str) -> bool:
    return name.startswith("Test") if kind == "class" else name.startswith("test_")


def _is_fixture(decorators: Sequence[str]) -> bool:
    return any(
        name in {"fixture", "pytest.fixture", "pytest_asyncio.fixture"}
        or name.endswith(".fixture")
        for name in decorators
    )
