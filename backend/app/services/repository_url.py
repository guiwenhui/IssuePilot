import re
from urllib.parse import urlsplit


GITHUB_HOST = "github.com"
OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class RepositoryUrlError(ValueError):
    pass


def normalize_repository_url(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)

    if parsed.scheme != "https" or parsed.hostname is None:
        raise RepositoryUrlError("repository_url must use HTTPS")
    if parsed.hostname.lower() != GITHUB_HOST:
        raise RepositoryUrlError("repository_url host is not supported")
    if parsed.username is not None or parsed.password is not None:
        raise RepositoryUrlError("repository_url must not include credentials")
    if _has_explicit_port(parsed.netloc) or parsed.query or parsed.fragment:
        raise RepositoryUrlError("repository_url contains unsupported URL parts")
    if "%" in parsed.path:
        raise RepositoryUrlError("repository_url must not contain encoded path parts")

    owner, repository = _parse_repository_path(parsed.path)
    return f"https://{GITHUB_HOST}/{owner}/{repository}.git"


def _has_explicit_port(netloc: str) -> bool:
    return ":" in netloc.rsplit("@", maxsplit=1)[-1]


def _parse_repository_path(path: str) -> tuple[str, str]:
    parts = path.strip("/").split("/")
    if len(parts) != 2:
        raise RepositoryUrlError("repository_url must identify owner and repository")

    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not OWNER_PATTERN.fullmatch(owner):
        raise RepositoryUrlError("repository owner is invalid")
    if not repository or repository in {".", ".."}:
        raise RepositoryUrlError("repository name is invalid")
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise RepositoryUrlError("repository name is invalid")
    return owner, repository
