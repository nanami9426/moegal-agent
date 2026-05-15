import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from utils.logger import logger


RSSHUB_IMAGE = "diygod/rsshub:chromium-bundled"
RSSHUB_REDIS_IMAGE = "redis:alpine"
RSSHUB_CONTAINER_NAME = "rsshub"
RSSHUB_REDIS_CONTAINER_NAME = "rsshub-redis"
RSSHUB_NETWORK_NAME = "rss_default"
RSSHUB_WAIT_SECONDS = 30


@dataclass(frozen=True)
class RsshubDockerConfig:
    base_url: str
    host: str
    port: int
    access_key: str


@dataclass(frozen=True)
class RsshubRuntime:
    container_names: tuple[str, ...] = ()


def load_rsshub_docker_config() -> RsshubDockerConfig:
    base_url = _normalize_base_url(os.getenv("MOEGAL_RSSHUB_BASE_URL", "http://127.0.0.1:1200"))
    parsed_url = urlparse(base_url)
    host = parsed_url.hostname or "127.0.0.1"
    port = parsed_url.port or 1200

    return RsshubDockerConfig(
        base_url=base_url,
        host=host,
        port=port,
        access_key=os.getenv("MOEGAL_RSSHUB_ACCESS_KEY", "moegal_rsshub"),
    )


def start_rsshub_stack() -> RsshubRuntime:
    config = load_rsshub_docker_config()
    if not shutil.which("docker"):
        raise RuntimeError("Docker CLI not found. Cannot start RSSHub container.")

    container_names = (RSSHUB_CONTAINER_NAME, RSSHUB_REDIS_CONTAINER_NAME)

    try:
        _ensure_network(RSSHUB_NETWORK_NAME)
        _ensure_redis_container()
        _ensure_rsshub_container(config)
        _wait_until_ready(config.base_url, RSSHUB_WAIT_SECONDS)
    except Exception:
        stop_rsshub_stack(RsshubRuntime(container_names=container_names))
        raise

    logger.info("RSSHub is ready at %s", config.base_url)
    return RsshubRuntime(container_names=container_names)


def stop_rsshub_stack(runtime: RsshubRuntime) -> None:
    if not runtime.container_names:
        return

    # Stop RSSHub before Redis so the app container can close cleanly.
    for container_name in runtime.container_names:
        if not _container_exists(container_name) or not _container_running(container_name):
            continue

        try:
            _docker(["stop", container_name])
            logger.info("Stopped Docker container: %s", container_name)
        except RuntimeError as exc:
            logger.warning("Failed to stop Docker container %s: %s", container_name, exc)


def _ensure_network(network_name: str) -> None:
    if _docker_ok(["network", "inspect", network_name]):
        return

    _docker(["network", "create", network_name])


def _ensure_redis_container() -> None:
    if _container_exists(RSSHUB_REDIS_CONTAINER_NAME):
        if not _container_running(RSSHUB_REDIS_CONTAINER_NAME):
            _docker(["start", RSSHUB_REDIS_CONTAINER_NAME])
        return

    _docker(
        [
            "run",
            "-d",
            "--name",
            RSSHUB_REDIS_CONTAINER_NAME,
            "--network",
            RSSHUB_NETWORK_NAME,
            "--network-alias",
            "redis",
            RSSHUB_REDIS_IMAGE,
        ]
    )


def _ensure_rsshub_container(config: RsshubDockerConfig) -> None:
    if _container_exists(RSSHUB_CONTAINER_NAME):
        if not _container_running(RSSHUB_CONTAINER_NAME):
            _docker(["start", RSSHUB_CONTAINER_NAME])
        return

    _docker(
        [
            "run",
            "-d",
            "--name",
            RSSHUB_CONTAINER_NAME,
            "--network",
            RSSHUB_NETWORK_NAME,
            "-p",
            f"{config.host}:{config.port}:1200",
            "-e",
            "NODE_ENV=production",
            "-e",
            f"ACCESS_KEY={config.access_key}",
            "-e",
            "CACHE_TYPE=redis",
            "-e",
            "REDIS_URL=redis://redis:6379/",
            "-e",
            "CACHE_EXPIRE=600",
            RSSHUB_IMAGE,
        ]
    )


def _wait_until_ready(base_url: str, wait_seconds: int) -> None:
    deadline = time.monotonic() + wait_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            response = httpx.get(base_url, timeout=2.0)
            if response.status_code < 500:
                return
        except httpx.HTTPError as exc:
            last_error = exc

        time.sleep(1)

    raise RuntimeError(f"RSSHub did not become ready at {base_url}") from last_error


def _container_exists(container_name: str) -> bool:
    return _docker_ok(["container", "inspect", container_name])


def _container_running(container_name: str) -> bool:
    result = _docker(
        ["inspect", "-f", "{{.State.Running}}", container_name],
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _docker_ok(args: list[str]) -> bool:
    return _docker(args, check=False).returncode == 0


def _docker(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"docker {' '.join(args)} failed: {detail}")

    return result


def _normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url:
        return "http://127.0.0.1:1200"

    if "://" not in base_url:
        base_url = f"http://{base_url}"

    return base_url
