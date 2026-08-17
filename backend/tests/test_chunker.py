import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from app.retrieval.chunker import (
    ChunkLimits,
    IndexedFile,
    IndexedSymbol,
    RetrievalChunkLimitError,
    UnsafeChunkSourceError,
    build_python_chunks,
)


def indexed_file(path: Path, relative: str) -> IndexedFile:
    return IndexedFile(
        id=uuid4(),
        path=relative,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        parse_status="parsed",
    )


def test_symbol_and_uncovered_module_code_become_stable_chunks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "import os\n\nVALUE = 1\n\ndef run(value: str):\n"
        "    return value.upper()\n",
        encoding="utf-8",
    )
    code_file = indexed_file(source, "service.py")
    symbol = IndexedSymbol(
        id=uuid4(),
        file_id=code_file.id,
        kind="function",
        qualified_name="run",
        signature="run(value: str)",
        start_line=5,
        end_line=6,
    )

    chunks = build_python_chunks(
        tmp_path,
        [code_file],
        [symbol],
        {"service.py"},
        ChunkLimits(100, 120, 160, 20, 16_384),
    )

    assert [(chunk.kind, chunk.start_line, chunk.end_line) for chunk in chunks] == [
        ("module", 1, 4),
        ("function", 5, 6),
    ]
    assert chunks[1].symbol_name == "run"
    assert chunks[1].symbol_id == symbol.id
    assert "service.py run run(value: str)" in chunks[1].searchable_text
    assert chunks[1].content_sha256 == hashlib.sha256(
        chunks[1].content.encode("utf-8")
    ).hexdigest()


def test_long_symbol_uses_line_windows_with_overlap(tmp_path: Path) -> None:
    source = tmp_path / "large.py"
    source.write_text(
        "\n".join(f"line_{number} = {number}" for number in range(1, 11))
        + "\n",
        encoding="utf-8",
    )
    code_file = indexed_file(source, "large.py")
    symbol = IndexedSymbol(
        id=uuid4(),
        file_id=code_file.id,
        kind="function",
        qualified_name="large",
        signature=None,
        start_line=1,
        end_line=10,
    )

    chunks = build_python_chunks(
        tmp_path,
        [code_file],
        [symbol],
        {"large.py"},
        ChunkLimits(100, 4, 6, 1, 16_384),
    )

    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [
        (1, 4),
        (4, 7),
        (7, 10),
    ]


def test_parent_window_matching_method_keeps_only_specific_chunk(
    tmp_path: Path,
) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "class Service:\n"
        "    value = 1\n"
        "    other = 2\n"
        "\n"
        "    def run(self):\n"
        "        return self.value\n",
        encoding="utf-8",
    )
    code_file = indexed_file(source, "service.py")
    class_symbol = IndexedSymbol(
        id=uuid4(),
        file_id=code_file.id,
        kind="class",
        qualified_name="Service",
        signature=None,
        start_line=1,
        end_line=6,
    )
    method_symbol = IndexedSymbol(
        id=uuid4(),
        file_id=code_file.id,
        kind="method",
        qualified_name="Service.run",
        signature="(self)",
        start_line=5,
        end_line=6,
    )

    chunks = build_python_chunks(
        tmp_path,
        [code_file],
        [class_symbol, method_symbol],
        {"service.py"},
        ChunkLimits(100, 3, 4, 1, 16_384),
    )

    matching = [
        chunk
        for chunk in chunks
        if (chunk.start_line, chunk.end_line) == (5, 6)
    ]
    assert len(matching) == 1
    assert matching[0].kind == "method"
    assert matching[0].symbol_id == method_symbol.id


@pytest.mark.parametrize("unsafe_path", ["../secret.py", "/tmp/secret.py"])
def test_chunker_rejects_paths_outside_repository(
    tmp_path: Path, unsafe_path: str
) -> None:
    code_file = IndexedFile(
        id=uuid4(),
        path=unsafe_path,
        source_sha256="a" * 64,
        parse_status="parsed",
    )

    with pytest.raises(UnsafeChunkSourceError):
        build_python_chunks(
            tmp_path,
            [code_file],
            [],
            {unsafe_path},
            ChunkLimits(100, 120, 160, 20, 16_384),
        )


def test_chunker_rejects_untracked_or_changed_source(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    code_file = indexed_file(source, "service.py")

    with pytest.raises(UnsafeChunkSourceError):
        build_python_chunks(
            tmp_path,
            [code_file],
            [],
            set(),
            ChunkLimits(100, 120, 160, 20, 16_384),
        )

    source.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(UnsafeChunkSourceError):
        build_python_chunks(
            tmp_path,
            [code_file],
            [],
            {"service.py"},
            ChunkLimits(100, 120, 160, 20, 16_384),
        )


def test_chunker_enforces_chunk_and_single_line_limits(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("A = 1\nB = 2\n", encoding="utf-8")
    code_file = indexed_file(source, "service.py")

    with pytest.raises(RetrievalChunkLimitError):
        build_python_chunks(
            tmp_path,
            [code_file],
            [],
            {"service.py"},
            ChunkLimits(0, 120, 160, 20, 16_384),
        )

    with pytest.raises(RetrievalChunkLimitError):
        build_python_chunks(
            tmp_path,
            [code_file],
            [],
            {"service.py"},
            ChunkLimits(10, 120, 160, 20, 3),
        )
