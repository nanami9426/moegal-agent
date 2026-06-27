import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import Conversation, Message, Subscription, User
from web.app import create_app


class WebApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self._seed_data()

        self.stack = ExitStack()
        self.stack.enter_context(patch("web.routes.get_engine", return_value=self.engine))
        self.stack.enter_context(patch("services.account.web_auth.get_engine", return_value=self.engine))
        self.client = TestClient(create_app(init_database=False))

    def tearDown(self) -> None:
        self.stack.close()

    def test_subscriptions_returns_only_active_records_for_requested_user(self) -> None:
        response = self.client.get(
            "/api/subscriptions",
            params={"platform": "tg", "platform_user_id": "42"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["subscriptions"]), 1)
        self.assertEqual(data["subscriptions"][0]["target"], "ブルアカ")
        self.assertNotIn("enabled", data["subscriptions"][0])

    def test_chat_history_returns_conversations_and_messages_in_order(self) -> None:
        response = self.client.get(
            "/api/chat-history",
            params={
                "platform": "tg",
                "platform_user_id": "42",
                "conversation_limit": 10,
                "message_limit": 10,
            },
        )

        self.assertEqual(response.status_code, 200)
        conversations = response.json()["conversations"]
        self.assertEqual([conversation["version"] for conversation in conversations], [1, 0])
        self.assertEqual(conversations[0]["is_active"], True)
        self.assertEqual(
            [message["role"] for message in conversations[0]["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(conversations[0]["messages"][0]["content"], "继续聊")
        self.assertNotIn("thread_id", conversations[0])
        self.assertNotIn("metadata_json", conversations[0]["messages"][0])

    def test_unknown_user_returns_empty_arrays(self) -> None:
        subscriptions = self.client.get(
            "/api/subscriptions",
            params={"platform": "tg", "platform_user_id": "missing"},
        )
        chat_history = self.client.get(
            "/api/chat-history",
            params={"platform": "tg", "platform_user_id": "missing"},
        )

        self.assertEqual(subscriptions.status_code, 200)
        self.assertEqual(chat_history.status_code, 200)
        self.assertEqual(subscriptions.json(), {"subscriptions": []})
        self.assertEqual(chat_history.json(), {"conversations": []})

    def test_required_query_params_reject_missing_or_blank_values(self) -> None:
        for path in ("/api/subscriptions", "/api/chat-history"):
            missing = self.client.get(path, params={"platform": "tg"})
            blank = self.client.get(
                path,
                params={"platform": "  ", "platform_user_id": "42"},
            )

            self.assertEqual(missing.status_code, 422)
            self.assertEqual(blank.status_code, 422)

    def test_web_auth_register_login_me_and_logout(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={"username": "Alice Web", "password": "secret1"},
        )

        self.assertEqual(registered.status_code, 200)
        registered_payload = registered.json()
        self.assertTrue(registered_payload["token"])
        login_id = str(registered_payload["user"]["id"])
        self.assertRegex(login_id, r"^\d{10}$")
        self.assertEqual(registered_payload["user"]["username"], "Alice Web")

        bad_login = self.client.post(
            "/api/auth/login",
            json={"user_id": login_id, "password": "wrong-password"},
        )
        self.assertEqual(bad_login.status_code, 401)

        logged_in = self.client.post(
            "/api/auth/login",
            json={"user_id": login_id, "password": "secret1"},
        )
        self.assertEqual(logged_in.status_code, 200)
        token = logged_in.json()["token"]

        me = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["id"], registered_payload["user"]["id"])

        logged_out = self.client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(logged_out.json(), {"revoked": True})

        expired_me = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(expired_me.status_code, 401)

    def test_web_chat_requires_auth_and_routes_message(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={"username": "Alice Web", "password": "secret1"},
        )
        token = registered.json()["token"]
        login_id = str(registered.json()["user"]["id"])

        missing_auth = self.client.post(
            "/api/web-chat/messages",
            json={"message": "你好"},
        )
        self.assertEqual(missing_auth.status_code, 401)

        with patch("web.routes.route_message", AsyncMock(return_value="你好呀")) as route_mock:
            response = self.client.post(
                "/api/web-chat/messages",
                json={"message": "  你好  "},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reply": "你好呀"})
        route_mock.assert_awaited_once_with(
            "web",
            login_id,
            "你好",
            username="Alice Web",
            display_name="Alice Web",
        )

    def test_web_chat_history_uses_authenticated_web_user(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={"username": "Alice Web", "password": "secret1"},
        )
        token = registered.json()["token"]
        login_id = str(registered.json()["user"]["id"])

        with Session(self.engine) as session:
            user = session.exec(
                select(User).where(
                    User.platform == "web",
                    User.platform_user_id == login_id,
                )
            ).one()
            conversation = Conversation(
                user_id=user.id,
                platform="web",
                platform_user_id=login_id,
                thread_id="web-thread",
                version=0,
                is_active=True,
                created_at=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
            )
            session.add(conversation)
            session.flush()
            session.add(
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content="Web 消息",
                    metadata_json={},
                    created_at=datetime(2026, 1, 2, 12, 1, tzinfo=timezone.utc),
                )
            )
            session.commit()

        response = self.client.get(
            "/api/web-chat/history",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        conversations = response.json()["conversations"]
        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["messages"][0]["content"], "Web 消息")

    def _seed_data(self) -> None:
        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        tg_user = User(
            id=1_000_000_001,
            platform="tg",
            platform_user_id="42",
            username="tester",
        )
        qq_user = User(
            id=1_000_000_002,
            platform="qq",
            platform_user_id="qq-42",
            username="qqtester",
        )

        with Session(self.engine) as session:
            session.add_all([tg_user, qq_user])
            session.flush()
            session.add_all(
                [
                    Subscription(
                        user_id=tg_user.id,
                        type="keyword",
                        target="ブルアカ",
                        display_name="ブルアカ",
                        enabled=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    Subscription(
                        user_id=tg_user.id,
                        type="keyword",
                        target="原神",
                        display_name="原神",
                        enabled=False,
                        created_at=now + timedelta(minutes=1),
                        updated_at=now + timedelta(minutes=1),
                    ),
                    Subscription(
                        user_id=qq_user.id,
                        type="keyword",
                        target="明日方舟",
                        display_name="明日方舟",
                        enabled=True,
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )

            old_conversation = Conversation(
                user_id=tg_user.id,
                platform="tg",
                platform_user_id="42",
                thread_id="old-thread",
                version=0,
                is_active=False,
                created_at=now,
                updated_at=now + timedelta(minutes=10),
                ended_at=now + timedelta(minutes=10),
            )
            new_conversation = Conversation(
                user_id=tg_user.id,
                platform="tg",
                platform_user_id="42",
                thread_id="new-thread",
                version=1,
                is_active=True,
                created_at=now + timedelta(minutes=11),
                updated_at=now + timedelta(minutes=20),
            )
            qq_conversation = Conversation(
                user_id=qq_user.id,
                platform="qq",
                platform_user_id="qq-42",
                thread_id="qq-thread",
                version=0,
                is_active=True,
                created_at=now,
                updated_at=now + timedelta(minutes=30),
            )
            session.add_all([old_conversation, new_conversation, qq_conversation])
            session.flush()

            session.add_all(
                [
                    Message(
                        conversation_id=old_conversation.id,
                        role="user",
                        content="你好",
                        metadata_json={"thread_id": "old-thread"},
                        created_at=now + timedelta(minutes=2),
                    ),
                    Message(
                        conversation_id=new_conversation.id,
                        role="user",
                        content="继续聊",
                        metadata_json={"thread_id": "new-thread"},
                        created_at=now + timedelta(minutes=12),
                    ),
                    Message(
                        conversation_id=new_conversation.id,
                        role="assistant",
                        content="可以",
                        metadata_json={"thread_id": "new-thread"},
                        created_at=now + timedelta(minutes=13),
                    ),
                    Message(
                        conversation_id=qq_conversation.id,
                        role="user",
                        content="QQ 消息",
                        metadata_json={"thread_id": "qq-thread"},
                        created_at=now + timedelta(minutes=1),
                    ),
                ]
            )
            session.commit()


if __name__ == "__main__":
    unittest.main()
