import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import DateTime
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

import db.models  # noqa: F401
from db.session import init_db


class DatabaseModelTest(unittest.TestCase):
    def test_datetime_columns_keep_timezone_information(self) -> None:
        naive_columns = []

        for table in SQLModel.metadata.sorted_tables:
            for column in table.columns:
                if isinstance(column.type, DateTime) and not column.type.timezone:
                    naive_columns.append(f"{table.name}.{column.name}")

        self.assertEqual(naive_columns, [])

    def test_postgres_schema_uses_timestamptz_for_datetimes(self) -> None:
        ddl = "\n".join(
            str(CreateTable(table).compile(dialect=postgresql.dialect()))
            for table in SQLModel.metadata.sorted_tables
            if table.name != "content_chunks"
        )

        self.assertIn("TIMESTAMP WITH TIME ZONE", ddl)
        self.assertNotIn("TIMESTAMP WITHOUT TIME ZONE", ddl)

    def test_postgres_content_chunks_use_pgvector(self) -> None:
        # pgvector 会注册 PostgreSQL 类型；放在独立进程验证，避免污染异步测试事件循环。
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from sqlalchemy.dialects import postgresql; "
                "from sqlalchemy.schema import CreateTable; "
                "from sqlmodel import SQLModel; import db.models; "
                "print(CreateTable(SQLModel.metadata.tables['content_chunks'])"
                ".compile(dialect=postgresql.dialect()))",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        ddl = result.stdout

        self.assertIn("embedding VECTOR NOT NULL", ddl)
        self.assertIn("uq_content_chunks_item_index", ddl)

    def test_init_db_does_not_require_pgvector_when_embedding_is_disabled(self) -> None:
        engine = MagicMock()
        with (
            patch.dict("os.environ", {"MOEGAL_EMBEDDING_MODEL": ""}),
            patch("db.session.get_engine", return_value=engine),
            patch.object(SQLModel.metadata, "create_all") as create_all,
        ):
            init_db()

        engine.begin.assert_not_called()
        table_names = {table.name for table in create_all.call_args.kwargs["tables"]}
        self.assertNotIn("content_chunks", table_names)
        self.assertIn("content_items", table_names)

    def test_init_db_enables_pgvector_when_embedding_is_configured(self) -> None:
        engine = MagicMock()
        connection = engine.begin.return_value.__enter__.return_value
        with (
            patch.dict("os.environ", {"MOEGAL_EMBEDDING_MODEL": "test-embedding"}),
            patch("db.session.get_engine", return_value=engine),
            patch.object(SQLModel.metadata, "create_all") as create_all,
        ):
            init_db()

        self.assertIn(
            "CREATE EXTENSION IF NOT EXISTS vector",
            str(connection.execute.call_args.args[0]),
        )
        create_all.assert_called_once_with(engine)


if __name__ == "__main__":
    unittest.main()
