import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
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
    # create_all 只适合早期阶段：它会创建缺失的表，但不会自动迁移已有表结构。
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    # conversations 是已有表，新增列需要显式补齐，避免老库启动时报缺列。
    _ensure_conversation_schema(engine)


def _ensure_conversation_schema(engine: Engine) -> None:
    # SQLite 测试库没有生产表迁移需求，这里只处理 PostgreSQL。
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    if "conversations" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("conversations")}
    # 项目还没有正式迁移系统，先用幂等 DDL 兼容已有开发库。
    ddl_by_column = {
        "platform_user_id": "ALTER TABLE conversations ADD COLUMN platform_user_id VARCHAR(128)",
        "thread_id": "ALTER TABLE conversations ADD COLUMN thread_id VARCHAR(255)",
        "version": "ALTER TABLE conversations ADD COLUMN version INTEGER NOT NULL DEFAULT 0",
        "is_active": "ALTER TABLE conversations ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE",
        "ended_at": "ALTER TABLE conversations ADD COLUMN ended_at TIMESTAMP WITH TIME ZONE",
    }

    with engine.begin() as connection:
        for column_name, ddl in ddl_by_column.items():
            if column_name not in existing_columns:
                connection.execute(text(ddl))

        # 老数据可能还没有 thread_id，唯一索引用 partial index 避开 NULL。
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_conversations_thread_id_unique "
                "ON conversations (thread_id) WHERE thread_id IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_conversations_platform_user_version_unique "
                "ON conversations (platform, platform_user_id, version) "
                "WHERE platform_user_id IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_conversations_platform_user_active "
                "ON conversations (platform, platform_user_id, is_active)"
            )
        )


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
