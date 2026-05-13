import os
from collections.abc import Generator

from sqlalchemy import create_engine
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
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
