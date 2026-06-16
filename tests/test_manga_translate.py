import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import torch

from services.manga_translate.ocr import TEXT_BUBBLE_CONFIDENCE, TextBubbleDetector
from services.manga_translate import translate


class MangaTranslateTest(unittest.IsolatedAsyncioTestCase):
    def test_text_bubble_detector_filters_text_bubbles_at_configured_confidence(self) -> None:
        class FakeProcessor:
            def __call__(self, **kwargs):
                return {}

            def post_process_object_detection(self, outputs, target_sizes, threshold):
                self.threshold = threshold
                return [
                    {
                        "boxes": torch.tensor(
                            [
                                [1.0, 2.0, 11.0, 12.0],
                                [3.0, 4.0, 13.0, 14.0],
                                [5.0, 6.0, 15.0, 16.0],
                            ]
                        ),
                        "scores": torch.tensor([0.95, 0.99, 0.79]),
                        "labels": torch.tensor([1, 0, 1]),
                    }
                ]

        class FakeModel:
            config = SimpleNamespace(label2id={"bubble": 0, "text_bubble": 1, "text_free": 2})

            def __call__(self, **kwargs):
                return SimpleNamespace()

        processor = FakeProcessor()
        detector = TextBubbleDetector(processor, FakeModel(), torch.device("cpu"))
        image = np.zeros((20, 20, 3), dtype=np.uint8)

        boxes = detector.detect_text_bubbles(image)

        np.testing.assert_array_equal(boxes, np.array([[1.0, 2.0, 11.0, 12.0]], dtype=np.float32))
        self.assertEqual(processor.threshold, TEXT_BUBBLE_CONFIDENCE)

    async def test_translate_req_translates_sentences_concurrently(self) -> None:
        started = asyncio.Event()
        first_is_waiting = asyncio.Event()
        calls = []

        async def fake_translate_sentence(sentence: str) -> str:
            calls.append(sentence)
            if sentence == "a":
                first_is_waiting.set()
                await started.wait()
                return "译a"
            started.set()
            return "译b"

        with patch(
            "services.manga_translate.translate.translate_sentence",
            AsyncMock(side_effect=fake_translate_sentence),
        ) as translate_sentence_mock:
            result = await translate.translate_req(["a", "b"])

        self.assertEqual(result, ["译a", "译b"])
        self.assertEqual(calls, ["a", "b"])
        self.assertTrue(first_is_waiting.is_set())
        self.assertEqual(translate_sentence_mock.await_count, 2)

    async def test_translate_req_returns_empty_list_without_model(self) -> None:
        with patch("services.manga_translate.translate.get_translate_model") as get_model_mock:
            result = await translate.translate_req([])

        self.assertEqual(result, [])
        get_model_mock.assert_not_called()

    async def test_translate_req_keeps_blank_sentences(self) -> None:
        with patch(
            "services.manga_translate.translate.translate_sentence",
            AsyncMock(return_value="译文"),
        ) as translate_sentence_mock:
            result = await translate.translate_req(["  ", "hello"])

        self.assertEqual(result, ["  ", "译文"])
        translate_sentence_mock.assert_awaited_once_with("hello")

    async def test_translate_sentence_strips_response_and_falls_back_to_source(self) -> None:
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="  译文  ")))
        with patch("services.manga_translate.translate.get_translate_model", return_value=model):
            result = await translate.translate_sentence("hello")

        self.assertEqual(result, "译文")

        model.ainvoke.return_value = SimpleNamespace(content="  ")
        with patch("services.manga_translate.translate.get_translate_model", return_value=model):
            result = await translate.translate_sentence("hello")

        self.assertEqual(result, "hello")

    def test_is_manga_image_bytes_returns_true_when_text_bubbles_are_detected(self) -> None:
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        detector = SimpleNamespace(
            detect_text_bubbles=Mock(return_value=np.array([[1, 2, 3, 4]], dtype=np.float32))
        )

        with (
            patch("services.manga_translate.translate.decode_image", return_value=(image, None)),
            patch("services.manga_translate.translate.get_det_model", return_value=detector),
        ):
            result = translate.is_manga_image_bytes(b"raw-image")

        self.assertTrue(result)
        detector.detect_text_bubbles.assert_called_once_with(image)

    def test_is_manga_image_bytes_returns_false_without_text_bubbles(self) -> None:
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        detector = SimpleNamespace(
            detect_text_bubbles=Mock(return_value=np.empty((0, 4), dtype=np.float32))
        )

        with (
            patch("services.manga_translate.translate.decode_image", return_value=(image, None)),
            patch("services.manga_translate.translate.get_det_model", return_value=detector),
        ):
            result = translate.is_manga_image_bytes(b"raw-image")

        self.assertFalse(result)
        detector.detect_text_bubbles.assert_called_once_with(image)


if __name__ == "__main__":
    unittest.main()
