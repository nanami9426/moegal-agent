import os


def get_base_url() -> str | None:
    return os.getenv("MOEGAL_LLM_GATEWAY_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None


def llm_user_headers(user_id: int | str | None) -> dict[str, str]:
    if user_id is None:
        raise ValueError("user_id is required for LLM requests.")

    user_id_text = str(user_id).strip()
    if not user_id_text:
        raise ValueError("user_id is required for LLM requests.")

    return {"X-User-ID": user_id_text}
