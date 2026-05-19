import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bots.tg.handlers import unsubscribe_command


class TelegramHandlersTest(unittest.IsolatedAsyncioTestCase):
    async def test_unsubscribe_command_requires_target(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(args=[])

        await unsubscribe_command(update, context)

        update.message.reply_text.assert_awaited_once_with("用法：/unsubscribe 关键词")

    async def test_unsubscribe_command_deletes_subscription(self) -> None:
        user = SimpleNamespace(
            id=42,
            username="tester",
            first_name="Test",
            last_name=None,
            language_code="zh",
        )
        update = SimpleNamespace(
            effective_user=user,
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(args=["ブルアカ"])

        with (
            patch(
                "bots.tg.handlers.upsert_user",
                return_value=SimpleNamespace(id=1_000_000_001),
            ) as upsert_user_mock,
            patch(
                "bots.tg.handlers.delete_subscription",
                return_value=SimpleNamespace(
                    deleted=True,
                    subscription=SimpleNamespace(target="ブルアカ"),
                ),
            ) as delete_subscription_mock,
        ):
            await unsubscribe_command(update, context)

        upsert_user_mock.assert_called_once_with(
            platform="tg",
            platform_user_id="42",
            username="tester",
            display_name="Test",
            language_code="zh",
        )
        delete_subscription_mock.assert_called_once_with(
            user_id=1_000_000_001,
            target="ブルアカ",
        )
        update.message.reply_text.assert_awaited_once_with("已取消订阅：ブルアカ")


if __name__ == "__main__":
    unittest.main()
