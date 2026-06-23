import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bots.tg.handlers import (
    PENDING_COMIC_PHOTO_KEY,
    PENDING_TRANSLATE_PHOTO_KEY,
    handel_receive_picture,
    handle_text,
    newchat_command,
    translate_command,
    unsubscribe_command,
)
from services.image_workflow import PendingImage


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        username="tester",
        first_name="Test",
        last_name=None,
        language_code="zh",
    )


def _translated_image_result(image_bytes: bytes = b"translated-image"):
    return (
        ["原文"],
        ["译文"],
        (base64.b64encode(image_bytes).decode("utf8"), "translated.png"),
    )


def _build_photo_update(raw_image: bytes = b"raw-image", caption: str | None = None):
    class FakeTelegramFile:
        async def download_to_drive(self, path: Path) -> None:
            path.write_bytes(raw_image)

        async def download_as_bytearray(self) -> bytearray:
            return bytearray(raw_image)

    user = _user()
    photo = SimpleNamespace(
        file_unique_id="photo-1",
        get_file=AsyncMock(return_value=FakeTelegramFile()),
    )
    message = SimpleNamespace(
        photo=[photo],
        from_user=user,
        caption=caption,
        reply_text=AsyncMock(),
        reply_photo=AsyncMock(),
        reply_document=AsyncMock(),
    )
    return SimpleNamespace(message=message, effective_user=user), message


def _build_text_update(text: str):
    user = _user()
    message = SimpleNamespace(
        text=text,
        reply_text=AsyncMock(),
        reply_photo=AsyncMock(),
        reply_document=AsyncMock(),
    )
    return SimpleNamespace(message=message, effective_user=user), message


class TelegramHandlersTest(unittest.IsolatedAsyncioTestCase):
    async def test_translate_command_prompts_for_picture(self) -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={PENDING_COMIC_PHOTO_KEY: {"file_bytes": b"old"}})

        await translate_command(update, context)

        self.assertTrue(context.user_data[PENDING_TRANSLATE_PHOTO_KEY])
        self.assertNotIn(PENDING_COMIC_PHOTO_KEY, context.user_data)
        update.message.reply_text.assert_awaited_once_with("请发送要翻译的图片。")

    async def test_handel_receive_picture_translates_after_translate_command(self) -> None:
        raw_image = b"raw-image"
        update, message = _build_photo_update(raw_image)
        context = SimpleNamespace(user_data={PENDING_TRANSLATE_PHOTO_KEY: True})

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("bots.tg.handlers.TG_SAVED_PICTURES_DIR", Path(tmpdir)),
            patch("services.image_workflow.is_manga_image_bytes") as is_manga_image_bytes_mock,
            patch(
                "services.image_workflow.translate_image_bytes",
                AsyncMock(return_value=_translated_image_result()),
            ) as translate_image_bytes_mock,
        ):
            await handel_receive_picture(update, context)

        self.assertNotIn(PENDING_TRANSLATE_PHOTO_KEY, context.user_data)
        is_manga_image_bytes_mock.assert_not_called()
        translate_image_bytes_mock.assert_awaited_once_with(raw_image, include_res_img=True)
        message.reply_text.assert_not_awaited()
        message.reply_photo.assert_awaited_once()
        sent_photo = message.reply_photo.await_args.kwargs["photo"]
        self.assertEqual(sent_photo.getvalue(), b"translated-image")
        self.assertEqual(sent_photo.name, "translated.png")
        self.assertEqual(message.reply_photo.await_args.kwargs["caption"], "翻译后的图片")
        message.reply_document.assert_awaited_once()
        sent_document = message.reply_document.await_args.kwargs["document"]
        self.assertEqual(sent_document.getvalue(), b"translated-image")
        self.assertEqual(sent_document.tell(), 0)
        self.assertEqual(sent_document.name, "translated.png")
        self.assertEqual(message.reply_document.await_args.kwargs["caption"], "翻译后的图片")

    async def test_handel_receive_picture_answers_non_manga_image(self) -> None:
        raw_image = b"raw-image"
        update, message = _build_photo_update(raw_image)
        context = SimpleNamespace(user_data={})

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("bots.tg.handlers.TG_SAVED_PICTURES_DIR", Path(tmpdir)),
            patch("services.image_workflow.is_manga_image_bytes", return_value=False) as is_manga_image_bytes_mock,
            patch(
                "services.image_workflow.route_image_message",
                AsyncMock(return_value="图片回答"),
            ) as route_image_message_mock,
        ):
            await handel_receive_picture(update, context)

        is_manga_image_bytes_mock.assert_called_once_with(raw_image)
        route_image_message_mock.assert_awaited_once()
        self.assertEqual(route_image_message_mock.await_args.args[:3], ("tg", "42", raw_image))
        message.reply_text.assert_awaited_once_with("图片回答")
        message.reply_photo.assert_not_awaited()
        message.reply_document.assert_not_awaited()

    async def test_handel_receive_picture_asks_before_translating_manga_image(self) -> None:
        raw_image = b"raw-image"
        update, message = _build_photo_update(raw_image, caption="这张图讲什么")
        context = SimpleNamespace(user_data={})

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("bots.tg.handlers.TG_SAVED_PICTURES_DIR", Path(tmpdir)),
            patch("services.image_workflow.is_manga_image_bytes", return_value=True),
            patch(
                "services.image_workflow.classify_image_translation_intent",
                AsyncMock(return_value="unknown"),
            ) as classify_intent_mock,
            patch("services.image_workflow.translate_image_bytes", AsyncMock()) as translate_image_bytes_mock,
            patch("services.image_workflow.route_image_message", AsyncMock()) as route_image_message_mock,
        ):
            await handel_receive_picture(update, context)

        self.assertEqual(
            context.user_data[PENDING_COMIC_PHOTO_KEY],
            PendingImage(file_bytes=raw_image, caption="这张图讲什么"),
        )
        classify_intent_mock.assert_awaited_once_with("这张图讲什么")
        message.reply_text.assert_awaited_once_with("这张图需要我帮你翻译吗？")
        translate_image_bytes_mock.assert_not_awaited()
        route_image_message_mock.assert_not_awaited()

    async def test_handle_text_translates_pending_manga_image(self) -> None:
        raw_image = b"raw-image"
        update, message = _build_text_update("翻译")
        context = SimpleNamespace(
            user_data={PENDING_COMIC_PHOTO_KEY: PendingImage(file_bytes=raw_image, caption="")}
        )

        with patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(return_value="translate"),
        ) as classify_intent_mock, patch(
            "services.image_workflow.translate_image_bytes",
            AsyncMock(return_value=_translated_image_result()),
        ) as translate_image_bytes_mock:
            await handle_text(update, context)

        self.assertNotIn(PENDING_COMIC_PHOTO_KEY, context.user_data)
        classify_intent_mock.assert_awaited_once_with("翻译")
        translate_image_bytes_mock.assert_awaited_once_with(raw_image, include_res_img=True)
        message.reply_text.assert_not_awaited()
        message.reply_photo.assert_awaited_once()
        message.reply_document.assert_awaited_once()

    async def test_handle_text_answers_pending_manga_image_when_llm_detects_skip(self) -> None:
        raw_image = b"raw-image"
        update, message = _build_text_update("不用翻译了啊")
        context = SimpleNamespace(
            user_data={PENDING_COMIC_PHOTO_KEY: PendingImage(file_bytes=raw_image, caption="讲讲画面")}
        )

        with patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(return_value="skip"),
        ) as classify_intent_mock, patch(
            "services.image_workflow.route_image_message",
            AsyncMock(return_value="视觉回答"),
        ) as route_image_message_mock:
            await handle_text(update, context)

        self.assertNotIn(PENDING_COMIC_PHOTO_KEY, context.user_data)
        classify_intent_mock.assert_awaited_once_with("不用翻译了啊")
        route_image_message_mock.assert_awaited_once()
        self.assertEqual(route_image_message_mock.await_args.args[:3], ("tg", "42", raw_image))
        self.assertEqual(route_image_message_mock.await_args.kwargs["prompt"], "讲讲画面")
        message.reply_text.assert_awaited_once_with("视觉回答")

    async def test_handle_text_asks_intent_again_when_llm_is_unsure(self) -> None:
        raw_image = b"raw-image"
        update, message = _build_text_update("等一下")
        context = SimpleNamespace(
            user_data={PENDING_COMIC_PHOTO_KEY: PendingImage(file_bytes=raw_image, caption="")}
        )

        with (
            patch(
                "services.image_workflow.classify_image_translation_intent",
                AsyncMock(return_value="unknown"),
            ) as classify_intent_mock,
            patch("services.image_workflow.translate_image_bytes", AsyncMock()) as translate_image_bytes_mock,
            patch("services.image_workflow.route_image_message", AsyncMock()) as route_image_message_mock,
        ):
            await handle_text(update, context)

        self.assertIn(PENDING_COMIC_PHOTO_KEY, context.user_data)
        classify_intent_mock.assert_awaited_once_with("等一下")
        message.reply_text.assert_awaited_once_with("这张图需要我帮你翻译吗？")
        translate_image_bytes_mock.assert_not_awaited()
        route_image_message_mock.assert_not_awaited()

    async def test_handle_text_routes_text_without_image_context_directly_to_agent(self) -> None:
        update, message = _build_text_update("我想翻译图片")
        context = SimpleNamespace(user_data={})

        with patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(),
        ) as classify_intent_mock, patch(
            "bots.tg.handlers.route_message",
            AsyncMock(return_value="普通回复"),
        ) as route_message_mock:
            await handle_text(update, context)

        self.assertNotIn(PENDING_TRANSLATE_PHOTO_KEY, context.user_data)
        classify_intent_mock.assert_not_awaited()
        route_message_mock.assert_awaited_once()
        self.assertEqual(route_message_mock.await_args.args[:3], ("tg", "42", "我想翻译图片"))
        message.reply_text.assert_awaited_once_with("普通回复")

    async def test_handel_receive_picture_translates_when_caption_requests_translation(self) -> None:
        raw_image = b"raw-image"
        update, message = _build_photo_update(raw_image, caption="帮我翻译")
        context = SimpleNamespace(user_data={})

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("bots.tg.handlers.TG_SAVED_PICTURES_DIR", Path(tmpdir)),
            patch("services.image_workflow.is_manga_image_bytes") as is_manga_image_bytes_mock,
            patch(
                "services.image_workflow.classify_image_translation_intent",
                AsyncMock(return_value="translate"),
            ) as classify_intent_mock,
            patch(
                "services.image_workflow.translate_image_bytes",
                AsyncMock(return_value=_translated_image_result()),
            ) as translate_image_bytes_mock,
        ):
            await handel_receive_picture(update, context)

        classify_intent_mock.assert_awaited_once_with("帮我翻译")
        is_manga_image_bytes_mock.assert_not_called()
        translate_image_bytes_mock.assert_awaited_once_with(raw_image, include_res_img=True)
        message.reply_photo.assert_awaited_once()
        message.reply_document.assert_awaited_once()

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
            return_value="00000000-0000-4000-8000-000000000001",
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
