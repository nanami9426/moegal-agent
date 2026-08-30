import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from services.rss_pipeline.collectors.arknights import MAX_PAGES, collect


@dataclass(frozen=True)
class _Source:
    id: str
    kind: str
    options: dict[str, Any]


class ArknightsCollectorTest(unittest.TestCase):
    def test_collect_paginates_to_end_maps_fields_and_deduplicates(self) -> None:
        requested_pages: list[int] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["page"])
            requested_pages.append(page)
            common_item = {
                "cid": "0793",
                "tab": "0",
                "sticky": False,
                "title": "  服务器\n维护公告  ",
                "author": "【明日方舟】运营组",
                "displayTime": 1_700_000_000,
                "cover": "",
                "extraCover": "https://example.com/cover.jpg",
                "brief": "  维护期间\n无法登录  ",
            }
            if page == 1:
                items = [common_item]
                end = False
            else:
                items = [
                    common_item,
                    {
                        "cid": "9681",
                        "tab": "1",
                        "sticky": True,
                        "title": "活动预告",
                        "author": "【明日方舟】运营组",
                        "displayTime": 1_700_000_100,
                        "cover": "https://example.com/activity.jpg",
                        "extraCover": "",
                        "brief": "活动即将开始",
                    },
                ]
                end = True
            return httpx.Response(
                200,
                request=request,
                json={"code": 0, "data": {"list": items, "total": 3, "end": end}},
            )

        source = _Source(id="arknights", kind="arknights_news", options={})
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            entries = collect(source, client)

        self.assertEqual(requested_pages, [1, 2])
        self.assertEqual(
            [entry.entry_id for entry in entries],
            [
                "https://ak.hypergryph.com/news/0793",
                "https://ak.hypergryph.com/news/9681",
            ],
        )

        first = entries[0]
        self.assertEqual(first.link, "https://ak.hypergryph.com/news/0793")
        self.assertEqual(first.title, "服务器 维护公告")
        self.assertEqual(first.summary, "维护期间 无法登录")
        self.assertEqual(first.author, "【明日方舟】运营组")
        self.assertEqual(
            first.published_at,
            datetime.fromtimestamp(1_700_000_000, timezone.utc),
        )
        self.assertEqual(first.raw["source_key"], source.id)
        self.assertEqual(first.raw["source_kind"], source.kind)
        self.assertEqual(first.raw["category"], "公告")
        self.assertEqual(first.raw["page"], 1)
        self.assertIn("category=LATEST", first.raw["request_url"])
        self.assertIn("page=1", first.raw["request_url"])

        second = entries[1]
        self.assertEqual(second.raw["category"], "活动")
        self.assertTrue(second.raw["sticky"])
        self.assertIn("page=2", second.raw["request_url"])

    def test_collect_stops_after_ten_pages_when_end_is_false(self) -> None:
        requested_pages: list[int] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["page"])
            requested_pages.append(page)
            return httpx.Response(
                200,
                request=request,
                json={
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "cid": str(page),
                                "tab": "2",
                                "title": f"新闻 {page}",
                                "author": "制作组",
                                "displayTime": 1_700_000_000 + page,
                                "brief": "摘要",
                                "cover": "",
                                "extraCover": "",
                                "sticky": False,
                            }
                        ],
                        "total": 100,
                        "end": False,
                    },
                },
            )

        source = _Source(id="arknights", kind="arknights_news", options={})
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            entries = collect(source, client)

        self.assertEqual(requested_pages, list(range(1, MAX_PAGES + 1)))
        self.assertEqual(len(entries), MAX_PAGES)

    def test_collect_rejects_api_business_error(self) -> None:
        def handle_request(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                request=request,
                json={"code": 500, "msg": "temporary error"},
            )

        source = _Source(id="arknights", kind="arknights_news", options={})
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            with self.assertRaisesRegex(ValueError, "code=500"):
                collect(source, client)


if __name__ == "__main__":
    unittest.main()
