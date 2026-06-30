import unittest

from sqlalchemy import DateTime
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

import db.models  # noqa: F401


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
        )

        self.assertIn("TIMESTAMP WITH TIME ZONE", ddl)
        self.assertNotIn("TIMESTAMP WITHOUT TIME ZONE", ddl)


if __name__ == "__main__":
    unittest.main()
