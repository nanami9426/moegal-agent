import unittest
from contextlib import AbstractContextManager
from types import SimpleNamespace

from db.session import _upgrade_memory_schema


class _FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement) -> None:
        self.statements.append(str(statement))


class _FakeBegin(AbstractContextManager):
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


class _FakeEngine:
    def __init__(self, dialect: str) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.connection = _FakeConnection()

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self.connection)


class MemorySchemaUpgradeTest(unittest.TestCase):
    def test_postgres_upgrade_contains_namespace_constraint_and_search_index(self) -> None:
        engine = _FakeEngine("postgresql")

        _upgrade_memory_schema(engine)

        ddl = "\n".join(engine.connection.statements)
        self.assertIn("ADD COLUMN IF NOT EXISTS namespace", ddl)
        self.assertIn("uq_user_memories_user_namespace_kind_key", ddl)
        self.assertIn("ix_user_memories_search", ddl)
        self.assertIn("to_tsvector", ddl)

    def test_non_postgres_upgrade_is_noop(self) -> None:
        engine = _FakeEngine("sqlite")

        _upgrade_memory_schema(engine)

        self.assertEqual(engine.connection.statements, [])


if __name__ == "__main__":
    unittest.main()
