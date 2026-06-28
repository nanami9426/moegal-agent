#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_BASE_URL="http://127.0.0.1:9426"
GATEWAY_BIN="${TMPDIR:-/tmp}/moegal-agent-gateway-$$"
gateway_pid=""
web_pid=""

if [[ -f "${ROOT_DIR}/.env" ]]; then
	set -a
	# shellcheck disable=SC1091
	source "${ROOT_DIR}/.env"
	set +a
fi

if [[ -z "${OPENAI_BASE_URL:-}" ]]; then
	echo "Missing OPENAI_BASE_URL. Set the upstream OpenAI-compatible base URL in .env or the environment." >&2
	exit 1
fi

WEB_HOST="${MOEGAL_WEB_HOST:-127.0.0.1}"
WEB_PORT="${MOEGAL_WEB_PORT:-8000}"
WEB_CHECK_HOST="${WEB_HOST}"
if [[ "${WEB_CHECK_HOST}" == "0.0.0.0" ]]; then
	WEB_CHECK_HOST="127.0.0.1"
fi
WEB_BASE_URL="http://${WEB_CHECK_HOST}:${WEB_PORT}"

cleanup() {
	if [[ -n "${web_pid}" ]] && kill -0 "${web_pid}" 2>/dev/null; then
		kill "${web_pid}" 2>/dev/null || true
		wait "${web_pid}" 2>/dev/null || true
	fi
	if [[ -n "${gateway_pid}" ]] && kill -0 "${gateway_pid}" 2>/dev/null; then
		kill "${gateway_pid}" 2>/dev/null || true
		wait "${gateway_pid}" 2>/dev/null || true
	fi
	rm -f "${GATEWAY_BIN}"
}
trap cleanup EXIT

wait_for_gateway() {
	for _ in {1..50}; do
		if ! kill -0 "${gateway_pid}" 2>/dev/null; then
			wait "${gateway_pid}" 2>/dev/null || true
			echo "Gateway exited before becoming ready." >&2
			exit 1
		fi

		if command -v curl >/dev/null 2>&1; then
			if curl -fsS "${GATEWAY_BASE_URL}/healthz" >/dev/null 2>&1; then
				return 0
			fi
		elif python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=0.5).read()' "${GATEWAY_BASE_URL}/healthz" >/dev/null 2>&1; then
			return 0
		fi

		sleep 0.2
	done

	echo "Gateway did not become ready at ${GATEWAY_BASE_URL}." >&2
	exit 1
}

wait_for_web() {
	for _ in {1..50}; do
		if ! kill -0 "${web_pid}" 2>/dev/null; then
			wait "${web_pid}" 2>/dev/null || true
			echo "FastAPI service exited before becoming ready." >&2
			exit 1
		fi

		if command -v curl >/dev/null 2>&1; then
			if curl -fsS "${WEB_BASE_URL}/openapi.json" >/dev/null 2>&1; then
				return 0
			fi
		elif python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=0.5).read()' "${WEB_BASE_URL}/openapi.json" >/dev/null 2>&1; then
			return 0
		fi

		sleep 0.2
	done

	echo "FastAPI service did not become ready at ${WEB_BASE_URL}." >&2
	exit 1
}

start_web() {
	local cmd=(uv run uvicorn web.app:app --host "${WEB_HOST}" --port "${WEB_PORT}")
	if [[ "${MOEGAL_WEB_RELOAD:-0}" == "1" ]]; then
		cmd+=(--reload)
	fi

	(
		cd "${ROOT_DIR}"
		"${cmd[@]}"
	) &
	web_pid=$!
	wait_for_web
}

(
	cd "${ROOT_DIR}/gateway"
	go build -o "${GATEWAY_BIN}" .
)

"${GATEWAY_BIN}" &
gateway_pid=$!
wait_for_gateway
start_web

cd "${ROOT_DIR}"
uv run python main.py "$@"
