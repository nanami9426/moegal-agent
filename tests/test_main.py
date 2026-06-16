import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import normalize_bots, parse_args, main


class MainArgsTest(unittest.TestCase):
    def test_normalize_bots_defaults_to_qq_and_tg(self) -> None:
        self.assertEqual(normalize_bots(None), ["qq", "tg"])

    def test_parse_args_accepts_single_bot(self) -> None:
        self.assertEqual(parse_args(["--bot", "qq"]).bot, ["qq"])

    def test_parse_args_accepts_comma_separated_bots(self) -> None:
        self.assertEqual(parse_args(["--bot", "qq,tg"]).bot, ["qq", "tg"])

    def test_parse_args_accepts_space_separated_bots(self) -> None:
        self.assertEqual(parse_args(["--bot", "qq", "tg"]).bot, ["qq", "tg"])

    def test_parse_args_rejects_unknown_bot(self) -> None:
        with patch("argparse.ArgumentParser._print_message"), self.assertRaises(SystemExit):
            parse_args(["--bot", "wx"])

    def test_main_only_starts_qq_when_bot_is_qq(self) -> None:
        refresher = SimpleNamespace(stop=Mock())
        with (
            patch("main.logger.info"),
            patch("main.init_settings"),
            patch("main.start_rsshub_stack", return_value="rsshub-runtime"),
            patch("main.stop_rsshub_stack") as stop_rsshub_stack,
            patch("main.init_db"),
            patch("main.init_ocr_models"),
            patch("main.start_rss_cache_refresher", return_value=refresher),
            patch("main.build_application") as build_application,
            patch("main.threading.Thread") as thread,
            patch("main.run_qq_client") as run_qq_client,
        ):
            main(bot=["qq"])

        build_application.assert_not_called()
        thread.assert_not_called()
        run_qq_client.assert_called_once_with()
        refresher.stop.assert_called_once_with()
        stop_rsshub_stack.assert_called_once_with("rsshub-runtime")

    def test_main_starts_qq_thread_and_tg_polling_when_both_are_enabled(self) -> None:
        application = SimpleNamespace(run_polling=Mock())
        refresher = SimpleNamespace(stop=Mock())
        with (
            patch("main.logger.info"),
            patch("main.init_settings"),
            patch("main.start_rsshub_stack", return_value="rsshub-runtime"),
            patch("main.stop_rsshub_stack"),
            patch("main.init_db"),
            patch("main.init_ocr_models"),
            patch("main.start_rss_cache_refresher", return_value=refresher),
            patch("main.build_application", return_value=application) as build_application,
            patch("main.threading.Thread") as thread,
            patch("main.run_qq_client") as run_qq_client,
        ):
            main(bot=["qq", "tg"])

        build_application.assert_called_once_with()
        thread.assert_called_once_with(
            target=run_qq_client,
            name="qq-bot",
            daemon=True,
        )
        thread.return_value.start.assert_called_once_with()
        run_qq_client.assert_not_called()
        application.run_polling.assert_called_once_with()
        refresher.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
