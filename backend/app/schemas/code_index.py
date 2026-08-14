from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ParsedSymbol(BaseModel):
    local_id: int
    parent_local_id: Optional[int] = None
    kind: Literal["class", "function", "method"]
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    signature: Optional[str] = None
    decorators: List[str] = Field(default_factory=list)
    is_async: bool = False
    is_test: bool = False
    is_fixture: bool = False

    model_config = ConfigDict(frozen=True)


class ParsedImport(BaseModel):
    kind: Literal["import", "from"]
    module: Optional[str] = None
    imported_name: Optional[str] = None
    alias: Optional[str] = None
    relative_level: int = 0
    scope: Optional[str] = None
    line: int

    model_config = ConfigDict(frozen=True)


class ParsedFile(BaseModel):
    path: str
    module_name: Optional[str] = None
    source_sha256: str
    line_count: int
    size_bytes: int
    is_test_file: bool
    parse_status: Literal["parsed", "syntax_error", "read_error"]
    parse_error: Optional[str] = None
    symbols: List[ParsedSymbol] = Field(default_factory=list)
    imports: List[ParsedImport] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)


class ParserResult(BaseModel):
    parser_version: str
    python_version: str
    files: List[ParsedFile]
    parsed_file_count: int
    symbol_count: int
    import_count: int
    test_count: int
    parse_error_count: int

    model_config = ConfigDict(frozen=True)


class ParserRequest(BaseModel):
    repository: str
    paths: List[str]
    max_python_files: int
    max_python_file_bytes: int
    max_python_total_bytes: int
    max_code_entities: int

    model_config = ConfigDict(extra="forbid")


class CodeStructureCounts(BaseModel):
    files: int
    parsed_files: int
    symbols: int
    imports: int
    tests: int
    parse_errors: int


class CodeStructureFile(BaseModel):
    path: str
    module_name: Optional[str] = None
    is_test_file: bool
    parse_status: str
    parse_error: Optional[str] = None
    symbols: List[ParsedSymbol]
    imports: List[ParsedImport]


class CodeStructureResponse(BaseModel):
    task_id: UUID
    commit_sha: str
    parser_version: str
    python_version: str
    indexed_at: datetime
    counts: CodeStructureCounts
    truncated: bool
    files: List[CodeStructureFile]
