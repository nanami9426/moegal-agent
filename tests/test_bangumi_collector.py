import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from services.rss_pipeline.collectors.bangumi import _configured_timezone, collect


class _QueueClient:
    def __init__(self, *responses: dict[str, object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "params": params, "headers": headers})
        spec = self.responses.pop(0)
        request = httpx.Request("GET", url, params=params, headers=headers)
        if "json" in spec:
            return httpx.Response(200, json=spec["json"], request=request)
        return httpx.Response(
            200,
            text=str(spec.get("text", "")),
            request=request,
        )


class BangumiCollectorTest(unittest.TestCase):
    def test_calendar_today_uses_configured_timezone(self) -> None:
        client = _QueueClient(
            {
                "json": [
                    {"weekday": {"id": 1}, "items": [{"id": 1, "name": "错误日期"}]},
                    {
                        "weekday": {"id": 7, "cn": "星期日"},
                        "items": [
                            {
                                "id": 42,
                                "name": "Original Name",
                                "name_cn": "中文名",
                                "summary": "作品简介",
                                "images": {"large": "//lain.bgm.tv/pic.jpg"},
                            }
                        ],
                    },
                ]
            }
        )
        source = SimpleNamespace(
            id="bangumi-calendar",
            kind="bangumi_calendar_today",
            options={},
        )

        with (
            patch.dict("os.environ", {"MOEGAL_TIMEZONE": "America/Los_Angeles"}),
            patch(
                "services.rss_pipeline.collectors.bangumi._today_in_timezone",
                return_value=date(2026, 8, 30),
            ) as today_in_timezone,
        ):
            entries = collect(source, client)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(today_in_timezone.call_args.args[0].key, "America/Los_Angeles")
        self.assertEqual(entry.entry_id, "https://bgm.tv/subject/42#2026-08-30")
        self.assertEqual(entry.link, "https://bgm.tv/subject/42")
        self.assertEqual(entry.title, "中文名｜Original Name")
        self.assertEqual(entry.summary, "作品简介")
        self.assertEqual(
            entry.published_at,
            datetime(2026, 8, 30, 7, tzinfo=timezone.utc),
        )
        self.assertEqual(entry.raw["source_key"], "bangumi-calendar")
        self.assertEqual(entry.raw["source_kind"], "bangumi_calendar_today")
        self.assertEqual(entry.raw["request_url"], "https://api.bgm.tv/calendar")
        self.assertTrue(entry.raw["published_at_inferred"])

    def test_calendar_invalid_timezone_falls_back_to_shanghai(self) -> None:
        with patch.dict("os.environ", {"MOEGAL_TIMEZONE": "not/a-real-timezone"}):
            self.assertEqual(_configured_timezone().key, "Asia/Shanghai")

    def test_calendar_rejects_payload_without_today_group(self) -> None:
        source = SimpleNamespace(
            id="bangumi-calendar",
            kind="bangumi_calendar_today",
            options={},
        )
        with (
            patch(
                "services.rss_pipeline.collectors.bangumi._today_in_timezone",
                return_value=date(2026, 8, 30),
            ),
            self.assertRaisesRegex(ValueError, "缺少当天 weekday 分组"),
        ):
            collect(
                source,
                _QueueClient({"json": [{"weekday": {"id": 1}, "items": []}]}),
            )

    def test_trending_parses_only_featured_items(self) -> None:
        html = """
        <html><head><meta charset="utf-8"></head><body>
          <a href="/subject/999">页面其他作品</a>
          <ul class="featuredItems clearit">
            <li><div class="mainItem">
              <a href="/subject/101" title="动画 A">
                <div class="image" style="background-image:url(//lain.bgm.tv/a.jpg)"></div>
              </a>
              <p class="title"><a class="l" href="/subject/101">动画 A</a></p>
              <small class="grey">7,919 人关注</small>
            </div></li>
            <li><div class="mainItem">
              <a href="/subject/102" title="动画 B"><img src="cover.jpg"></a>
              <small class="grey">12 人关注</small>
            </div></li>
          </ul>
        </body></html>
        """
        client = _QueueClient({"text": html})
        source = SimpleNamespace(
            id="bangumi-trending",
            kind="bangumi_anime_trending",
            options={},
        )

        entries = collect(source, client)

        self.assertEqual([entry.title for entry in entries], ["动画 A", "动画 B"])
        self.assertEqual(entries[0].entry_id, "https://bgm.tv/subject/101")
        self.assertEqual(entries[0].raw["rank_position"], 1)
        self.assertEqual(entries[0].raw["follower_count"], 7919)
        self.assertEqual(entries[0].raw["cover"], "https://lain.bgm.tv/a.jpg")
        self.assertEqual(entries[1].raw["source_key"], "bangumi-trending")
        self.assertEqual(entries[1].raw["request_url"], "https://bgm.tv/anime")

    def test_trending_rejects_page_without_featured_items(self) -> None:
        source = SimpleNamespace(
            id="bangumi-trending",
            kind="bangumi_anime_trending",
            options={},
        )
        with self.assertRaisesRegex(ValueError, "缺少注目动画列表"):
            collect(source, _QueueClient({"text": "<html><body>验证页</body></html>"}))

    def test_rejects_unknown_kind(self) -> None:
        source = SimpleNamespace(id="bad", kind="calendar_today", options={})
        with self.assertRaisesRegex(ValueError, "不支持"):
            collect(source, _QueueClient())


if __name__ == "__main__":
    unittest.main()
