import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence, Set

from app.schemas.implementation import FileReplacementDraft
from app.services.git_client import GitClient


class PatchValidationError(Exception):
    pass


class PatchSourceChangedError(PatchValidationError):
    pass


@dataclass(frozen=True)
class PatchLimits:
    max_files: int = 4
    max_file_bytes: int = 81_920
    max_total_bytes: int = 163_840
    max_diff_bytes: int = 102_400
    max_changed_lines: int = 2_000


@dataclass(frozen=True)
class PatchArtifactDraft:
    unified_diff: str
    diff_sha256: str
    file_manifest: list[dict[str, str]]
    file_count: int
    insertions: int
    deletions: int


class PatchService:
    def __init__(self, git_client: GitClient, limits: PatchLimits) -> None:
        self._git = git_client
        self._limits = limits

    async def apply(
        self,
        worktree: Path,
        allowed_paths: Set[str],
        replacements: Sequence[FileReplacementDraft],
    ) -> PatchArtifactDraft:
        originals = self._validate_replacements(
            worktree, allowed_paths, replacements
        )
        try:
            for replacement in replacements:
                _atomic_write(worktree / replacement.path, replacement.content)
            return await self.inspect(worktree, allowed_paths, originals)
        except Exception:
            for path, content in originals.items():
                _atomic_write(worktree / path, content.decode("utf-8"))
            raise

    async def inspect(
        self,
        worktree: Path,
        allowed_paths: Set[str],
        originals: dict[str, bytes] | None = None,
    ) -> PatchArtifactDraft:
        if await self._git.untracked_paths(worktree):
            raise PatchSourceChangedError("implementation worktree has untracked files")
        changed = await self._git.changed_paths(worktree)
        if not changed or not set(changed).issubset(allowed_paths):
            raise PatchValidationError("patch changed paths are not allowed")
        stats = await self._git.diff_numstat(worktree)
        if {path for _, _, path in stats} != set(changed):
            raise PatchValidationError("patch statistics do not match paths")
        insertions = sum(row[0] for row in stats)
        deletions = sum(row[1] for row in stats)
        if insertions + deletions > self._limits.max_changed_lines:
            raise PatchValidationError("patch changed line limit exceeded")
        unified_diff = await self._git.diff(worktree)
        encoded_diff = unified_diff.encode("utf-8")
        if not unified_diff or len(encoded_diff) > self._limits.max_diff_bytes:
            raise PatchValidationError("patch diff size is invalid")
        manifest = []
        for path in sorted(changed):
            current = _read_regular_file(worktree, path)
            original = (originals or {}).get(path)
            manifest.append(
                {
                    "path": path,
                    "original_sha256": _sha256(original) if original else "",
                    "patched_sha256": _sha256(current),
                }
            )
        return PatchArtifactDraft(
            unified_diff=unified_diff,
            diff_sha256=_sha256(encoded_diff),
            file_manifest=manifest,
            file_count=len(changed),
            insertions=insertions,
            deletions=deletions,
        )

    def _validate_replacements(
        self,
        worktree: Path,
        allowed_paths: Set[str],
        replacements: Sequence[FileReplacementDraft],
    ) -> dict[str, bytes]:
        if not replacements or len(replacements) > self._limits.max_files:
            raise PatchValidationError("patch file count is invalid")
        originals: dict[str, bytes] = {}
        total = 0
        for replacement in replacements:
            if replacement.path not in allowed_paths:
                raise PatchValidationError("replacement path is not approved")
            content = replacement.content.encode("utf-8")
            if len(content) > self._limits.max_file_bytes:
                raise PatchValidationError("replacement file is too large")
            original = _read_regular_file(worktree, replacement.path)
            if _sha256(original) != replacement.original_sha256:
                raise PatchSourceChangedError("replacement source hash changed")
            originals[replacement.path] = original
            total += len(content)
        if total > self._limits.max_total_bytes:
            raise PatchValidationError("replacement total size exceeded")
        return originals


def _read_regular_file(worktree: Path, relative_path: str) -> bytes:
    pure_path = PurePosixPath(relative_path)
    if (
        pure_path.is_absolute()
        or not pure_path.parts
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or pure_path.parts[0] == ".git"
    ):
        raise PatchValidationError("unsafe patch path")
    root = worktree.resolve()
    path = worktree.joinpath(*pure_path.parts)
    try:
        resolved_parent = path.parent.resolve(strict=True)
        resolved_parent.relative_to(root)
        metadata = path.lstat()
    except (FileNotFoundError, ValueError) as error:
        raise PatchValidationError("patch path is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise PatchValidationError("patch path is not a regular file")
    try:
        return path.read_bytes()
    except OSError as error:
        raise PatchValidationError("patch file cannot be read") from error


def _atomic_write(path: Path, content: str) -> None:
    mode = stat.S_IMODE(path.lstat().st_mode)
    descriptor, temporary = tempfile.mkstemp(prefix=".issuepilot-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content.encode("utf-8"))
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
