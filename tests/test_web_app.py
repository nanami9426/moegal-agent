import os
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import Conversation, LLMTokenUsage, Message, Subscription, User, UserMemory
from services.account.bindings import complete_platform_link
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
        self.stack.enter_context(patch("db.session.get_engine", return_value=self.engine))
        self.stack.enter_context(patch("services.account.bindings.get_engine", return_value=self.engine))
        self.stack.enter_context(patch("services.account.web_auth.get_engine", return_value=self.engine))
        self.stack.enter_context(patch("services.account.memories.get_engine", return_value=self.engine))
        self.stack.enter_context(
            patch("services.account.conversation_memories.get_engine", return_value=self.engine)
        )
        self.client = TestClient(create_app(init_database=False))

    def tearDown(self) -> None:
        self.stack.close()

    def test_subscriptions_requires_auth_and_binding(self) -> None:
        missing_auth = self.client.get(
            "/api/subscriptions",
            params={"platform": "tg", "platform_user_id": "42"},
        )
        self.assertEqual(missing_auth.status_code, 401)

        token = self._register_web_user()[0]
        unbound = self.client.get(
            "/api/subscriptions",
            params={"platform": "tg", "platform_user_id": "42"},
            headers=self._auth_headers(token),
        )
        self.assertEqual(unbound.status_code, 403)

        self._bind_platform_user(token, platform="tg", platform_user_id="42")
        response = self.client.get(
            "/api/subscriptions",
            params={"platform": "tg", "platform_user_id": "42"},
            headers=self._auth_headers(token),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["subscriptions"]), 1)
        self.assertEqual(data["subscriptions"][0]["target"], "ブルアカ")
        self.assertNotIn("enabled", data["subscriptions"][0])

    def test_chat_history_returns_conversations_and_messages_in_order(self) -> None:
        token = self._register_web_user()[0]
        self._bind_platform_user(token, platform="tg", platform_user_id="42")

        response = self.client.get(
            "/api/chat-history",
            params={
                "platform": "tg",
                "platform_user_id": "42",
                "conversation_limit": 10,
                "message_limit": 10,
            },
            headers=self._auth_headers(token),
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

    def test_token_usage_returns_aggregates_for_bound_user(self) -> None:
        token = self._register_web_user()[0]
        self._bind_platform_user(token, platform="tg", platform_user_id="42")

        with Session(self.engine) as session:
            session.add_all(
                [
                    LLMTokenUsage(
                        user_id=1_000_000_001,
                        model="gpt-test-mini",
                        request_path="/v1/chat/completions",
                        prompt_tokens=10,
                        completion_tokens=5,
                        total_tokens=15,
                        status_code=200,
                        elapsed_ms=120,
                        raw_usage={
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "total_tokens": 15,
                        },
                        created_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
                    ),
                    LLMTokenUsage(
                        user_id=1_000_000_001,
                        model="gpt-test-mini",
                        request_path="/v1/chat/completions",
                        prompt_tokens=7,
                        completion_tokens=8,
                        total_tokens=15,
                        status_code=200,
                        elapsed_ms=80,
                        raw_usage={
                            "prompt_tokens": 7,
                            "completion_tokens": 8,
                            "total_tokens": 15,
                        },
                        created_at=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc),
                    ),
                    LLMTokenUsage(
                        user_id=1_000_000_001,
                        model="gpt-test-large",
                        request_path="/v1/responses",
                        prompt_tokens=20,
                        completion_tokens=10,
                        total_tokens=30,
                        status_code=200,
                        elapsed_ms=300,
                        raw_usage={
                            "prompt_tokens": 20,
                            "completion_tokens": 10,
                            "total_tokens": 30,
                        },
                        created_at=datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc),
                    ),
                    LLMTokenUsage(
                        user_id=1_000_000_002,
                        model="gpt-test-mini",
                        request_path="/v1/chat/completions",
                        prompt_tokens=100,
                        completion_tokens=100,
                        total_tokens=200,
                        status_code=200,
                        elapsed_ms=500,
                        raw_usage={
                            "prompt_tokens": 100,
                            "completion_tokens": 100,
                            "total_tokens": 200,
                        },
                        created_at=datetime(2026, 1, 1, 13, tzinfo=timezone.utc),
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/token-usage",
            params={"platform": "tg", "platform_user_id": "42", "recent_limit": 2},
            headers=self._auth_headers(token),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["request_count"], 3)
        self.assertEqual(payload["summary"]["prompt_tokens"], 37)
        self.assertEqual(payload["summary"]["completion_tokens"], 23)
        self.assertEqual(payload["summary"]["total_tokens"], 60)
        self.assertEqual(payload["summary"]["average_elapsed_ms"], 167)
        self.assertEqual(
            [item["model"] for item in payload["by_model"]],
            ["gpt-test-large", "gpt-test-mini"],
        )
        self.assertEqual(payload["by_model"][0]["total_tokens"], 30)
        self.assertEqual([record["model"] for record in payload["recent"]], [
            "gpt-test-large",
            "gpt-test-mini",
        ])

        forbidden = self.client.get(
            "/api/token-usage",
            params={"platform": "qq", "platform_user_id": "qq-42"},
            headers=self._auth_headers(token),
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_unbound_or_unknown_user_is_forbidden(self) -> None:
        token = self._register_web_user()[0]
        subscriptions = self.client.get(
            "/api/subscriptions",
            params={"platform": "tg", "platform_user_id": "missing"},
            headers=self._auth_headers(token),
        )
        chat_history = self.client.get(
            "/api/chat-history",
            params={"platform": "tg", "platform_user_id": "missing"},
            headers=self._auth_headers(token),
        )

        self.assertEqual(subscriptions.status_code, 403)
        self.assertEqual(chat_history.status_code, 403)

    def test_required_query_params_reject_missing_or_blank_values(self) -> None:
        token = self._register_web_user()[0]
        for path in ("/api/subscriptions", "/api/chat-history"):
            missing = self.client.get(
                path,
                params={"platform": "tg"},
                headers=self._auth_headers(token),
            )
            blank = self.client.get(
                path,
                params={"platform": "  ", "platform_user_id": "42"},
                headers=self._auth_headers(token),
            )

            self.assertEqual(missing.status_code, 422)
            self.assertEqual(blank.status_code, 422)

    def test_admin_link_code_binds_bot_account_and_lists_bindings(self) -> None:
        token, web_user_id = self._register_web_user()

        initial_accounts = self.client.get(
            "/api/admin/bindings",
            headers=self._auth_headers(token),
        )
        self.assertEqual(initial_accounts.status_code, 200)
        initial_payload = initial_accounts.json()
        self.assertEqual(initial_payload["max_per_platform"], 2)
        self.assertEqual(len(initial_payload["bindings"]), 1)
        self.assertEqual(initial_payload["bindings"][0]["platform"], "web")
        self.assertEqual(initial_payload["bindings"][0]["platform_user_id"], str(web_user_id))

        code_response = self.client.post(
            "/api/admin/link-codes",
            headers=self._auth_headers(token),
        )
        self.assertEqual(code_response.status_code, 200)
        code_payload = code_response.json()
        self.assertRegex(code_payload["code"], r"^[A-Z2-9]{8}$")
        self.assertNotIn("platform", code_payload)
        self.assertTrue(code_payload["expires_at"])

        result = complete_platform_link(
            platform="tg",
            platform_user_id="42",
            code=code_payload["code"],
            username="tester",
            display_name="Test User",
            language_code="zh",
        )
        self.assertFalse(result.already_bound)

        bindings = self.client.get(
            "/api/admin/bindings",
            headers=self._auth_headers(token),
        )
        self.assertEqual(bindings.status_code, 200)
        binding_payload = bindings.json()["bindings"]
        self.assertEqual(len(binding_payload), 2)
        self.assertEqual(binding_payload[0]["platform"], "web")
        self.assertEqual(binding_payload[1]["platform"], "tg")
        self.assertEqual(binding_payload[1]["platform_user_id"], "42")
        self.assertEqual(binding_payload[1]["display_name"], "Test User")

    def test_admin_can_read_current_web_account_resources(self) -> None:
        token, web_user_id = self._register_web_user()
        login_id = str(web_user_id)

        with Session(self.engine) as session:
            web_user = session.get(User, web_user_id)
            self.assertIsNotNone(web_user)
            session.add(
                Subscription(
                    user_id=web_user_id,
                    type="keyword",
                    target="网页订阅",
                    display_name="网页订阅",
                    enabled=True,
                    created_at=datetime(2026, 1, 3, 12, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 1, 3, 12, tzinfo=timezone.utc),
                )
            )
            conversation = Conversation(
                user_id=web_user_id,
                platform="web",
                platform_user_id=login_id,
                thread_id="web-admin-thread",
                version=0,
                is_active=True,
                created_at=datetime(2026, 1, 3, 13, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 3, 13, tzinfo=timezone.utc),
            )
            session.add(conversation)
            session.flush()
            session.add(
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content="后台能看到 Web 吗",
                    metadata_json={},
                    created_at=datetime(2026, 1, 3, 13, 1, tzinfo=timezone.utc),
                )
            )
            session.commit()

        subscriptions = self.client.get(
            "/api/subscriptions",
            params={"platform": "web", "platform_user_id": login_id},
            headers=self._auth_headers(token),
        )
        chat_history = self.client.get(
            "/api/chat-history",
            params={"platform": "web", "platform_user_id": login_id},
            headers=self._auth_headers(token),
        )

        self.assertEqual(subscriptions.status_code, 200)
        self.assertEqual(subscriptions.json()["subscriptions"][0]["target"], "网页订阅")
        self.assertEqual(chat_history.status_code, 200)
        self.assertEqual(
            chat_history.json()["conversations"][0]["messages"][0]["content"],
            "后台能看到 Web 吗",
        )

        other_token, other_web_user_id = self._register_web_user(username="Other Web")
        forbidden = self.client.get(
            "/api/chat-history",
            params={"platform": "web", "platform_user_id": str(web_user_id)},
            headers=self._auth_headers(other_token),
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_link_code_respects_platform_binding_limit_env(self) -> None:
        token = self._register_web_user()[0]

        with patch.dict(os.environ, {"MOEGAL_MAX_LINKED_BOT_USERS_PER_PLATFORM": "1"}):
            self._bind_platform_user(token, platform="tg", platform_user_id="42")
            code_response = self.client.post(
                "/api/admin/link-codes",
                headers=self._auth_headers(token),
            )
            self.assertEqual(code_response.status_code, 200)
            code = code_response.json()["code"]

            with self.assertRaisesRegex(ValueError, "最多绑定 1 个 Telegram 账号"):
                complete_platform_link(
                    platform="tg",
                    platform_user_id="43",
                    code=code,
                )

            result = complete_platform_link(
                platform="qq",
                platform_user_id="qq-42",
                code=code,
            )
            self.assertFalse(result.already_bound)

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

        with patch("web.api.chat.route_message", AsyncMock(return_value="你好呀")) as route_mock:
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
            temporary=False,
            temporary_thread_id=None,
        )

    def test_web_chat_stream_requires_auth_and_streams_events(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={"username": "Alice Web", "password": "secret1"},
        )
        token = registered.json()["token"]
        login_id = str(registered.json()["user"]["id"])

        missing_auth = self.client.post(
            "/api/web-chat/messages/stream",
            json={"message": "你好"},
        )
        self.assertEqual(missing_auth.status_code, 401)

        async def fake_stream(*args, **kwargs):
            yield "你"
            yield "好"

        stream_mock = MagicMock(side_effect=fake_stream)
        with patch("web.api.chat.route_message_stream", stream_mock):
            response = self.client.post(
                "/api/web-chat/messages/stream",
                json={"message": "  你好  "},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('data: {"delta":"你"}', response.text)
        self.assertIn('data: {"delta":"好"}', response.text)
        self.assertIn('event: done\ndata: {"reply":"你好"}', response.text)
        stream_mock.assert_called_once_with(
            "web",
            login_id,
            "你好",
            username="Alice Web",
            display_name="Alice Web",
            temporary=False,
            temporary_thread_id=None,
        )

    def test_web_chat_new_reports_empty_current_conversation(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={"username": "Alice Web", "password": "secret1"},
        )
        token = registered.json()["token"]

        with patch(
            "web.api.chat.start_new_conversation_context",
            return_value=SimpleNamespace(created=False),
        ) as start_new_mock:
            response = self.client.post(
                "/api/web-chat/new",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"created": False, "message": "已在新对话中。"})
        start_new_mock.assert_called_once()

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

    def test_web_memory_management_and_settings(self) -> None:
        token, user_id = self._register_web_user()
        with Session(self.engine) as session:
            memory = UserMemory(
                user_id=user_id,
                namespace="global",
                kind="preference",
                key="preference.anime.genre",
                content="用户喜欢日常系动画。",
            )
            session.add(memory)
            session.commit()
            session.refresh(memory)
            memory_id = memory.id

        listed = self.client.get(
            "/api/web-chat/memories",
            headers=self._auth_headers(token),
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["memories"][0]["id"], memory_id)

        updated = self.client.patch(
            f"/api/web-chat/memories/{memory_id}",
            json={"content": "用户现在更喜欢治愈系动画。", "importance": 0.9},
            headers=self._auth_headers(token),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["content"], "用户现在更喜欢治愈系动画。")
        self.assertEqual(updated.json()["importance"], 0.9)

        settings = self.client.get(
            "/api/web-chat/memory-settings",
            headers=self._auth_headers(token),
        )
        self.assertEqual(settings.status_code, 200)
        self.assertTrue(settings.json()["enabled"])

        paused = self.client.patch(
            "/api/web-chat/memory-settings",
            json={"enabled": False, "auto_extract": False},
            headers=self._auth_headers(token),
        )
        self.assertEqual(paused.status_code, 200)
        self.assertFalse(paused.json()["enabled"])
        self.assertFalse(paused.json()["auto_extract"])

        deleted = self.client.delete(
            f"/api/web-chat/memories/{memory_id}",
            headers=self._auth_headers(token),
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json(), {"deleted": True})

        with Session(self.engine) as session:
            session.add(
                UserMemory(
                    user_id=user_id,
                    namespace="global",
                    kind="note",
                    key="another.memory",
                    content="另一条记忆。",
                )
            )
            session.commit()
        cleared = self.client.delete(
            "/api/web-chat/memories",
            headers=self._auth_headers(token),
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json(), {"deleted_count": 1})

    def test_web_temporary_chat_passes_non_persistent_options(self) -> None:
        token, user_id = self._register_web_user()
        with patch("web.api.chat.route_message", AsyncMock(return_value="临时回复")) as route_mock:
            response = self.client.post(
                "/api/web-chat/messages",
                json={
                    "message": "不要记住这句话",
                    "temporary": True,
                    "temporary_thread_id": "temp-1",
                },
                headers=self._auth_headers(token),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reply": "临时回复"})
        route_mock.assert_awaited_once_with(
            "web",
            str(user_id),
            "不要记住这句话",
            username="Alice Web",
            display_name="Alice Web",
            temporary=True,
            temporary_thread_id="temp-1",
        )

    def _register_web_user(
        self,
        *,
        username: str = "Alice Web",
        password: str = "secret1",
    ) -> tuple[str, int]:
        registered = self.client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        self.assertEqual(registered.status_code, 200)
        payload = registered.json()
        return payload["token"], payload["user"]["id"]

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _bind_platform_user(
        self,
        token: str,
        *,
        platform: str,
        platform_user_id: str,
    ) -> None:
        code_response = self.client.post(
            "/api/admin/link-codes",
            headers=self._auth_headers(token),
        )
        self.assertEqual(code_response.status_code, 200)
        complete_platform_link(
            platform=platform,
            platform_user_id=platform_user_id,
            code=code_response.json()["code"],
        )

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
