import os
import unittest
from unittest.mock import patch

from utils.llm import get_base_url, llm_user_headers


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

    def test_llm_user_headers_sets_x_user_id(self) -> None:
        self.assertEqual(llm_user_headers(1_000_000_001), {"X-User-ID": "1000000001"})

    def test_llm_user_headers_requires_user_id(self) -> None:
        with self.assertRaises(ValueError):
            llm_user_headers(None)


if __name__ == "__main__":
    unittest.main()
