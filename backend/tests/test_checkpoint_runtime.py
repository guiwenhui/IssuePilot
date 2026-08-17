from app.checkpoints.postgres import psycopg_url
from app.core.config import Settings


def test_checkpoint_url_reuses_business_database_by_default() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/app"
    )

    assert settings.checkpoint_database_url is None
    assert psycopg_url(settings.database_url) == (
        "postgresql://user:pass@localhost:5432/app"
    )


def test_checkpoint_schema_and_limits_are_bounded() -> None:
    settings = Settings()

    assert settings.checkpoint_schema == "issuepilot_checkpoint"
    assert settings.planning_revision_limit == 5
    assert settings.planning_decision_queue_capacity == 20
