import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, SQLModel

# 导入模型模块，确保 SQLModel.metadata 能收集到所有表。
import db.models  # noqa: F401

# 避免每次访问数据库时都重新创建 engine
_engine: Engine | None = None


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("Missing DATABASE_URL. 请先在 .env 中配置。")

    return database_url


def get_psycopg_conninfo() -> str:
    """把 SQLAlchemy 连接串转换成 psycopg 可以直接使用的连接串。"""
    url = make_url(get_database_url())
    # SQLAlchemy 使用 postgresql+psycopg，psycopg 原生连接只认 postgresql。
    if url.drivername.startswith("postgresql+"):
        url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _validate_postgres_url(database_url: str) -> None:
    url = make_url(database_url)

    if not url.drivername.startswith("postgresql"):
        raise RuntimeError(
            "DATABASE_URL must use PostgreSQL, for example "
            "postgresql+psycopg://user:password@host:5432/database."
        )

    if not url.database:
        raise RuntimeError("DATABASE_URL must include a PostgreSQL database name.")


def create_db_engine() -> Engine:
    database_url = get_database_url()
    _validate_postgres_url(database_url)
    return create_engine(database_url, pool_pre_ping=True)


def get_engine() -> Engine:
    global _engine

    if _engine is None:
        _engine = create_db_engine()

    return _engine


def init_db() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _upgrade_memory_schema(engine)


def _upgrade_memory_schema(engine: Engine) -> None:
    """为 create_all 无法修改的旧表补齐记忆字段。

    项目暂未引入正式迁移框架，因此这里只维护一段 PostgreSQL 幂等升级；新数据库
    会由 SQLModel 直接创建完整结构。
    """
    if engine.dialect.name != "postgresql":
        return

    statements = (
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS namespace VARCHAR(255) NOT NULL DEFAULT 'global'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source VARCHAR(32) NOT NULL DEFAULT 'legacy'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS importance DOUBLE PRECISION NOT NULL DEFAULT 0.5",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source_message_id INTEGER NULL",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ NULL",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS metadata_json JSON NOT NULL DEFAULT '{}'::json",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_source ON user_memories (source)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_namespace ON user_memories (namespace)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_source_message_id ON user_memories (source_message_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_expires_at ON user_memories (expires_at)",
        """
        CREATE INDEX IF NOT EXISTS ix_user_memories_search
        ON user_memories USING GIN (
            to_tsvector('simple', coalesce(key, '') || ' ' || coalesce(content, ''))
        )
        """,
        "ALTER TABLE user_memories DROP CONSTRAINT IF EXISTS uq_user_memories_user_kind_key",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_user_memories_user_namespace_kind_key'
            ) THEN
                ALTER TABLE user_memories
                ADD CONSTRAINT uq_user_memories_user_namespace_kind_key
                UNIQUE (user_id, namespace, kind, key);
            END IF;
        END $$
        """,
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
