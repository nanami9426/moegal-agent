import os
import unittest
from unittest.mock import patch

from utils.llm import get_base_url


class LLMUtilsTest(unittest.TestCase):
    def test_get_base_url_prefers_gateway_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "MOEGAL_LLM_GATEWAY_BASE_URL": "http://127.0.0.1:9426/v1",
            },
        ):
            self.assertEqual(get_base_url(), "http://127.0.0.1:9426/v1")

    def test_get_base_url_falls_back_to_openai_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
            clear=True,
        ):
            self.assertEqual(get_base_url(), "https://dashscope.aliyuncs.com/compatible-mode/v1")


if __name__ == "__main__":
    unittest.main()
