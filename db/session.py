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


def _create_server_engine(database_url: str) -> Engine:
    # 创建一个不指定具体数据库名的 MySQL 连接
    url = make_url(database_url)
    server_url = url.set(database="")
    return create_engine(server_url, pool_pre_ping=True)


def _ensure_mysql_database_exists(database_url: str) -> None:
    url = make_url(database_url)

    if not url.drivername.startswith("mysql") or not url.database:
        return

    database_name = url.database.replace("`", "``")

    with _create_server_engine(database_url).begin() as connection:
        connection.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )


def create_db_engine() -> Engine:
    database_url = get_database_url()
    _ensure_mysql_database_exists(database_url)
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
