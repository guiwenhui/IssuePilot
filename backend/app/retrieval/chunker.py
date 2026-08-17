import hashlib
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from uuid import UUID


CHUNKER_VERSION = "python-symbol-v1"


class UnsafeChunkSourceError(Exception):
    pass


class RetrievalChunkLimitError(Exception):
    pass


@dataclass(frozen=True)
class ChunkLimits:
    max_chunks: int
    max_chunk_lines: int
    max_symbol_chunk_lines: int
    overlap_lines: int
    max_characters: int


@dataclass(frozen=True)
class IndexedFile:
    id: UUID
    path: str
    source_sha256: str
    parse_status: str


@dataclass(frozen=True)
class IndexedSymbol:
    id: UUID
    file_id: UUID
    kind: str
    qualified_name: str
    signature: Optional[str]
    start_line: int
    end_line: int


@dataclass(frozen=True)
class CodeChunkDraft:
    file_id: UUID
    symbol_id: Optional[UUID]
    path: str
    kind: str
    symbol_name: Optional[str]
    start_line: int
    end_line: int
    content: str
    content_sha256: str
    searchable_text: str


def build_python_chunks(
    repository: Path,
    files: Sequence[IndexedFile],
    symbols: Sequence[IndexedSymbol],
    tracked_paths: Set[str],
    limits: ChunkLimits,
) -> List[CodeChunkDraft]:
    _validate_limits(limits)
    by_file = _symbols_by_file(symbols)
    chunks: List[CodeChunkDraft] = []
    for code_file in sorted(files, key=lambda item: item.path):
        if code_file.parse_status != "parsed":
            continue
        lines = _read_source(repository, code_file, tracked_paths)
        file_chunks = _chunks_for_file(code_file, lines, by_file, limits)
        chunks.extend(file_chunks)
        if len(chunks) > limits.max_chunks:
            raise RetrievalChunkLimitError("code chunk count exceeded")
    return chunks


def _validate_limits(limits: ChunkLimits) -> None:
    if (
        limits.max_chunks < 0
        or limits.max_chunk_lines < 1
        or limits.max_symbol_chunk_lines < 1
        or limits.overlap_lines < 0
        or limits.overlap_lines >= limits.max_chunk_lines
        or limits.max_characters < 1
    ):
        raise RetrievalChunkLimitError("invalid chunk limits")


def _symbols_by_file(
    symbols: Sequence[IndexedSymbol],
) -> Dict[UUID, List[IndexedSymbol]]:
    result: Dict[UUID, List[IndexedSymbol]] = {}
    for symbol in symbols:
        result.setdefault(symbol.file_id, []).append(symbol)
    for values in result.values():
        values.sort(key=lambda item: (item.start_line, item.end_line, item.qualified_name))
    return result


def _safe_source_path(
    repository: Path, relative: str, tracked_paths: Set[str]
) -> Path:
    posix_path = PurePosixPath(relative)
    if (
        relative not in tracked_paths
        or posix_path.is_absolute()
        or ".." in posix_path.parts
        or posix_path.suffix != ".py"
    ):
        raise UnsafeChunkSourceError("unsafe or untracked Python source")
    repository_root = repository.resolve()
    candidate = repository.joinpath(*posix_path.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise UnsafeChunkSourceError("source is not a regular file")
    try:
        candidate.resolve().relative_to(repository_root)
    except ValueError as error:
        raise UnsafeChunkSourceError("source escapes repository") from error
    return candidate


def _read_source(
    repository: Path, code_file: IndexedFile, tracked_paths: Set[str]
) -> List[str]:
    source_path = _safe_source_path(repository, code_file.path, tracked_paths)
    raw = source_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != code_file.source_sha256:
        raise UnsafeChunkSourceError("source hash changed after indexing")
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        source = raw.decode(encoding)
    except (LookupError, SyntaxError, UnicodeDecodeError) as error:
        raise UnsafeChunkSourceError("source encoding is invalid") from error
    return source.splitlines()


def _chunks_for_file(
    code_file: IndexedFile,
    lines: Sequence[str],
    symbols_by_file: Dict[UUID, List[IndexedSymbol]],
    limits: ChunkLimits,
) -> List[CodeChunkDraft]:
    if not lines:
        return []
    symbols = symbols_by_file.get(code_file.id, [])
    chunks: List[CodeChunkDraft] = []
    for start, end in _uncovered_ranges(len(lines), symbols):
        chunks.extend(_module_chunks(code_file, lines, start, end, limits))
    for symbol in symbols:
        chunks.extend(_symbol_chunks(code_file, symbol, lines, limits))
    return sorted(
        chunks,
        key=lambda item: (
            item.path,
            item.start_line,
            item.end_line,
            item.symbol_name or "",
        ),
    )


def _uncovered_ranges(
    line_count: int, symbols: Sequence[IndexedSymbol]
) -> Iterable[Tuple[int, int]]:
    covered = [False] * line_count
    for symbol in symbols:
        start = max(1, symbol.start_line)
        end = min(line_count, symbol.end_line)
        for index in range(start - 1, end):
            covered[index] = True
    start: Optional[int] = None
    for line_number, is_covered in enumerate(covered, start=1):
        if not is_covered and start is None:
            start = line_number
        elif is_covered and start is not None:
            yield start, line_number - 1
            start = None
    if start is not None:
        yield start, line_count


def _module_chunks(
    code_file: IndexedFile,
    lines: Sequence[str],
    start: int,
    end: int,
    limits: ChunkLimits,
) -> List[CodeChunkDraft]:
    return [
        _draft(code_file, None, "module", None, lines, window_start, window_end)
        for window_start, window_end in _window_ranges(
            lines, start, end, limits.max_chunk_lines, limits
        )
        if _content(lines, window_start, window_end).strip()
    ]


def _symbol_chunks(
    code_file: IndexedFile,
    symbol: IndexedSymbol,
    lines: Sequence[str],
    limits: ChunkLimits,
) -> List[CodeChunkDraft]:
    start = max(1, symbol.start_line)
    end = min(len(lines), symbol.end_line)
    if start > end:
        return []
    length = end - start + 1
    window_lines = length if length <= limits.max_symbol_chunk_lines else limits.max_chunk_lines
    return [
        _draft(
            code_file,
            symbol,
            symbol.kind,
            symbol.qualified_name,
            lines,
            window_start,
            window_end,
        )
        for window_start, window_end in _window_ranges(
            lines, start, end, window_lines, limits
        )
        if _content(lines, window_start, window_end).strip()
    ]


def _window_ranges(
    lines: Sequence[str],
    start: int,
    end: int,
    max_lines: int,
    limits: ChunkLimits,
) -> Iterable[Tuple[int, int]]:
    current = start
    while current <= end:
        candidate_end = min(end, current + max_lines - 1)
        fitted_end = _fit_character_limit(
            lines, current, candidate_end, limits.max_characters
        )
        yield current, fitted_end
        if fitted_end >= end:
            return
        current = max(current + 1, fitted_end - limits.overlap_lines + 1)


def _fit_character_limit(
    lines: Sequence[str], start: int, end: int, max_characters: int
) -> int:
    fitted = end
    while fitted > start and len(_content(lines, start, fitted)) > max_characters:
        fitted -= 1
    if len(_content(lines, start, fitted)) > max_characters:
        raise RetrievalChunkLimitError("single source line exceeds chunk limit")
    return fitted


def _content(lines: Sequence[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1 : end])


def _draft(
    code_file: IndexedFile,
    symbol: Optional[IndexedSymbol],
    kind: str,
    symbol_name: Optional[str],
    lines: Sequence[str],
    start: int,
    end: int,
) -> CodeChunkDraft:
    content = _content(lines, start, end)
    signature = symbol.signature if symbol is not None else None
    searchable = " ".join(
        item for item in (code_file.path, symbol_name, signature, content) if item
    )
    return CodeChunkDraft(
        file_id=code_file.id,
        symbol_id=symbol.id if symbol is not None else None,
        path=code_file.path,
        kind=kind,
        symbol_name=symbol_name,
        start_line=start,
        end_line=end,
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        searchable_text=searchable,
    )
