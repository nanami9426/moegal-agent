import base64
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bots.qq.app import QQClient
from services.image_workflow import PendingImage


def _translated_image_result(image_bytes: bytes = b"translated-image"):
    return (
        ["原文"],
        ["译文"],
        (base64.b64encode(image_bytes).decode("utf8"), "translated.png"),
    )


def _attachment() -> SimpleNamespace:
    return SimpleNamespace(
        content_type="image/png",
        filename="raw.png",
        url="https://example.com/raw.png",
    )


def _message(content: str = "", attachments: list[SimpleNamespace] | None = None):
    return SimpleNamespace(
        author=SimpleNamespace(user_openid="openid-1"),
        content=content,
        id="msg-1",
        attachments=attachments or [],
        reply=AsyncMock(),
    )


def _client() -> QQClient:
    client = QQClient.__new__(QQClient)
    client.api = SimpleNamespace(post_c2c_file=AsyncMock(return_value={"file_info": "media"}))
    return client


def _remote_upload_env(base_url: str = "https://static.example.com/moegal-qq") -> dict[str, str]:
    return {
        "MOEGAL_PUBLIC_ASSET_BASE_URL": base_url,
        "MOEGAL_QQ_IMAGE_REMOTE_HOST": "example.com",
        "MOEGAL_QQ_IMAGE_REMOTE_USER": "deploy",
        "MOEGAL_QQ_IMAGE_REMOTE_PASSWORD": "secret",
        "MOEGAL_QQ_IMAGE_REMOTE_DIR": "/path/to/nginx/html/moegal-qq/image",
    }


class QQClientTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.upsert_user_patcher = patch(
            "services.image_workflow.upsert_user",
            return_value=SimpleNamespace(id=1_000_000_001),
        )
        self.upsert_user_patcher.start()

    def tearDown(self) -> None:
        self.upsert_user_patcher.stop()

    async def test_c2c_message_replies_once_with_original_message(self) -> None:
        client = _client()
        message = _message("  你好  ")

        with patch(
            "bots.qq.app.route_message",
            AsyncMock(return_value="测试回复：你好"),
        ) as route_message_mock:
            await client.on_c2c_message_create(message)

        route_message_mock.assert_awaited_once_with("qq", "openid-1", "你好")
        message.reply.assert_awaited_once_with(msg_type=0, content="测试回复：你好")

    async def test_newchat_command_starts_new_context(self) -> None:
        client = _client()
        message = _message("/newchat")

        with (
            patch(
                "bots.qq.app.start_new_conversation_context",
                return_value=SimpleNamespace(created=True),
            ) as start_new_context_mock,
            patch("bots.qq.app.route_message", AsyncMock()) as route_message_mock,
        ):
            await client.on_c2c_message_create(message)

        start_new_context_mock.assert_called_once_with("qq", "openid-1")
        route_message_mock.assert_not_awaited()
        message.reply.assert_awaited_once_with(
            msg_type=0,
            content="已开启新的对话上下文。订阅和摘要记录不会受影响。",
        )

    async def test_newchat_command_reports_already_in_new_chat(self) -> None:
        client = _client()
        message = _message("/newchat")

        with (
            patch(
                "bots.qq.app.start_new_conversation_context",
                return_value=SimpleNamespace(created=False),
            ),
            patch("bots.qq.app.route_message", AsyncMock()) as route_message_mock,
        ):
            await client.on_c2c_message_create(message)

        route_message_mock.assert_not_awaited()
        message.reply.assert_awaited_once_with(msg_type=0, content="已在新对话中。")

    async def test_link_command_completes_platform_binding(self) -> None:
        client = _client()
        message = _message("/link ABCD1234")

        with (
            patch(
                "bots.qq.app.complete_platform_link",
                return_value=SimpleNamespace(already_bound=False),
            ) as complete_link_mock,
            patch("bots.qq.app.route_message", AsyncMock()) as route_message_mock,
        ):
            await client.on_c2c_message_create(message)

        complete_link_mock.assert_called_once_with(
            platform="qq",
            platform_user_id="openid-1",
            code="ABCD1234",
        )
        route_message_mock.assert_not_awaited()
        message.reply.assert_awaited_once_with(
            msg_type=0,
            content="绑定成功。现在可以在 Web 管理后台查看该 QQ 账号的数据。",
        )

    async def test_link_command_requires_code(self) -> None:
        client = _client()
        message = _message("/link")

        with patch("bots.qq.app.route_message", AsyncMock()) as route_message_mock:
            await client.on_c2c_message_create(message)

        route_message_mock.assert_not_awaited()
        message.reply.assert_awaited_once_with(msg_type=0, content="用法：/link 绑定码")

    async def test_c2c_image_answers_non_manga_image(self) -> None:
        client = _client()
        message = _message("这是什么", [_attachment()])
        raw_image = b"raw-image"

        with (
            patch("bots.qq.app._download_image_attachment", AsyncMock(return_value=raw_image)),
            patch(
                "services.image_workflow.classify_image_translation_intent",
                AsyncMock(return_value="unknown"),
            ),
            patch("services.image_workflow.is_manga_image_bytes", return_value=False) as is_manga_mock,
            patch(
                "services.image_workflow.route_image_message",
                AsyncMock(return_value="图片回答"),
            ) as route_image_message_mock,
        ):
            await client.on_c2c_message_create(message)

        is_manga_mock.assert_called_once_with(raw_image)
        route_image_message_mock.assert_awaited_once()
        self.assertEqual(route_image_message_mock.await_args.args[:3], ("qq", "openid-1", raw_image))
        self.assertEqual(route_image_message_mock.await_args.kwargs["prompt"], "这是什么")
        self.assertEqual(route_image_message_mock.await_args.kwargs["user_id"], 1_000_000_001)
        message.reply.assert_awaited_once_with(msg_type=0, content="图片回答")

    async def test_translate_command_translates_next_image(self) -> None:
        client = _client()
        command_message = _message("/translate")
        image_message = _message("", [_attachment()])
        raw_image = b"raw-image"

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            _remote_upload_env(),
        ), patch("bots.qq.app.QQ_TRANSLATED_IMAGES_DIR", Path(tmpdir)), patch(
            "bots.qq.app._download_image_attachment",
            AsyncMock(return_value=raw_image),
        ), patch(
            "services.image_workflow.is_manga_image_bytes"
        ) as is_manga_mock, patch(
            "bots.qq.app.uuid.uuid4", return_value=type("U", (), {"hex": "uuid"})(),
        ), patch(
            "services.image_workflow.translate_image_bytes",
            AsyncMock(return_value=_translated_image_result()),
        ) as translate_image_bytes_mock, patch(
            "bots.qq.app._upload_translated_image_to_remote"
        ) as upload_mock:
            await client.on_c2c_message_create(command_message)
            await client.on_c2c_message_create(image_message)

        command_message.reply.assert_awaited_once_with(msg_type=0, content="请发送要翻译的图片。")
        is_manga_mock.assert_not_called()
        translate_image_bytes_mock.assert_awaited_once_with(
            raw_image,
            include_res_img=True,
            user_id=1_000_000_001,
        )
        upload_mock.assert_called_once_with("translated_uuid.png", b"translated-image")
        client.api.post_c2c_file.assert_awaited_once_with(
            "openid-1",
            file_type=1,
            url="https://static.example.com/moegal-qq/image/translated_uuid.png",
            srv_send_msg=False,
        )
        image_message.reply.assert_awaited_once_with(msg_type=7, media={"file_info": "media"})

    async def test_c2c_image_translates_when_caption_requests_translation(self) -> None:
        client = _client()
        message = _message("帮我翻译", [_attachment()])
        raw_image = b"raw-image"

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            _remote_upload_env(),
        ), patch("bots.qq.app.QQ_TRANSLATED_IMAGES_DIR", Path(tmpdir)), patch(
            "bots.qq.app._download_image_attachment",
            AsyncMock(return_value=raw_image),
        ), patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(return_value="translate"),
        ) as classify_intent_mock, patch(
            "services.image_workflow.is_manga_image_bytes"
        ) as is_manga_mock, patch(
            "bots.qq.app.uuid.uuid4", return_value=type("U", (), {"hex": "uuid"})(),
        ), patch(
            "services.image_workflow.translate_image_bytes",
            AsyncMock(return_value=_translated_image_result()),
        ) as translate_image_bytes_mock, patch(
            "bots.qq.app._upload_translated_image_to_remote"
        ) as upload_mock:
            await client.on_c2c_message_create(message)

        classify_intent_mock.assert_awaited_once_with("帮我翻译", user_id=1_000_000_001)
        is_manga_mock.assert_not_called()
        translate_image_bytes_mock.assert_awaited_once_with(
            raw_image,
            include_res_img=True,
            user_id=1_000_000_001,
        )
        upload_mock.assert_called_once_with("translated_uuid.png", b"translated-image")
        message.reply.assert_awaited_once_with(msg_type=7, media={"file_info": "media"})

    async def test_c2c_manga_image_saves_pending_then_translates_text_reply(self) -> None:
        client = _client()
        image_message = _message("这张图讲什么", [_attachment()])
        text_message = _message("翻译")
        raw_image = b"raw-image"

        with (
            patch("bots.qq.app._download_image_attachment", AsyncMock(return_value=raw_image)),
            patch("services.image_workflow.is_manga_image_bytes", return_value=True),
            patch(
                "services.image_workflow.classify_image_translation_intent",
                AsyncMock(return_value="unknown"),
            ) as classify_intent_mock,
            patch("services.image_workflow.translate_image_bytes", AsyncMock()) as translate_mock,
        ):
            await client.on_c2c_message_create(image_message)

        self.assertEqual(
            client._pending_comic_images["openid-1"],
            PendingImage(file_bytes=raw_image, caption="这张图讲什么"),
        )
        classify_intent_mock.assert_awaited_once_with("这张图讲什么", user_id=1_000_000_001)
        translate_mock.assert_not_awaited()
        image_message.reply.assert_awaited_once_with(msg_type=0, content="这张图需要我帮你翻译吗？")

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            _remote_upload_env(),
        ), patch("bots.qq.app.QQ_TRANSLATED_IMAGES_DIR", Path(tmpdir)), patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(return_value="translate"),
        ), patch(
            "bots.qq.app.uuid.uuid4", return_value=type("U", (), {"hex": "uuid"})(),
        ), patch(
            "services.image_workflow.translate_image_bytes",
            AsyncMock(return_value=_translated_image_result()),
        ) as translate_image_bytes_mock, patch(
            "bots.qq.app._upload_translated_image_to_remote"
        ) as upload_mock:
            await client.on_c2c_message_create(text_message)

        self.assertNotIn("openid-1", client._pending_comic_images)
        translate_image_bytes_mock.assert_awaited_once_with(
            raw_image,
            include_res_img=True,
            user_id=1_000_000_001,
        )
        upload_mock.assert_called_once_with("translated_uuid.png", b"translated-image")
        text_message.reply.assert_awaited_once_with(msg_type=7, media={"file_info": "media"})

    async def test_c2c_pending_manga_skip_answers_image(self) -> None:
        client = _client()
        client._pending_comic_images = {
            "openid-1": PendingImage(file_bytes=b"raw-image", caption="讲讲画面")
        }
        client._pending_translate_users = set()
        message = _message("不用翻译了啊")

        with patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(return_value="skip"),
        ) as classify_intent_mock, patch(
            "services.image_workflow.route_image_message",
            AsyncMock(return_value="视觉回答"),
        ) as route_image_message_mock:
            await client.on_c2c_message_create(message)

        self.assertNotIn("openid-1", client._pending_comic_images)
        classify_intent_mock.assert_awaited_once_with("不用翻译了啊", user_id=1_000_000_001)
        route_image_message_mock.assert_awaited_once()
        self.assertEqual(route_image_message_mock.await_args.args[:3], ("qq", "openid-1", b"raw-image"))
        self.assertEqual(route_image_message_mock.await_args.kwargs["prompt"], "讲讲画面")
        self.assertEqual(route_image_message_mock.await_args.kwargs["user_id"], 1_000_000_001)
        message.reply.assert_awaited_once_with(msg_type=0, content="视觉回答")

    async def test_c2c_image_download_failure_replies_text_error(self) -> None:
        client = _client()
        message = _message("", [_attachment()])

        with patch(
            "bots.qq.app._download_image_attachment",
            AsyncMock(side_effect=RuntimeError("download failed")),
        ):
            await client.on_c2c_message_create(message)

        message.reply.assert_awaited_once_with(msg_type=0, content="图片下载失败，请稍后再试。")

    async def test_c2c_translated_image_without_public_url_replies_config_error(self) -> None:
        client = _client()
        message = _message("帮我翻译", [_attachment()])

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {},
            clear=True,
        ), patch("bots.qq.app.QQ_TRANSLATED_IMAGES_DIR", Path(tmpdir)), patch(
            "bots.qq.app._download_image_attachment",
            AsyncMock(return_value=b"raw-image"),
        ), patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(return_value="translate"),
        ), patch(
            "bots.qq.app.uuid.uuid4", return_value=type("U", (), {"hex": "uuid"})(),
        ), patch(
            "services.image_workflow.translate_image_bytes",
            AsyncMock(return_value=_translated_image_result()),
        ):
            await client.on_c2c_message_create(message)

        client.api.post_c2c_file.assert_not_awaited()
        message.reply.assert_awaited_once_with(
            msg_type=0,
            content="翻译后的图片已生成，但发送失败，请检查公开图片地址配置。",
        )

    async def test_c2c_translated_image_media_send_failure_replies_config_error(self) -> None:
        client = _client()
        client.api.post_c2c_file = AsyncMock(side_effect=RuntimeError("send failed"))
        message = _message("帮我翻译", [_attachment()])

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            _remote_upload_env(),
        ), patch("bots.qq.app.QQ_TRANSLATED_IMAGES_DIR", Path(tmpdir)), patch(
            "bots.qq.app._download_image_attachment",
            AsyncMock(return_value=b"raw-image"),
        ), patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(return_value="translate"),
        ), patch(
            "bots.qq.app.uuid.uuid4", return_value=type("U", (), {"hex": "uuid"})(),
        ), patch(
            "services.image_workflow.translate_image_bytes",
            AsyncMock(return_value=_translated_image_result()),
        ), patch("bots.qq.app._upload_translated_image_to_remote"):
            await client.on_c2c_message_create(message)

        message.reply.assert_awaited_once_with(
            msg_type=0,
            content="翻译后的图片已生成，但发送失败，请检查公开图片地址配置。",
        )

    async def test_c2c_translated_image_uploads_remote_when_configured(self) -> None:
        client = _client()
        message = _message("帮我翻译", [_attachment()])

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            _remote_upload_env("https://static.example.com/moegal-qq"),
        ), patch("bots.qq.app.QQ_TRANSLATED_IMAGES_DIR", Path(tmpdir)), patch(
            "bots.qq.app._download_image_attachment",
            AsyncMock(return_value=b"raw-image"),
        ), patch(
            "services.image_workflow.classify_image_translation_intent",
            AsyncMock(return_value="translate"),
        ), patch(
            "bots.qq.app.uuid.uuid4", return_value=type("U", (), {"hex": "uuid"})(),
        ), patch(
            "services.image_workflow.translate_image_bytes",
            AsyncMock(return_value=_translated_image_result()),
        ), patch("bots.qq.app._upload_translated_image_to_remote") as upload_mock:
            await client.on_c2c_message_create(message)

        upload_mock.assert_called_once_with("translated_uuid.png", b"translated-image")
        client.api.post_c2c_file.assert_awaited_once_with(
            "openid-1",
            file_type=1,
            url="https://static.example.com/moegal-qq/image/translated_uuid.png",
            srv_send_msg=False,
        )
        message.reply.assert_awaited_once_with(msg_type=7, media={"file_info": "media"})


if __name__ == "__main__":
    unittest.main()
