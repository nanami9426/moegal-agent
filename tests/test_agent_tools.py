import unittest
from unittest.mock import patch

from agent.tools import TOOLS, get_weather


WEATHER_PARAMS = {
    "format": "%l: %C %t, 体感%f, 湿度%h, 风%w, 降水%p, 紫外线%u",
    "lang": "zh",
}


class AgentToolsTest(unittest.TestCase):
    def test_get_weather_fetches_wttr_weather(self) -> None:
        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            self.assertEqual(url, "https://wttr.in/Shenzhen")
            self.assertEqual(kwargs["params"], WEATHER_PARAMS)
            self.assertEqual(kwargs["timeout"], 8.0)
            self.assertTrue(kwargs["follow_redirects"])
            return _FakeResponse("Shenzhen: Rain +29C")

        with patch("agent.tools.httpx.get", side_effect=fake_get):
            result = get_weather.invoke({"location": "  Shenzhen  "})

        self.assertEqual(result, "Shenzhen: Rain +29C")

    def test_get_weather_defaults_to_shenzhen(self) -> None:
        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            self.assertEqual(url, "https://wttr.in/Shenzhen")
            self.assertEqual(kwargs["params"], WEATHER_PARAMS)
            return _FakeResponse("Shenzhen: Rain +29C")

        with patch("agent.tools.httpx.get", side_effect=fake_get):
            result = get_weather.invoke({"location": ""})

        self.assertEqual(result, "Shenzhen: Rain +29C")

    def test_weather_tool_is_registered(self) -> None:
        self.assertIn("get_weather", [tool.name for tool in TOOLS])

    def test_memory_tools_are_registered(self) -> None:
        tool_names = [tool.name for tool in TOOLS]

        self.assertIn("remember_user_memory", tool_names)
        self.assertIn("forget_user_memory", tool_names)
        self.assertIn("list_user_memories", tool_names)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
