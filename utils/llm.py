import os


def get_base_url() -> str | None:
    return os.getenv("MOEGAL_LLM_GATEWAY_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
