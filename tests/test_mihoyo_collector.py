import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from services.rss_pipeline.collectors.mihoyo import collect


@dataclass(frozen=True)
class _Source:
    id: str
    kind: str
    options: dict[str, Any]


class MihoyoCollectorTest(unittest.TestCase):
    def test_collect_maps_all_configured_game_and_news_type_combinations(self) -> None:
        requests: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            gids = request.url.params["gids"]
            news_type = request.url.params["type"]
            post_id = f"{gids}{news_type}001"
            return httpx.Response(
                200,
                request=request,
                json={
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "list": [
                            {
                                "post": {
                                    "post_id": post_id,
                                    "subject": "  测试\n标题  ",
                                    "created_at": 1_700_000_000,
                                    "cover": "https://example.com/cover.png",
                                    "images": ["https://example.com/image.png"],
                                },
                                "news_meta": {"activity_status": 1},
                            }
                        ],
                        "last_id": 1,
                        "is_last": False,
                    },
                },
            )

        cases = [
            (2, 1, "ys", "原神官方公告"),
            (2, 2, "ys", "原神官方活动"),
            (6, 1, "sr", "崩坏：星穹铁道官方公告"),
            (6, 2, "sr", "崩坏：星穹铁道官方活动"),
            (8, 1, "zzz", "绝区零官方公告"),
            (8, 2, "zzz", "绝区零官方活动"),
        ]

        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            for gids, news_type, slug, feed_title in cases:
                with self.subTest(gids=gids, news_type=news_type):
                    source = _Source(
                        id=f"mihoyo-{gids}-{news_type}",
                        kind="mihoyo_official",
                        options={
                            "gids": gids,
                            "news_type": news_type,
                            "page_size": 20,
                        },
                    )
                    entries = collect(source, client)

                    self.assertEqual(len(entries), 1)
                    entry = entries[0]
                    post_id = f"{gids}{news_type}001"
                    self.assertEqual(
                        entry.entry_id,
                        f"https://www.miyoushe.com/{slug}/article/{post_id}",
                    )
                    self.assertEqual(
                        entry.link,
                        f"https://www.miyoushe.com/{slug}/article/{post_id}",
                    )
                    self.assertEqual(entry.feed_title, feed_title)
                    self.assertEqual(entry.title, "测试 标题")
                    self.assertIsNone(entry.summary)
                    self.assertEqual(
                        entry.published_at,
                        datetime.fromtimestamp(1_700_000_000, timezone.utc),
                    )
                    self.assertEqual(entry.raw["source_key"], source.id)
                    self.assertEqual(entry.raw["source_kind"], source.kind)
                    self.assertIn("page_size=20", entry.raw["request_url"])

        # 每个配置实例只调用一次列表接口，不会逐条请求帖子详情。
        self.assertEqual(len(requests), 6)
        for request in requests:
            self.assertEqual(request.url.path, "/post/api/getNewsList")
            self.assertEqual(request.headers["referer"], "https://www.miyoushe.com/")

    def test_collect_rejects_unsupported_options_before_request(self) -> None:
        def handle_request(request: httpx.Request) -> httpx.Response:
            self.fail(f"不应发起请求: {request.url}")

        source = _Source(
            id="mihoyo-invalid",
            kind="mihoyo_official",
            options={"gids": 99, "news_type": 1, "page_size": 20},
        )
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            with self.assertRaisesRegex(ValueError, "gids 不受支持"):
                collect(source, client)

    def test_collect_rejects_api_business_error(self) -> None:
        def handle_request(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                request=request,
                json={"retcode": 1001, "message": "未指定类型", "data": None},
            )

        source = _Source(
            id="mihoyo-error",
            kind="mihoyo_official",
            options={"gids": 2, "news_type": 1},
        )
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            with self.assertRaisesRegex(ValueError, "retcode=1001"):
                collect(source, client)


if __name__ == "__main__":
    unittest.main()
