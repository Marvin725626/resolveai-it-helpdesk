import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# Normalize sqlite URL for aiosqlite if sqlite is provided
db_url = settings.DATABASE_URL
if db_url.startswith("sqlite://") and not db_url.startswith("sqlite+aiosqlite://"):
    db_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)

engine = create_async_engine(
    db_url,
    echo=settings.DATABASE_ECHO,
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for providing an async database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initializes database schema and tables."""
    schema_mode = os.environ.get("APP_SCHEMA_MODE", "bootstrap")
    if schema_mode not in ("bootstrap", "migrate"):
        raise RuntimeError("APP_SCHEMA_MODE must be bootstrap or migrate")
    if schema_mode == "migrate":
        # Deployment entrypoint runs Alembic. Never mutate its schema via create_all.
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT version_num FROM alembic_version"))
        return
    # Import all models to ensure they are registered with Base metadata
    import app.models.tenant  # noqa
    import app.models.user  # noqa
    import app.models.invitation  # noqa
    import app.models.customer  # noqa
    import app.models.conversation  # noqa
    import app.models.document  # noqa
    import app.models.ticket  # noqa
    import app.models.analytics  # noqa
    import app.models.audit_log  # noqa
    import app.helpdesk.models  # noqa
    import app.helpdesk.catalog_models  # noqa

    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            from sqlalchemy import text
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # create_all skips indexes of an already-existing table; bootstrap only these named local indexes explicitly.
        for table_name,index_name in (("resolveai_runs","ix_resolveai_runs_scope_time"),("tickets","ix_resolveai_tickets_scope_time")):
            index=next(item for item in Base.metadata.tables[table_name].indexes if item.name==index_name)
            await conn.run_sync(lambda connection, index=index: index.create(connection,checkfirst=True))
        email_index = next(item for item in Base.metadata.tables["users"].indexes if item.name == "uq_users_email_lower")
        async with conn.begin_nested():
            if conn.dialect.name == "sqlite":
                from sqlalchemy import text
                exists = await conn.scalar(text("SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_users_email_lower'"))
            elif conn.dialect.name == "postgresql":
                from sqlalchemy import text
                exists = await conn.scalar(text("SELECT 1 FROM pg_indexes WHERE schemaname=current_schema() AND indexname='uq_users_email_lower'"))
            else:
                exists = None
            if not exists:
                await conn.run_sync(lambda connection: email_index.create(connection, checkfirst=False))
        if conn.dialect.name == "postgresql":
            from sqlalchemy import text
            await conn.execute(text("CREATE INDEX IF NOT EXISTS resolveai_embedding_hnsw ON resolveai_chunks USING hnsw (embedding vector_cosine_ops)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS resolveai_search_gin ON resolveai_chunks USING gin (to_tsvector('simple', search_text))"))
