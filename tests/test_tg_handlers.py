import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bots.tg.handlers import (
    PENDING_TRANSLATE_PHOTO_KEY,
    handel_receive_picture,
    newchat_command,
    translate_command,
    unsubscribe_command,
)


class TelegramHandlersTest(unittest.IsolatedAsyncioTestCase):
    async def test_translate_command_prompts_for_picture(self) -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={})

        await translate_command(update, context)

        self.assertTrue(context.user_data[PENDING_TRANSLATE_PHOTO_KEY])
        update.message.reply_text.assert_awaited_once_with("请发送要翻译的漫画图片。")

    async def test_handel_receive_picture_replies_with_translated_image(self) -> None:
        raw_image = b"raw-image"
        translated_image = b"translated-image"

        class FakeTelegramFile:
            async def download_to_drive(self, path: Path) -> None:
                path.write_bytes(raw_image)

            async def download_as_bytearray(self) -> bytearray:
                return bytearray(raw_image)

        photo = SimpleNamespace(
            file_unique_id="photo-1",
            get_file=AsyncMock(return_value=FakeTelegramFile()),
        )
        message = SimpleNamespace(
            photo=[photo],
            from_user=SimpleNamespace(id=42),
            reply_text=AsyncMock(),
            reply_photo=AsyncMock(),
            reply_document=AsyncMock(),
        )
        update = SimpleNamespace(message=message)
        context = SimpleNamespace(user_data={PENDING_TRANSLATE_PHOTO_KEY: True})

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("bots.tg.handlers.TG_SAVED_PICTURES_DIR", Path(tmpdir)),
            patch(
                "bots.tg.handlers.translate_image_bytes",
                AsyncMock(
                    return_value=(
                        ["原文"],
                        ["译文"],
                        (base64.b64encode(translated_image).decode("utf8"), "translated.png"),
                    )
                ),
            ) as translate_image_bytes_mock,
        ):
            await handel_receive_picture(update, context)

        self.assertNotIn(PENDING_TRANSLATE_PHOTO_KEY, context.user_data)
        translate_image_bytes_mock.assert_awaited_once_with(raw_image, include_res_img=True)
        message.reply_text.assert_awaited_once_with("图片已保存")
        message.reply_photo.assert_awaited_once()
        sent_photo = message.reply_photo.await_args.kwargs["photo"]
        self.assertEqual(sent_photo.getvalue(), translated_image)
        self.assertEqual(sent_photo.name, "translated.png")
        self.assertEqual(message.reply_photo.await_args.kwargs["caption"], "翻译后的图片")
        message.reply_document.assert_awaited_once()
        sent_document = message.reply_document.await_args.kwargs["document"]
        self.assertEqual(sent_document.getvalue(), translated_image)
        self.assertEqual(sent_document.tell(), 0)
        self.assertEqual(sent_document.name, "translated.png")
        self.assertEqual(message.reply_document.await_args.kwargs["caption"], "翻译后的图片")

    async def test_handel_receive_picture_requires_translate_command(self) -> None:
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(message=message)
        context = SimpleNamespace(user_data={})

        with patch(
            "bots.tg.handlers.translate_image_bytes",
            AsyncMock(),
        ) as translate_image_bytes_mock:
            await handel_receive_picture(update, context)

        translate_image_bytes_mock.assert_not_awaited()
        message.reply_text.assert_awaited_once_with(
            "请先发送 /translate，然后再发送漫画图片。"
        )

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

    async def test_newchat_command_starts_new_context(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(args=[])

        with patch(
            "bots.tg.handlers.start_new_conversation_context",
            return_value="tg:42:v1",
        ) as start_new_context_mock:
            await newchat_command(update, context)

        start_new_context_mock.assert_called_once_with("tg", "42")
        update.message.reply_text.assert_awaited_once_with(
            "已开启新的对话上下文。订阅和摘要记录不会受影响。"
        )

    async def test_newchat_command_requires_user(self) -> None:
        update = SimpleNamespace(
            effective_user=None,
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(args=[])

        await newchat_command(update, context)

        update.message.reply_text.assert_awaited_once_with("无法识别当前用户，请稍后再试。")


if __name__ == "__main__":
    unittest.main()
