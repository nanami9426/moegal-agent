import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import LLMTokenUsage, User


class LLMTokenUsageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def test_usage_table_is_created_and_insertable(self) -> None:
        inspector = inspect(self.engine)
        self.assertIn("llm_token_usages", inspector.get_table_names())

        with Session(self.engine) as session:
            user = User(id=1_000_000_001, platform="qq", platform_user_id="openid-1")
            session.add(user)
            session.add(
                LLMTokenUsage(
                    user_id=user.id,
                    model="test-model",
                    request_path="/v1/chat/completions",
                    prompt_tokens=11,
                    completion_tokens=7,
                    total_tokens=18,
                    status_code=200,
                    elapsed_ms=123,
                    raw_usage={
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                    },
                    created_at=datetime(2026, 6, 30, 12, tzinfo=timezone.utc),
                )
            )
            session.commit()

            usage = session.exec(select(LLMTokenUsage)).one()

        self.assertEqual(usage.user_id, 1_000_000_001)
        self.assertEqual(usage.total_tokens, 18)
        self.assertEqual(usage.raw_usage["prompt_tokens"], 11)


if __name__ == "__main__":
    unittest.main()
