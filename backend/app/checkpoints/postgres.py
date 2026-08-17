from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, Error as PsycopgError, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout


class CheckpointSchemaMissingError(Exception):
    pass


class CheckpointerUnavailableError(Exception):
    pass


def psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class PostgresCheckpointFactory:
    def __init__(self, database_url: str, schema: str) -> None:
        self._database_url = psycopg_url(database_url)
        self._schema = schema

    @asynccontextmanager
    async def saver(self) -> AsyncIterator[AsyncPostgresSaver]:
        pool = self._pool()
        try:
            await pool.open()
        except Exception as error:
            raise CheckpointerUnavailableError() from error
        try:
            yield AsyncPostgresSaver(pool)
        except (PsycopgError, PoolTimeout) as error:
            raise CheckpointerUnavailableError() from error
        finally:
            await pool.close()

    async def verify(self) -> None:
        try:
            async with await self._connection() as connection:
                result = await connection.execute(
                    "SELECT to_regclass(%s)",
                    (f"{self._schema}.checkpoints",),
                )
                row = await result.fetchone()
                if row is None or row["to_regclass"] is None:
                    raise CheckpointSchemaMissingError()
        except CheckpointSchemaMissingError:
            raise
        except Exception as error:
            raise CheckpointerUnavailableError() from error

    async def setup(self) -> None:
        try:
            async with await self._connection() as connection:
                statement = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(self._schema)
                )
                await connection.execute(statement)
            async with self.saver() as saver:
                await saver.setup()
        except CheckpointerUnavailableError:
            raise
        except Exception as error:
            raise CheckpointerUnavailableError() from error

    def _pool(self) -> AsyncConnectionPool:
        return AsyncConnectionPool(
            self._database_url,
            kwargs=self._connection_kwargs(include_schema=True),
            min_size=1,
            max_size=4,
            open=False,
        )

    async def _connection(self):
        return await AsyncConnection.connect(
            self._database_url,
            **self._connection_kwargs(include_schema=False),
        )

    def _connection_kwargs(self, include_schema: bool) -> dict:
        options = f"-c search_path={self._schema}" if include_schema else None
        values = {
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        }
        if options is not None:
            values["options"] = options
        return values
