import pytest

from app.services.repository_url import (
    RepositoryUrlError,
    normalize_repository_url,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "https://github.com/pallets/markupsafe",
            "https://github.com/pallets/markupsafe.git",
        ),
        (
            "https://GITHUB.com/pallets/markupsafe.git",
            "https://github.com/pallets/markupsafe.git",
        ),
    ],
)
def test_normalize_repository_url_returns_canonical_github_url(
    value: str,
    expected: str,
) -> None:
    assert normalize_repository_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/pallets/markupsafe.git",
        "https://gitlab.com/pallets/markupsafe.git",
        "https://user:secret@github.com/pallets/markupsafe.git",
        "https://github.com:443/pallets/markupsafe.git",
        "https://github.com/pallets/markupsafe.git?ref=main",
        "https://github.com/pallets/markupsafe.git#readme",
        "https://github.com/pallets/markupsafe/extra.git",
        "https://github.com/pallets/%2Fprivate.git",
        "https://github.com/../private.git",
        "https://github.com/pallets/.git",
    ],
)
def test_normalize_repository_url_rejects_unsafe_or_unsupported_urls(
    value: str,
) -> None:
    with pytest.raises(RepositoryUrlError):
        normalize_repository_url(value)
