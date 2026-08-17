import asyncio

from app.checkpoints.postgres import PostgresCheckpointFactory
from app.core.config import get_settings


async def _setup() -> None:
    settings = get_settings()
    database_url = settings.checkpoint_database_url or settings.database_url
    factory = PostgresCheckpointFactory(database_url, settings.checkpoint_schema)
    await factory.setup()
    await factory.verify()


if __name__ == "__main__":
    asyncio.run(_setup())
