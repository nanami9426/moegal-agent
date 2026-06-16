import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bots.qq.app import QQClient


class QQClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_c2c_message_replies_once_with_original_message(self) -> None:
        client = QQClient.__new__(QQClient)
        message = SimpleNamespace(
            author=SimpleNamespace(user_openid="openid-1"),
            content="  你好  ",
            id="msg-1",
            reply=AsyncMock(),
        )

        with patch(
            "bots.qq.app.route_message",
            AsyncMock(return_value="测试回复：你好"),
        ) as route_message_mock:
            await client.on_c2c_message_create(message)

        route_message_mock.assert_awaited_once_with("qq", "openid-1", "你好")
        message.reply.assert_awaited_once_with(msg_type=0, content="测试回复：你好")


if __name__ == "__main__":
    unittest.main()
