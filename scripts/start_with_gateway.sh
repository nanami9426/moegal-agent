#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_BASE_URL="http://127.0.0.1:9426"
GATEWAY_BIN="${TMPDIR:-/tmp}/moegal-agent-gateway-$$"
gateway_pid=""

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

cleanup() {
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

(
	cd "${ROOT_DIR}/gateway"
	go build -o "${GATEWAY_BIN}" .
)

"${GATEWAY_BIN}" &
gateway_pid=$!
wait_for_gateway

cd "${ROOT_DIR}"
uv run python main.py "$@"
