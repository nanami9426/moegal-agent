import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
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
    embedding_enabled = bool(os.getenv("MOEGAL_EMBEDDING_MODEL", "").strip())
    if embedding_enabled:
        # 只有启用语义检索时才要求数据库安装 pgvector，避免影响原有功能启动。
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except SQLAlchemyError as exc:
            raise RuntimeError(
                "已配置 MOEGAL_EMBEDDING_MODEL，但 PostgreSQL 无法启用 vector 扩展。"
                "请让数据库管理员安装 pgvector 并授予扩展创建权限。"
            ) from exc
        SQLModel.metadata.create_all(engine)
        return

    tables = [
        table
        for table in SQLModel.metadata.sorted_tables
        if table.name != "content_chunks"
    ]
    SQLModel.metadata.create_all(engine, tables=tables)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
