import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from services.rss_pipeline.collectors.bilibili import collect


class _QueueClient:
    def __init__(self, *payloads: dict[str, object]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "params": params, "headers": headers})
        request = httpx.Request("GET", url, params=params, headers=headers)
        return httpx.Response(200, json=self.payloads.pop(0), request=request)


class BilibiliCollectorTest(unittest.TestCase):
    def test_weekly_selects_latest_series_and_maps_video(self) -> None:
        client = _QueueClient(
            {
                "code": 0,
                "data": [
                    {"number": 8, "subject": "第八期"},
                    {"number": "10", "subject": "第十期"},
                ],
            },
            {
                "code": 0,
                "data": {
                    "config": {"title": "每周必看"},
                    "list": [
                        {
                            "bvid": "BV1abc",
                            "title": "值得一看",
                            "right_desc_1": "UP 主",
                            "rcmd_reason": "本周热门",
                            "cover": "https://i.example/cover.jpg",
                        }
                    ],
                },
            },
        )
        source = _source("weekly", "bilibili_weekly")

        entries = collect(source, client)

        self.assertEqual(client.calls[1]["params"]["number"], 10)  # type: ignore[index]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.entry_id, "https://www.bilibili.com/video/BV1abc")
        self.assertEqual(entry.link, "https://www.bilibili.com/video/BV1abc")
        self.assertEqual(entry.summary, "第十期 · 本周热门")
        self.assertEqual(entry.author, "UP 主")
        self.assertEqual(entry.raw["source_kind"], "bilibili_weekly")
        self.assertIn("number=10", entry.raw["request_url"])

    def test_anime_timeline_reads_all_episodes_from_today(self) -> None:
        episode = {
            "episode_id": 123,
            "season_id": 99,
            "title": "示例番剧",
            "pub_index": "第 3 话",
            "pub_ts": 1_700_000_000,
            "pub_time": "10:00",
            "published": 1,
            "follows": "10 万",
            "plays": "20 万",
        }
        client = _QueueClient(
            {
                "code": 0,
                "result": [
                    {
                        "date": "8-29",
                        "is_today": 0,
                        "episodes": [{"episode_id": 999, "title": "昨天"}],
                    },
                    {
                        "date": "8-30",
                        "date_ts": 1_700_000_000,
                        "day_of_week": 7,
                        "is_today": 1,
                        "episodes": [
                            episode,
                            {**episode},
                            {
                                "episode_id": 124,
                                "title": "尚未开播",
                                "pub_index": "第 4 话",
                                "pub_time": "23:00",
                                "delay_reason": "延期一周",
                                "published": 0,
                            },
                        ],
                    },
                ],
            }
        )
        source = _source(
            "timeline",
            "bilibili_anime_timeline",
            season_type=1,
            day_before=2,
            day_after=0,
        )

        entries = collect(source, client)

        self.assertEqual(len(entries), 2)
        entry = entries[0]
        self.assertEqual(
            entry.entry_id,
            "https://www.bilibili.com/bangumi/play/ep123",
        )
        self.assertEqual(entry.title, "示例番剧 · 第 3 话")
        self.assertEqual(entry.summary, "10:00")
        self.assertEqual(
            entry.published_at,
            datetime.fromtimestamp(1_700_000_000, timezone.utc),
        )
        self.assertEqual(
            client.calls[0]["params"],
            {"types": 1, "before": 0, "after": 6},
        )
        self.assertEqual(
            client.calls[0]["url"],
            "https://api.bilibili.com/pgc/web/timeline",
        )
        self.assertEqual(entries[1].summary, "23:00 · 延期一周")
        self.assertEqual(entry.raw["source_key"], "timeline")

    def test_anime_timeline_rejects_payload_without_today_group(self) -> None:
        source = _source("timeline", "bilibili_anime_timeline")
        payload = {
            "code": 0,
            "result": [
                {"date": "8-29", "is_today": 0, "episodes": []},
            ],
        }

        with self.assertRaisesRegex(ValueError, "缺少今日分组"):
            collect(source, _QueueClient(payload))

    def test_category_rank_uses_click_order_and_filters_numeric_title(self) -> None:
        client = _QueueClient(
            {
                "code": 0,
                "data": {
                    "result": [
                        {
                            "id": 123,
                            "bvid": "BVrank",
                            "title": "番剧资讯",
                            "description": "简介",
                            "author": "作者",
                            "senddate": 1_700_000_000,
                        },
                        {"id": 124, "bvid": "BVspam", "title": " 12345 "},
                    ]
                },
            }
        )
        source = _source(
            "rank",
            "bilibili_category_rank",
            cate_id=33,
            days=7,
            page_size=20,
            order="click",
        )

        with (
            patch(
                "services.rss_pipeline.collectors.bilibili._today_in_shanghai",
                return_value=date(2026, 8, 30),
            ),
            patch(
                "services.rss_pipeline.collectors.bilibili.logger.warning"
            ) as warning,
        ):
            entries = collect(source, client)

        params = client.calls[0]["params"]
        self.assertEqual(params["cate_id"], 33)  # type: ignore[index]
        self.assertEqual(params["pagesize"], 20)  # type: ignore[index]
        self.assertEqual(params["order"], "click")  # type: ignore[index]
        self.assertEqual(params["time_from"], "20260823")  # type: ignore[index]
        self.assertEqual(params["time_to"], "20260830")  # type: ignore[index]
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0].entry_id,
            "https://www.bilibili.com/video/BVrank",
        )
        self.assertEqual(entries[0].raw["cate_id"], 33)
        warning.assert_called_once_with(
            "Bilibili 内容源 %s 的分区 %s 过滤了 %s 个纯数字标题",
            "rank",
            33,
            1,
        )

    def test_mall_new_flattens_days_without_pre_items_parameter(self) -> None:
        client = _QueueClient(
            {
                "code": 0,
                "data": {
                    "codeType": 1,
                    "vo": {
                        "cateTabs": [
                            {"cateType": 1, "cateName": "手办"},
                            {"cateType": 3, "cateName": "周边"},
                        ],
                        "days": [
                            {
                                "dayNO": 1,
                                "weekDay": "周日",
                                "presaleItems": [
                                    {
                                        "itemsId": 501,
                                        "name": "新品手办",
                                        "brief": "限定款",
                                        "priceDesc": "¥199",
                                        "itemUrlForH5": "//mall.bilibili.com/items/501",
                                    }
                                ],
                            },
                            {
                                "dayNO": 2,
                                "presaleItems": [
                                    {"itemsId": 501, "name": "重复商品"},
                                    {"itemsId": 502, "name": "第二件商品", "price": 88},
                                ],
                            },
                        ]
                    },
                },
            }
        )
        source = _source("mall", "bilibili_mall_new", category=1)

        entries = collect(source, client)

        params = client.calls[0]["params"]
        self.assertNotIn("preItemsIds", params)  # type: ignore[operator]
        self.assertEqual(params["cateType"], 1)  # type: ignore[index]
        self.assertEqual(
            [entry.entry_id for entry in entries],
            [
                "https://mall.bilibili.com/detail.html?itemsId=501",
                "https://mall.bilibili.com/detail.html?itemsId=502",
            ],
        )
        self.assertEqual(
            entries[0].link,
            "https://mall.bilibili.com/detail.html?itemsId=501",
        )
        self.assertEqual(entries[0].summary, "限定款 · ¥199")
        self.assertEqual(
            entries[0].raw["upstream_item_url"],
            "https://mall.bilibili.com/items/501",
        )
        self.assertEqual(entries[0].raw["request_url"], entries[0].feed_url)

    def test_mall_new_rejects_invalid_code_type_or_category_tab(self) -> None:
        source = _source("mall", "bilibili_mall_new", category=1)
        invalid_payloads = [
            {"code": 0, "data": {"codeType": 0, "vo": {"days": []}}},
            {
                "code": 0,
                "data": {
                    "codeType": 1,
                    "vo": {
                        "cateTabs": [{"cateType": 3, "cateName": "周边"}],
                        "days": [],
                    },
                },
            },
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    collect(source, _QueueClient(payload))

    def test_hot_search_uses_http_uri_or_search_fallback(self) -> None:
        client = _QueueClient(
            {
                "code": 0,
                "data": {
                    "trending": {
                        "title": "B站热搜",
                        "list": [
                            {
                                "keyword": "中文 热词",
                                "show_name": "中文 热词",
                                "uri": "bilibili://search",
                                "heat_score": 100,
                            },
                            {
                                "keyword": "direct",
                                "uri": "https://search.bilibili.com/all?keyword=direct",
                            },
                        ],
                    }
                },
            }
        )
        source = _source("hot", "bilibili_hot_search")

        entries = collect(source, client)

        self.assertEqual(len(entries), 2)
        self.assertIn("keyword=%E4%B8%AD%E6%96%87%20%E7%83%AD%E8%AF%8D", entries[0].link)
        self.assertEqual(
            entries[1].link,
            "https://search.bilibili.com/all?keyword=direct",
        )
        self.assertEqual(entries[0].raw["rank_position"], 1)
        self.assertEqual(entries[0].raw["source_kind"], "bilibili_hot_search")
        self.assertEqual(entries[0].entry_id, entries[0].link)
        self.assertEqual(entries[1].entry_id, entries[1].link)

    def test_rejects_unknown_kind(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持"):
            collect(_source("bad", "weekly"), _QueueClient())


def _source(source_id: str, kind: str, **options: object) -> SimpleNamespace:
    return SimpleNamespace(id=source_id, kind=kind, options=options)


if __name__ == "__main__":
    unittest.main()
