import os
import subprocess
import unittest
from unittest.mock import patch

from services.rsshub_container import (
    load_rsshub_docker_config,
    start_rsshub_stack,
    stop_rsshub_stack,
)


class RsshubContainerTest(unittest.TestCase):
    def test_loads_default_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_rsshub_docker_config()

        self.assertEqual(config.base_url, "http://127.0.0.1:1200")
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 1200)
        self.assertEqual(config.access_key, "moegal_rsshub")

    def test_accepts_base_url_without_scheme(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MOEGAL_RSSHUB_BASE_URL": "127.0.0.1:1200",
                "MOEGAL_RSSHUB_ACCESS_KEY": "custom_key",
            },
            clear=True,
        ):
            config = load_rsshub_docker_config()

        self.assertEqual(config.base_url, "http://127.0.0.1:1200")
        self.assertEqual(config.access_key, "custom_key")

    def test_start_creates_rsshub_and_redis_when_missing(self) -> None:
        commands: list[list[str]] = []

        def fake_docker(args: list[str], *, check: bool = True):
            commands.append(args)
            return subprocess.CompletedProcess(
                ["docker", *args],
                0,
                stdout="",
                stderr="",
            )

        def fake_docker_ok(args: list[str]) -> bool:
            commands.append(args)
            return False

        with (
            patch("services.rsshub_container.shutil.which", return_value="/usr/bin/docker"),
            patch("services.rsshub_container._docker", side_effect=fake_docker),
            patch("services.rsshub_container._docker_ok", side_effect=fake_docker_ok),
            patch("services.rsshub_container._wait_until_ready"),
            patch.dict(os.environ, {}, clear=True),
        ):
            runtime = start_rsshub_stack()

        self.assertEqual(runtime.container_names, ("rsshub", "rsshub-redis"))

        command_strings = [" ".join(command) for command in commands]
        self.assertIn("network create rss_default", command_strings)

        redis_run = next(command for command in commands if command[:2] == ["run", "-d"] and "redis:alpine" in command)
        self.assertIn("--network-alias", redis_run)
        self.assertIn("redis", redis_run)

        rsshub_run = next(
            command
            for command in commands
            if command[:2] == ["run", "-d"] and "diygod/rsshub:chromium-bundled" in command
        )
        self.assertIn("127.0.0.1:1200:1200", rsshub_run)
        self.assertIn("ACCESS_KEY=moegal_rsshub", rsshub_run)
        self.assertIn("REDIS_URL=redis://redis:6379/", rsshub_run)

    def test_stop_stops_rsshub_before_redis(self) -> None:
        stopped: list[str] = []

        def fake_docker(args: list[str], *, check: bool = True):
            if args[0] == "stop":
                stopped.append(args[1])
            return subprocess.CompletedProcess(["docker", *args], 0, stdout="", stderr="")

        with (
            patch("services.rsshub_container._container_exists", return_value=True),
            patch("services.rsshub_container._container_running", return_value=True),
            patch("services.rsshub_container._docker", side_effect=fake_docker),
        ):
            runtime = start_runtime()
            stop_rsshub_stack(runtime)

        self.assertEqual(stopped, ["rsshub", "rsshub-redis"])


def start_runtime():
    from services.rsshub_container import RsshubRuntime

    return RsshubRuntime(
        container_names=("rsshub", "rsshub-redis"),
    )


if __name__ == "__main__":
    unittest.main()
